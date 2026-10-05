"""Bounded last-known monitoring snapshots; never raw traffic or training rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
import logging

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from cloud_database import CloudDatabaseError, connect
import cloud_push
from cloud_gateways import secret_hash

FRESHNESS_SECONDS = 90


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceMetadata(Metadata):
    mac: str = Field(pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
    name: str = Field(min_length=1, max_length=200)
    ip_address: str | None = Field(default=None, max_length=45)
    status: Literal["SAFE", "ATTACK", "UNKNOWN", "WARNING", "ALERT", "BLOCKED"]
    attack_probability: float = Field(ge=0, le=100, allow_inf_nan=False)
    blocked: bool


class AlertMetadata(Metadata):
    event_id: int = Field(ge=0)
    mac: str = Field(pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
    timestamp: datetime
    status: Literal["SAFE", "ATTACK", "UNKNOWN", "WARNING", "ALERT", "BLOCKED"]
    attack_probability: float = Field(ge=0, le=100, allow_inf_nan=False)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Alert timestamps must include a timezone.")
        return value


class ModelMetadata(Metadata):
    available: bool
    checkpoint_name: str | None = Field(default=None, max_length=200)
    updated_at: datetime | None = None

    @field_validator("updated_at")
    @classmethod
    def aware_updated_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Model timestamps must include a timezone.")
        return value


class MonitoringSnapshot(Metadata):
    observed_at: datetime
    devices: list[DeviceMetadata] = Field(max_length=500)
    alerts: list[AlertMetadata] = Field(max_length=100)
    model: ModelMetadata

    @field_validator("observed_at")
    @classmethod
    def valid_observation_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Observation time must include a timezone.")
        if value > datetime.now(timezone.utc) + timedelta(seconds=60):
            raise ValueError("Observation time is too far in the future.")
        return value

    @field_validator("devices")
    @classmethod
    def unique_devices(cls, value: list[DeviceMetadata]) -> list[DeviceMetadata]:
        if len({device.mac for device in value}) != len(value):
            raise ValueError("Each MAC address must appear once.")
        return value


def upload_snapshot(gateway_id: UUID, credential: str, snapshot: MonitoringSnapshot) -> dict:
    if not 32 <= len(credential) <= 256:
        raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
    with connect() as connection:
        gateway = connection.execute(
            "SELECT id, household_id FROM caughtin4k.gateways "
            "WHERE id = %s AND credential_hash = %s AND revoked_at IS NULL FOR UPDATE",
            (gateway_id, secret_hash(credential)),
        ).fetchone()
        if gateway is None:
            raise HTTPException(status_code=401, detail="Gateway credential is invalid.")
        if gateway["household_id"] is None:
            raise HTTPException(status_code=409, detail="Pair this gateway before uploading monitoring data.")
        stored = connection.execute(
            "INSERT INTO caughtin4k.gateway_snapshots "
            "(gateway_id, observed_at, devices, alerts, model) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (gateway_id) DO UPDATE SET "
            "observed_at = excluded.observed_at, received_at = now(), "
            "devices = excluded.devices, alerts = excluded.alerts, model = excluded.model "
            "WHERE excluded.observed_at > caughtin4k.gateway_snapshots.observed_at "
            "RETURNING received_at",
            (
                gateway_id, snapshot.observed_at,
                Jsonb([device.model_dump(mode="json") for device in snapshot.devices]),
                Jsonb([alert.model_dump(mode="json") for alert in snapshot.alerts]),
                Jsonb(snapshot.model.model_dump(mode="json")),
            ),
        ).fetchone()
        connection.execute(
            "UPDATE caughtin4k.gateways SET last_seen_at = now() WHERE id = %s", (gateway_id,),
        )
    if stored is not None:
        try:
            cloud_push.enqueue(gateway_id, snapshot)
        except CloudDatabaseError:
            logging.getLogger(__name__).error("Push enqueue unavailable; monitoring snapshot was saved.")
    return {"success": True, "snapshot_updated": stored is not None}


def freshness(last_seen_at: datetime | None, observed_at: datetime | None) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=FRESHNESS_SECONDS)
    return {
        "recent_contact": last_seen_at is not None and last_seen_at >= cutoff,
        "data_stale": observed_at is None or observed_at < cutoff,
        "freshness_seconds": FRESHNESS_SECONDS,
    }


def read_snapshot(account_id: UUID, household_id: UUID, gateway_id: UUID) -> dict:
    with connect() as connection:
        row = connection.execute(
            "SELECT g.id AS gateway_id, g.name, g.last_seen_at, g.revoked_at, "
            "s.observed_at, s.received_at, s.devices, s.alerts, s.model "
            "FROM caughtin4k.gateways g "
            "JOIN caughtin4k.household_members m ON m.household_id = g.household_id "
            "LEFT JOIN caughtin4k.gateway_snapshots s ON s.gateway_id = g.id "
            "WHERE g.id = %s AND g.household_id = %s AND m.account_id = %s",
            (gateway_id, household_id, account_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Gateway not found.")
    state = freshness(row["last_seen_at"], row["observed_at"])
    if row["revoked_at"] is not None:
        state = {**state, "recent_contact": False, "data_stale": True}
    return {
        **row, **state,
        "snapshot_available": row["received_at"] is not None,
    }
