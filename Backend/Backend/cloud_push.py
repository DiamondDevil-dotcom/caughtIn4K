"""Private, account-scoped Android push outbox; never client-selected topics."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from cloud_database import CloudDatabaseError, check_schema, connect

logger = logging.getLogger(__name__)
THREAT_STATUSES = {"WARNING", "ATTACK", "ALERT", "BLOCKED"}
MAX_AGE_SECONDS = 60


class InstallationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: UUID
    secret: str = Field(pattern=r"^[0-9a-f]{64}$")


class RegistrationInput(InstallationInput):
    token: str = Field(min_length=20, max_length=4096, pattern=r"^\S+$")


def enabled() -> bool:
    return os.getenv("GHOST_CLOUD_PUSH_ENABLED", "").lower() == "true"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def register(account: dict, payload: RegistrationInput) -> dict:
    if not enabled():
        raise HTTPException(status_code=503, detail="Background notifications are not enabled yet.")
    if account.get("email_verified_at") is None:
        raise HTTPException(status_code=403, detail="Verify your email before enabling notifications.")
    with connect() as connection:
        # All token ownership changes and sends serialize on this transaction lock.
        connection.execute("SELECT pg_advisory_xact_lock(734104006)")
        existing = connection.execute(
            "SELECT secret_hash FROM caughtin4k.push_installations WHERE installation_id = %s",
            (payload.installation_id,),
        ).fetchone()
        if existing and not hmac.compare_digest(existing["secret_hash"], digest(payload.secret)):
            raise HTTPException(status_code=403, detail="Notification installation credential is invalid.")
        connection.execute(
            "DELETE FROM caughtin4k.push_installations WHERE updated_at < now() - interval '30 days'"
        )
        count = connection.execute(
            "SELECT count(*) AS total FROM caughtin4k.push_installations "
            "WHERE account_id = %s AND installation_id <> %s AND token <> %s",
            (account["id"], payload.installation_id, payload.token),
        ).fetchone()
        if count["total"] >= 20:
            raise HTTPException(status_code=429, detail="Notification device limit reached. Sign out on an old device.")
        connection.execute(
            "DELETE FROM caughtin4k.push_installations WHERE token = %s AND installation_id <> %s",
            (payload.token, payload.installation_id),
        )
        # Account changes or token rotation must not carry the old account's queue.
        connection.execute(
            "DELETE FROM caughtin4k.push_deliveries WHERE installation_id = %s AND EXISTS "
            "(SELECT 1 FROM caughtin4k.push_installations WHERE installation_id = %s "
            "AND (account_id <> %s OR session_version <> %s OR token <> %s))",
            (payload.installation_id, payload.installation_id, account["id"],
             account["session_version"], payload.token),
        )
        connection.execute(
            "INSERT INTO caughtin4k.push_installations "
            "(installation_id, secret_hash, account_id, session_version, token) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (installation_id) DO UPDATE SET account_id = excluded.account_id, "
            "session_version = excluded.session_version, token = excluded.token, updated_at = now()",
            (payload.installation_id, digest(payload.secret), account["id"],
             account["session_version"], payload.token),
        )
    return {"success": True}


def unregister(payload: InstallationInput) -> dict:
    # The installation secret permits logout even after the account session expires.
    with connect() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(734104006)")
        connection.execute(
            "DELETE FROM caughtin4k.push_installations WHERE installation_id = %s AND secret_hash = %s",
            (payload.installation_id, digest(payload.secret)),
        )
    return {"success": True}


def fresh_events(snapshot, now: datetime) -> list:
    if not now - timedelta(seconds=MAX_AGE_SECONDS) <= snapshot.observed_at <= now:
        return []
    visible = {device.mac for device in snapshot.devices}
    return [
        event for event in snapshot.alerts
        if event.mac in visible and event.status in THREAT_STATUSES
        and now - timedelta(seconds=MAX_AGE_SECONDS) <= event.timestamp <= now
    ]


def event_key(event) -> str:
    return f"{event.event_id}:{int(event.timestamp.timestamp() * 1000)}"


def enqueue(gateway_id: UUID, snapshot) -> None:
    if not enabled():
        return
    now = datetime.now(timezone.utc)
    events = fresh_events(snapshot, now)
    if not events:
        return
    with connect() as connection:
        for event in events:
            connection.execute(
                "INSERT INTO caughtin4k.push_deliveries "
                "(installation_id, gateway_id, household_id, account_id, event_key, status, expires_at) "
                "SELECT i.installation_id, g.id, g.household_id, i.account_id, %s, %s, %s "
                "FROM caughtin4k.gateways g "
                "JOIN caughtin4k.household_members m ON m.household_id = g.household_id "
                "JOIN caughtin4k.accounts a ON a.id = m.account_id "
                "JOIN caughtin4k.push_installations i ON i.account_id = a.id "
                "WHERE g.id = %s AND g.revoked_at IS NULL AND a.email_verified_at IS NOT NULL "
                "AND i.session_version = a.session_version "
                "AND i.updated_at > now() - interval '30 days' "
                "ON CONFLICT (installation_id, gateway_id, event_key) DO NOTHING",
                (event_key(event), event.status,
                 event.timestamp + timedelta(seconds=MAX_AGE_SECONDS), gateway_id),
            )


def configure():
    import firebase_admin
    from firebase_admin import credentials

    check_schema()
    path = os.getenv("GHOST_FIREBASE_CREDENTIALS_FILE", "/etc/secrets/firebase-service-account.json")
    credential = credentials.Certificate(path)
    return firebase_admin.initialize_app(
        credential, {"httpTimeout": 10}, name="caughtin4k-push",
    )


def deliver_batch(app) -> None:
    from firebase_admin import exceptions, messaging
    from google.auth.exceptions import GoogleAuthError

    with connect() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(734104006)")
        rows = connection.execute(
            "SELECT d.*, i.token, (g.revoked_at IS NULL AND g.household_id = d.household_id "
            "AND i.account_id = d.account_id AND i.session_version = a.session_version "
            "AND a.email_verified_at IS NOT NULL AND m.account_id IS NOT NULL "
            "AND i.updated_at > now() - interval '30 days') AS authorized "
            "FROM caughtin4k.push_deliveries d "
            "JOIN caughtin4k.push_installations i USING (installation_id) "
            "JOIN caughtin4k.accounts a ON a.id = i.account_id "
            "JOIN caughtin4k.gateways g ON g.id = d.gateway_id "
            "LEFT JOIN caughtin4k.household_members m ON m.household_id = d.household_id "
            "AND m.account_id = i.account_id "
            "WHERE d.completed_at IS NULL AND d.next_attempt_at <= now() "
            "ORDER BY d.id LIMIT 10 FOR UPDATE OF d",
        ).fetchall()
        for row in rows:
            remaining = (row["expires_at"] - datetime.now(timezone.utc)).total_seconds()
            if not row["authorized"] or remaining <= 0 or row["attempts"] >= 4:
                connection.execute(
                    "UPDATE caughtin4k.push_deliveries SET completed_at = now() WHERE id = %s",
                    (row["id"],),
                )
                continue
            # Generic lock-screen text avoids exposing household/device details after logout.
            message = messaging.Message(
                token=row["token"],
                notification=messaging.Notification(
                    title={
                        "WARNING": "Suspicious activity rising",
                        "BLOCKED": "Device blocked",
                    }.get(row["status"], "Threat detected"),
                    body="Open caughtIn4K to review your home.",
                ),
                data={"gateway_id": str(row["gateway_id"]), "event_key": row["event_key"]},
                android=messaging.AndroidConfig(
                    priority="high", ttl=timedelta(seconds=remaining),
                    notification=messaging.AndroidNotification(
                        channel_id="caughtin4k_threats", sound="default",
                        tag=f'{row["gateway_id"]}:{row["event_key"]}',
                    ),
                ),
            )
            try:
                messaging.send(message, app=app)
            except messaging.UnregisteredError:
                connection.execute(
                    "DELETE FROM caughtin4k.push_installations WHERE installation_id = %s",
                    (row["installation_id"],),
                )
            except (exceptions.FirebaseError, GoogleAuthError) as error:
                code = error.code if isinstance(error, exceptions.FirebaseError) else "authentication"
                logger.warning("Push delivery failed (%s); bounded retry scheduled.", code)
                connection.execute(
                    "UPDATE caughtin4k.push_deliveries SET attempts = attempts + 1, "
                    "next_attempt_at = now() + (%s * interval '1 second') WHERE id = %s",
                    (2 ** (row["attempts"] + 1), row["id"]),
                )
            else:
                connection.execute(
                    "UPDATE caughtin4k.push_deliveries SET completed_at = now() WHERE id = %s",
                    (row["id"],),
                )
        connection.execute(
            "DELETE FROM caughtin4k.push_deliveries WHERE expires_at < now() - interval '1 day'"
        )
        connection.execute(
            "DELETE FROM caughtin4k.push_installations WHERE updated_at < now() - interval '30 days'"
        )


async def worker(app, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(deliver_batch, app)
        except CloudDatabaseError:
            logger.error("Push outbox storage unavailable; monitoring uploads remain independent.")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            pass
