import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from firebase_admin import exceptions, messaging
from pydantic import ValidationError

import cloud_accounts
import cloud_monitoring
import cloud_push as push
from cloud_account_api import build_router
from cloud_database import CloudDatabaseError


class PushTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"GHOST_CLOUD_PUSH_ENABLED": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.account = {"id": uuid4(), "session_version": 2,
                        "email_verified_at": datetime.now(timezone.utc)}
        self.installation = push.RegistrationInput(
            installation_id=uuid4(), secret="a" * 64, token="test-token-" + "b" * 32,
        )
        self.now = datetime.now(timezone.utc)
        self.event = cloud_monitoring.AlertMetadata(
            event_id=42, mac="aa:bb:cc:dd:ee:ff", timestamp=self.now,
            status="WARNING", attack_probability=75,
        )
        self.snapshot = cloud_monitoring.MonitoringSnapshot(
            observed_at=self.now, alerts=[self.event],
            devices=[cloud_monitoring.DeviceMetadata(
                mac=self.event.mac, name="Test device", status="BLOCKED",
                attack_probability=90, blocked=True,
            )],
            model=cloud_monitoring.ModelMetadata(available=False),
        )

    @contextmanager
    def connection(self, existing=None, deliveries=None):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.side_effect = [existing, {"total": 0}]
        self.db.execute.return_value.fetchall.return_value = deliveries or []
        yield self.db

    def queries(self):
        return "\n".join(call.args[0] for call in self.db.execute.call_args_list)

    def test_registration_only_uses_authenticated_identity(self):
        with patch.object(push, "connect", side_effect=self.connection):
            push.register(self.account, self.installation)
        call = self.db.execute.call_args_list[-1]
        self.assertIn("ON CONFLICT (installation_id)", call.args[0])
        self.assertEqual(call.args[1][2:4], (self.account["id"], 2))
        self.assertIn("DELETE FROM caughtin4k.push_deliveries", self.queries())
        self.assertNotIn(self.installation.secret, self.queries())

    def test_installation_secret_cannot_be_overridden(self):
        with patch.object(push, "connect", side_effect=lambda: self.connection(
            existing={"secret_hash": push.digest("c" * 64)},
        )):
            with self.assertRaises(HTTPException) as error:
                push.register(self.account, self.installation)
        self.assertEqual(error.exception.status_code, 403)
        self.assertNotIn("INSERT INTO", self.queries())

    def test_registration_requires_verified_account_and_enabled_service(self):
        with self.assertRaises(HTTPException) as error:
            push.register({**self.account, "email_verified_at": None}, self.installation)
        self.assertEqual(error.exception.status_code, 403)
        with patch.dict("os.environ", {"GHOST_CLOUD_PUSH_ENABLED": "false"}):
            with self.assertRaises(HTTPException) as error:
                push.register(self.account, self.installation)
        self.assertEqual(error.exception.status_code, 503)

    def test_payload_rejects_client_selected_household_or_account(self):
        for field in ("account_id", "household_id", "topic"):
            with self.assertRaises(ValidationError):
                push.RegistrationInput(**{**self.installation.model_dump(), field: str(uuid4())})

    def test_logout_secret_revokes_without_account_session(self):
        with patch.object(push, "connect", side_effect=self.connection):
            push.unregister(self.installation)
        query, values = self.db.execute.call_args.args
        self.assertIn("installation_id = %s AND secret_hash = %s", query)
        self.assertEqual(values, (self.installation.installation_id, push.digest(self.installation.secret)))

    def test_disable_rollout_flag_does_not_skip_logout_revocation(self):
        with (
            patch.dict("os.environ", {"GHOST_CLOUD_PUSH_ENABLED": "false"}),
            patch.object(push, "connect", side_effect=self.connection),
        ):
            push.unregister(self.installation)
        self.assertIn("DELETE FROM caughtin4k.push_installations", self.queries())

    def test_registration_limit_is_explicit_not_an_unbounded_outbox(self):
        @contextmanager
        def full_connection():
            self.db = MagicMock()
            self.db.execute.return_value.fetchone.side_effect = [None, {"total": 20}]
            yield self.db
        with patch.object(push, "connect", side_effect=full_connection):
            with self.assertRaises(HTTPException) as error:
                push.register(self.account, self.installation)
        self.assertEqual(error.exception.status_code, 429)
        self.assertNotIn("INSERT INTO", self.queries())

    def test_fresh_events_include_warning_despite_current_blocked_state(self):
        self.assertEqual(push.fresh_events(self.snapshot, self.now), [self.event])
        for status in ("SAFE", "UNKNOWN"):
            snapshot = self.snapshot.model_copy(update={
                "alerts": [self.event.model_copy(update={"status": status})],
            })
            self.assertEqual(push.fresh_events(snapshot, self.now), [])

    def test_stale_future_removed_events_are_not_sent(self):
        for timestamp in (self.now - timedelta(seconds=61), self.now + timedelta(seconds=1)):
            snapshot = self.snapshot.model_copy(update={
                "alerts": [self.event.model_copy(update={"timestamp": timestamp})],
            })
            self.assertEqual(push.fresh_events(snapshot, self.now), [])
        self.assertEqual(push.fresh_events(
            self.snapshot.model_copy(update={"devices": []}), self.now,
        ), [])
        self.assertEqual(push.fresh_events(self.snapshot, self.now + timedelta(seconds=61)), [])

    def test_enqueue_filters_current_membership_verified_account_and_session(self):
        with patch.object(push, "connect", side_effect=self.connection):
            push.enqueue(uuid4(), self.snapshot)
        query = self.queries()
        for required in (
            "m.household_id = g.household_id", "i.account_id = a.id",
            "g.revoked_at IS NULL", "a.email_verified_at IS NOT NULL",
            "i.session_version = a.session_version",
            "ON CONFLICT (installation_id, gateway_id, event_key) DO NOTHING",
        ):
            self.assertIn(required, query)

    def row(self, **values):
        return {
            "id": 1, "installation_id": self.installation.installation_id,
            "gateway_id": uuid4(), "event_key": push.event_key(self.event),
            "status": "WARNING",
            "token": self.installation.token, "authorized": True,
            "expires_at": self.now + timedelta(seconds=50), "attempts": 0,
            **values,
        }

    def test_delivery_is_generic_and_uses_event_tag_and_channel(self):
        row = self.row()
        with (
            patch.object(push, "connect", side_effect=lambda: self.connection(deliveries=[row])),
            patch.object(messaging, "send") as send,
        ):
            push.deliver_batch(MagicMock())
        message = send.call_args.args[0]
        self.assertEqual(message.token, row["token"])
        self.assertEqual(message.android.notification.channel_id, "caughtin4k_threats")
        self.assertEqual(message.data["gateway_id"], str(row["gateway_id"]))
        self.assertEqual(message.notification.title, "Suspicious activity rising")
        self.assertNotIn("Test device", message.notification.body)
        self.assertIn("completed_at = now()", self.queries())
        for constraint in (
            "g.household_id = d.household_id", "i.account_id = d.account_id",
            "i.session_version = a.session_version", "m.account_id IS NOT NULL",
        ):
            self.assertIn(constraint, self.queries())

    def test_revoked_expired_and_exhausted_deliveries_do_not_send(self):
        for row in (
            self.row(authorized=False), self.row(expires_at=self.now - timedelta(seconds=1)),
            self.row(attempts=4),
        ):
            with (
                patch.object(push, "connect", side_effect=lambda: self.connection(deliveries=[row])),
                patch.object(messaging, "send") as send,
            ):
                push.deliver_batch(MagicMock())
            send.assert_not_called()

    def test_invalid_token_is_deleted_and_transient_failure_retries(self):
        for error, query in (
            (messaging.UnregisteredError("test"), "DELETE FROM caughtin4k.push_installations"),
            (exceptions.UnavailableError("test"), "attempts = attempts + 1"),
        ):
            with (
                patch.object(push, "connect", side_effect=lambda: self.connection(deliveries=[self.row()])),
                patch.object(messaging, "send", side_effect=error),
            ):
                push.deliver_batch(MagicMock())
            self.assertIn(query, self.queries())

    def test_push_storage_failure_does_not_reject_saved_monitoring_snapshot(self):
        gateway = uuid4()
        with (
            patch.object(cloud_monitoring, "connect", side_effect=lambda: self.connection()),
            patch.object(push, "enqueue", side_effect=CloudDatabaseError("test")),
        ):
            self.db = MagicMock()
            @contextmanager
            def saved_connection():
                self.db.execute.return_value.fetchone.side_effect = [
                    {"household_id": uuid4()}, {"received_at": self.now},
                ]
                yield self.db
            with patch.object(cloud_monitoring, "connect", side_effect=saved_connection):
                result = cloud_monitoring.upload_snapshot(gateway, "x" * 32, self.snapshot)
        self.assertTrue(result["success"])


class PushApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(build_router("test-secret-" + "x" * 32, require_verified=True))
        self.client = TestClient(app)
        self.payload = {"installation_id": str(uuid4()), "secret": "a" * 64, "token": "t" * 32}

    def test_unauthenticated_and_unverified_cannot_register(self):
        self.assertEqual(self.client.post("/cloud/push/register", json=self.payload).status_code, 401)
        with patch.object(cloud_accounts, "authenticate", return_value={"id": uuid4()}):
            result = self.client.post(
                "/cloud/push/register", json=self.payload,
                headers={"Authorization": "Bearer test"},
            )
        self.assertEqual(result.status_code, 403)

    def test_unregister_uses_installation_secret_not_expired_session(self):
        with patch.object(push, "unregister", return_value={"success": True}) as unregister:
            result = self.client.post("/cloud/push/unregister", json={
                key: value for key, value in self.payload.items() if key != "token"
            })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(unregister.call_args.args[0].secret, self.payload["secret"])


if __name__ == "__main__":
    unittest.main()
