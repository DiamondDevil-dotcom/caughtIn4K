import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import consumer_setup_agent as agent
from cloud_uploader import PermanentUploadError, UploadConfig


class ConsumerSetupTests(unittest.TestCase):
    def setUp(self):
        self.configuration = {"request_id": str(uuid4()), "ssid": "My IoT;[]", "password": r"test \ password"}
        self.config = UploadConfig(
            cloud_url="https://cloud.example", gateway_id=uuid4(), credential="x" * 32, router_token="token",
        )

    def test_ap_profile_escapes_secrets_and_never_touches_ethernet(self):
        profile = agent.wifi_profile(self.configuration)
        self.assertIn("mode=ap", profile)
        self.assertIn("interface-name=wlan0", profile)
        self.assertIn("method=shared", profile)
        self.assertNotIn("eth0", profile)
        self.assertIn("ssid=" + "".join(f"{byte};" for byte in self.configuration["ssid"].encode()), profile)
        self.assertIn(r"psk=test\s\\\spassword", profile)
        for changes in ({"ssid": "bad\nkey=x"}, {"password": "bad\npassword"}, {"request_id": "not-a-uuid"}):
            with self.assertRaises(PermanentUploadError):
                agent.wifi_profile({**self.configuration, **changes})

    def test_success_is_persisted_without_password_and_commands_are_fixed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(agent, "run_command") as run:
            profile, state = Path(directory) / "wifi", Path(directory) / "state"
            agent.apply_wifi(self.configuration, profile, state)
            self.assertEqual(agent.read_revision(state), self.configuration["request_id"])
            self.assertNotIn(self.configuration["password"], state.read_text())
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                self.assertNotIn(self.configuration["password"], call.args[0])
                self.assertNotIn("eth0", call.args[0])

    def test_apply_failure_restores_previous_profile_and_never_records_success(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, state = Path(directory) / "wifi", Path(directory) / "state"
            profile.write_text("previous-private-profile", encoding="utf-8")
            with patch.object(agent, "run_command", side_effect=[
                "", agent.SetupError("network_configuration_failed"), "", "",
            ]):
                with self.assertRaises(agent.SetupError):
                    agent.apply_wifi(self.configuration, profile, state)
            self.assertEqual(profile.read_text(), "previous-private-profile")
            self.assertIsNone(agent.read_revision(state))

    def test_lost_ack_after_restart_does_not_reapply_applied_revision(self):
        with (
            patch.object(agent, "read_revision", return_value=self.configuration["request_id"]),
            patch.object(agent, "local_checks", return_value=dict.fromkeys(
                ("ethernet", "wifi", "router", "model", "firewall"), True,
            )),
            patch.object(agent, "endpoint_json", return_value={"paired": True, "configuration": self.configuration}),
            patch.object(agent, "apply_wifi") as apply,
        ):
            worker = agent.SetupWorker(self.config)
            worker.poll()
            restarted = agent.SetupWorker(self.config)
            restarted.poll()
            apply.assert_not_called()

    def test_failure_reports_safe_code_without_repeated_network_mutations(self):
        checks = dict.fromkeys(("ethernet", "wifi", "router", "model", "firewall"), False)
        with (
            patch.object(agent, "read_revision", return_value=None),
            patch.object(agent, "local_checks", return_value=checks),
            patch.object(agent, "endpoint_json", return_value={"paired": True, "configuration": self.configuration}) as exchange,
            patch.object(agent, "apply_wifi", side_effect=agent.SetupError("network_configuration_failed")) as apply,
            self.assertLogs(agent.logger, level="ERROR"),
        ):
            worker = agent.SetupWorker(self.config)
            worker.poll()
            worker.poll()
            apply.assert_called_once()
            request = exchange.call_args.args[1]
            report = json.loads(request.data)
            self.assertEqual(report["error_code"], "network_configuration_failed")
            self.assertNotIn("password", report)

    def test_readiness_requires_actual_ap_and_firewall_not_only_model(self):
        def command(args, **kwargs):
            if args[0] == "ip":
                return '[{"dev":"eth0"}]'
            if args[0] == "nmcli":
                return self.configuration["request_id"]
            if args[0] == "iw":
                return "Interface wlan0\n\ttype AP"
            return json.dumps({"nftables": [
                {"set": {"name": "blocked_macs"}}, {"chain": {"name": "input_filter"}},
                {"chain": {"name": "forward_filter"}},
            ]})
        snapshot = {"observed_at": "now", "devices": [], "alerts": [], "model": {"available": True}}
        with patch.object(agent, "run_command", side_effect=command), patch.object(agent, "endpoint_json", return_value=snapshot):
            checks = agent.local_checks(self.config, None, self.configuration["request_id"])
            self.assertTrue(all(checks.values()))
            self.assertFalse(agent.local_checks(self.config, None, str(uuid4()))["wifi"])
        with (
            patch.object(agent, "run_command", side_effect=agent.SetupError("network_configuration_failed")),
            patch.object(agent, "endpoint_json", return_value=snapshot),
            self.assertLogs(agent.logger, level="WARNING"),
        ):
            checks = agent.local_checks(self.config, None, self.configuration["request_id"])
            self.assertTrue(checks["model"])
            self.assertFalse(checks["firewall"])
            self.assertFalse(checks["ethernet"])


if __name__ == "__main__":
    unittest.main()
