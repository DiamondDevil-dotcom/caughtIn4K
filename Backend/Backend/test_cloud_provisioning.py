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
