import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import cloud_accounts as accounts
import cloud_monitoring as monitoring
from cloud_account_api import build_router
from cloud_gateways import secret_hash


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "devices": [], "alerts": [], "model": {"available": False},
        }

    @contextmanager
    def connection(self, rows):
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.side_effect = rows
        yield self.db

    def test_snapshot_forbids_training_or_raw_packet_fields(self):
        for field in ("packets", "training_rows", "household_id", "account_id"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                monitoring.MonitoringSnapshot(**{**self.payload, field: []})

    def test_federated_progress_is_bounded_metadata_not_weights_or_training_rows(self):
        value = {
            "observed_at": datetime.now(timezone.utc),
            "status": "federated", "federated_round": 4,
            "training": {"state": "running", "current_round": 5, "total_rounds": 10},
        }
        model = monitoring.ModelMetadata(available=True, federated=value)
        self.assertEqual(model.federated.training.current_round, 5)
        for extra in ("weights", "training_rows", "coordinator_url"):
            with self.assertRaises(ValidationError):
                monitoring.FederatedMetadata(**{**value, extra: []})
        with self.assertRaises(ValidationError):
            monitoring.TrainingMetadata(state="fake", current_round=0, total_rounds=10)

    def test_future_and_naive_observation_times_rejected(self):
        for time in (datetime.now(), datetime.now(timezone.utc) + timedelta(minutes=5)):
            with self.assertRaises(ValidationError):
                monitoring.MonitoringSnapshot(**{**self.payload, "observed_at": time})

    def test_real_pi_detection_states_and_percentages_are_preserved(self):
        for status in ("SAFE", "WARNING", "ALERT", "BLOCKED"):
            snapshot = monitoring.MonitoringSnapshot(**{
                **self.payload,
                "devices": [{
                    "mac": "aa:bb:cc:dd:ee:ff", "name": "Device", "status": status,
                    "attack_probability": 75, "blocked": status == "BLOCKED",
                }],
            })
            self.assertEqual(snapshot.devices[0].status, status)
            self.assertEqual(snapshot.devices[0].attack_probability, 75)

    def test_upload_scopes_machine_identity_and_does_not_overwrite_newer_data(self):
        gateway_id, household_id = uuid4(), uuid4()
        credential = "test-only-gateway-credential-32-characters"
        with patch.object(monitoring, "connect", side_effect=lambda: self.connection([
            {"id": gateway_id, "household_id": household_id}, None,
        ])):
            result = monitoring.upload_snapshot(
                gateway_id, credential, monitoring.MonitoringSnapshot(**self.payload),
            )
        calls = self.db.execute.call_args_list
        self.assertEqual(calls[0].args[1], (gateway_id, secret_hash(credential)))
        self.assertIn("revoked_at IS NULL FOR UPDATE", calls[0].args[0])
        self.assertIn("excluded.observed_at > caughtin4k.gateway_snapshots.observed_at", calls[1].args[0])
        self.assertEqual(result, {"success": True, "snapshot_updated": False})

    def test_wrong_credential_or_unpaired_gateway_cannot_write(self):
        for row, status in ((None, 401), ({"household_id": None}, 409)):
            with patch.object(monitoring, "connect", side_effect=lambda: self.connection([row])):
                with self.assertRaises(HTTPException) as caught:
                    monitoring.upload_snapshot(
                        uuid4(), "test-only-gateway-credential-32-characters",
                        monitoring.MonitoringSnapshot(**self.payload),
                    )
            self.assertEqual(caught.exception.status_code, status)
            self.assertEqual(self.db.execute.call_count, 1)

    def test_recent_contact_does_not_make_old_data_fresh(self):
        now = datetime.now(timezone.utc)
        result = monitoring.freshness(now, now - timedelta(minutes=10))
        self.assertTrue(result["recent_contact"])
        self.assertTrue(result["data_stale"])
        self.assertEqual(monitoring.freshness(None, None)["recent_contact"], False)

    def test_freshness_exact_threshold(self):
        now = datetime.now(timezone.utc)
        with patch.object(monitoring, "datetime") as clock:
            clock.now.return_value = now
            threshold = now - timedelta(seconds=90)
            self.assertFalse(monitoring.freshness(threshold, threshold)["data_stale"])
            self.assertFalse(monitoring.freshness(
                threshold - timedelta(microseconds=1), threshold,
            )["recent_contact"])

    def test_snapshot_read_filters_both_household_and_account(self):
        account_id, home, gateway_id = uuid4(), uuid4(), uuid4()
        with patch.object(monitoring, "connect", side_effect=lambda: self.connection([None])):
            with self.assertRaises(HTTPException) as caught:
                monitoring.read_snapshot(account_id, home, gateway_id)
        self.assertEqual(caught.exception.status_code, 404)
        query, values = self.db.execute.call_args.args
        self.assertEqual(values, (gateway_id, home, account_id))
        self.assertIn("m.account_id = %s", query)

    def test_no_snapshot_is_distinct_from_empty_device_list(self):
        row = {
            "gateway_id": uuid4(), "name": "Pi", "last_seen_at": None, "revoked_at": None,
            "observed_at": None, "received_at": None, "devices": None, "alerts": None, "model": None,
        }
        with patch.object(monitoring, "connect", side_effect=lambda: self.connection([row])):
            result = monitoring.read_snapshot(uuid4(), uuid4(), row["gateway_id"])
        self.assertFalse(result["snapshot_available"])
        self.assertIsNone(result["devices"])
        self.assertTrue(result["data_stale"])


class MonitoringApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(build_router("test-only-secret-at-least-32-characters"))
        self.client = TestClient(app)
        self.gateway_id, self.home, self.account_id = uuid4(), uuid4(), uuid4()
        self.payload = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "devices": [], "alerts": [], "model": {"available": False},
        }

    def test_user_token_does_not_replace_machine_credential(self):
        result = self.client.put(
            f"/cloud/gateways/{self.gateway_id}/snapshot", json=self.payload,
            headers={"Authorization": "Bearer user-token"},
        )
        self.assertEqual(result.status_code, 401)

    def test_snapshot_get_requires_account_authentication(self):
        result = self.client.get(f"/cloud/households/{self.home}/gateways/{self.gateway_id}/snapshot")
        self.assertEqual(result.status_code, 401)

    def test_account_identity_cannot_be_overridden_in_snapshot_get(self):
        with (
            patch.object(accounts, "authenticate", return_value={"id": self.account_id}),
            patch.object(monitoring, "read_snapshot", return_value={"snapshot_available": False}) as read,
        ):
            result = self.client.get(
                f"/cloud/households/{self.home}/gateways/{self.gateway_id}/snapshot?account_id={uuid4()}",
                headers={"Authorization": "Bearer test"},
            )
        self.assertEqual(result.status_code, 200)
        read.assert_called_once_with(self.account_id, self.home, self.gateway_id)

    def test_uploaded_gateway_id_comes_from_path_not_body(self):
        with patch.object(monitoring, "upload_snapshot") as upload:
            result = self.client.put(
                f"/cloud/gateways/{self.gateway_id}/snapshot",
                json={**self.payload, "gateway_id": str(uuid4())},
                headers={"X-Gateway-Credential": "test-only-gateway-credential-32-characters"},
            )
        self.assertEqual(result.status_code, 422)
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
