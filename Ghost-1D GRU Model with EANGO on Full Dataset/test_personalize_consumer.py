import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from router_setup import personalize_consumer as factory


class PersonalizationTests(unittest.TestCase):
    def test_factory_identity_is_unique_private_and_never_overwritten(self):
        simulated_linux = SimpleNamespace(
            name="posix", geteuid=lambda: 0, open=os.open, fdopen=os.fdopen,
            fsync=os.fsync, chown=lambda *args: None,
            O_WRONLY=os.O_WRONLY, O_CREAT=os.O_CREAT, O_EXCL=os.O_EXCL,
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(factory, "os", simulated_linux):
            base = Path(directory)
            identities = []
            for name in ("device-a", "device-b"):
                bundle = base / f"bundle-{name}"
                bundle.mkdir()
                (bundle / "consumer-setup.txt").write_text("enabled\n")
                (bundle / "gateway.env").write_text(
                    "GHOST_CLOUD_UPLOAD_ENABLED=false\n"
                    "GHOST_CLOUD_API_URL=https://cloud.example\n"
                    f"GHOST_CLOUD_GATEWAY_ID={uuid4()}\n"
                    f"GHOST_CLOUD_GATEWAY_CREDENTIAL={uuid4().hex}\n",
                )
                root = base / name
                (root / "opt/caughtin4k").mkdir(parents=True)
                (root / "opt/caughtin4k/consumer_setup_agent.py").touch()
                (root / "etc/caughtin4k").mkdir(parents=True)
                factory.personalize(root, bundle)
                target = root / "etc/caughtin4k/device.env"
                identities.append(target.read_text())
                self.assertIn("GHOST_CLOUD_UPLOAD_ENABLED=true", target.read_text())
                self.assertNotIn("pairing_code", target.read_text())
                with self.assertRaises(ValueError):
                    factory.personalize(root, bundle)
                self.assertEqual(target.read_text(), identities[-1])
            self.assertNotEqual(identities[0], identities[1])
            other = base / "duplicate-image"
            (other / "opt/caughtin4k").mkdir(parents=True)
            (other / "opt/caughtin4k/consumer_setup_agent.py").touch()
            (other / "etc/caughtin4k").mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                factory.personalize(other, bundle)
            self.assertFalse((other / "etc/caughtin4k/device.env").exists())

    def test_personalization_rejects_live_host(self):
        with self.assertRaises(ValueError):
            factory.personalize(Path("/"), Path("unused"))


if __name__ == "__main__":
    unittest.main()
