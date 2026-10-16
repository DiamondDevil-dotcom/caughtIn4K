import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import provision_cloud_gateway as provisioning


class ProvisioningTests(unittest.TestCase):
    @contextmanager
    def connection(self):
        self.db = MagicMock()
        yield self.db

    def test_private_bundle_separates_customer_code_and_machine_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            with patch.object(provisioning, "connect", side_effect=self.connection):
                gateway_id = provisioning.provision_bundle(
                    "New Pi", datetime.now(timezone.utc) + timedelta(days=1),
                    "https://cloud.example", output,
                )
            machine = (output / "gateway.env").read_text()
            label = json.loads((output / "pairing-label.json").read_text())
            self.assertIn("GHOST_CLOUD_UPLOAD_ENABLED=false", machine)
            self.assertEqual(label["gateway_id"], gateway_id)
            self.assertNotIn(label["pairing_code"], machine)
            self.assertNotIn("gateway_credential", label)
            machine_secret = machine.split("GHOST_CLOUD_GATEWAY_CREDENTIAL=")[1].strip()
            self.assertNotIn(machine_secret, json.dumps(label))

    def test_existing_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(provisioning, "connect") as connect:
                with self.assertRaises(FileExistsError):
                    provisioning.provision_bundle(
                        "Pi", datetime.now(timezone.utc) + timedelta(days=1),
                        "https://cloud.example", Path(directory),
                    )
            connect.assert_not_called()

    def test_verified_purchase_is_bound_by_factory_not_included_in_qr(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "consumer"
            with patch.object(provisioning, "connect", side_effect=self.connection):
                gateway = provisioning.provision_bundle(
                    "Pi", datetime.now(timezone.utc) + timedelta(days=1),
                    "https://cloud.example", output, verified_order=" order-123 ",
                    purchaser_email=" Buyer@Example.com ",
                )
            purchase = [call for call in self.db.execute.call_args_list
                        if "INSERT INTO caughtin4k.gateway_purchases" in call.args[0]]
            self.assertEqual(purchase[0].args[1], (gateway, "order-123", "buyer@example.com"))
            self.assertNotIn("buyer", (output / "pairing-label.json").read_text())

    def test_partial_purchase_binding_rejected_before_writing(self):
        with patch.object(provisioning, "create_private_directory") as create:
            for kwargs in ({"verified_order": "order"}, {"purchaser_email": "buyer@example.com"}):
                with self.assertRaises(ValueError):
                    provisioning.provision_bundle(
                        "Pi", datetime.now(timezone.utc) + timedelta(days=1),
                        "https://cloud.example", Path("unused"), **kwargs,
                    )
        create.assert_not_called()

    def test_consumer_setup_is_explicit_and_preserves_the_three_field_qr(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "consumer"
            with patch.object(provisioning, "connect", side_effect=self.connection):
                gateway_id = provisioning.provision_bundle(
                    "Consumer Pi", datetime.now(timezone.utc) + timedelta(days=1),
                    "https://cloud.example", output, consumer_setup=True,
                )
            self.assertEqual(set(json.loads((output / "pairing-label.json").read_text())),
                             {"version", "gateway_id", "pairing_code"})
            self.assertEqual((output / "consumer-setup.txt").read_text(), "enabled\n")
            self.assertTrue(any(
                "SET consumer_setup = TRUE" in call.args[0] and call.args[1] == (gateway_id,)
                for call in self.db.execute.call_args_list
            ))

    def test_repository_output_rejected(self):
        with self.assertRaises(provisioning.ProvisioningError):
            provisioning.create_private_directory(Path(__file__).resolve().parent / "private-bundle")

    def test_invalid_cloud_origin_rejected_before_writing(self):
        for value in ("http://cloud.example", "https://cloud.example\nSECRET=x",
                      "https://cloud.example/path", "https://cloud.example:bad"):
            with patch.object(provisioning, "create_private_directory") as create:
                with self.assertRaises(ValueError):
                    provisioning.provision_bundle(
                        "Pi", datetime.now(timezone.utc) + timedelta(days=1), value, Path("unused"),
                    )
            create.assert_not_called()

    def test_file_write_failure_reaches_transaction_boundary(self):
        connection = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(provisioning, "connect", return_value=connection),
                patch.object(provisioning, "write_private_file", side_effect=OSError("disk full")),
            ):
                with self.assertRaises(OSError):
                    provisioning.provision_bundle(
                        "Pi", datetime.now(timezone.utc) + timedelta(days=1),
                        "https://cloud.example", Path(directory) / "bundle",
                    )
            self.assertIs(connection.__exit__.call_args.args[0], OSError)


if __name__ == "__main__":
    unittest.main()
