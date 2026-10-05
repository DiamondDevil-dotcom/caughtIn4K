import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import cloud_control_agent as agent
from cloud_uploader import UploadConfig, UploadError, PermanentUploadError


class ControlAgentTests(unittest.TestCase):
    def setUp(self):
        self.config = UploadConfig(
            "https://staging.example", uuid4(),
            "test-only-machine-credential-32-characters", "private-local-token",
            staging_token="test-only-staging-token-32-characters",
        )
        self.command = {
            "command_id": str(uuid4()), "action": "block", "mac": "aa:bb:cc:dd:ee:ff",
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
        }
        self.result = {"success": True, "result_code": "applied"}

    def test_credentials_remain_separate_and_only_allowlisted_action_reaches_pi(self):
        with patch.object(agent, "endpoint_json", side_effect=[
            {"command": self.command}, self.result, {"success": True, "status": "succeeded"},
        ]) as request:
            agent.ControlWorker(self.config, MagicMock()).poll()
        cloud, local, ack = [call.args[1] for call in request.call_args_list]
        for req in (cloud, ack):
            self.assertEqual(req.get_header("X-gateway-credential"), self.config.credential)
            self.assertEqual(req.get_header("X-cloud-staging-token"), self.config.staging_token)
            self.assertIsNone(req.get_header("X-gateway-token"))
        self.assertEqual(local.get_header("X-gateway-token"), self.config.router_token)
        self.assertIsNone(local.get_header("X-gateway-credential"))
        self.assertIsNone(local.get_header("X-cloud-staging-token"))
        self.assertEqual(json.loads(local.data), self.command)

    def test_ack_retry_never_reexecutes_network_action(self):
        worker = agent.ControlWorker(self.config, MagicMock())
        with patch.object(agent, "endpoint_json", side_effect=[
            {"command": self.command}, self.result, UploadError("offline"), {"success": True},
        ]) as request:
            with self.assertRaises(UploadError):
                worker.poll()
            worker.poll()
        self.assertEqual([call.args[1].method for call in request.call_args_list], ["POST", "POST", "PUT", "PUT"])
        self.assertIsNone(worker.pending_result)

    def test_expired_and_invalid_commands_never_reach_firewall(self):
        expired = {**self.command, "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
        with patch.object(agent, "endpoint_json") as request:
            self.assertEqual(agent.apply_local(self.config, MagicMock(), expired),
                             {"success": False, "result_code": "expired"})
            request.assert_not_called()
        for changes in ({"action": "shell"}, {"mac": ";sudo reboot"}, {"command_id": "invalid"},
                        {"expires_at": "2026-10-05T00:00:00"}, {"raw_command": "shutdown"}):
            with self.assertRaises(PermanentUploadError):
                agent.validate_command({**self.command, **changes})

    def test_local_timeout_is_not_retried_and_is_unconfirmed(self):
        with patch.object(agent, "endpoint_json", side_effect=UploadError("offline")) as request:
            result = agent.apply_local(self.config, MagicMock(), self.command)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result, {"success": False, "result_code": "local_unreachable"})

    def test_dry_run_and_rejected_controls_never_report_success(self):
        for response in ({"success": False, "result_code": "enforcement_failed"},
                         PermanentUploadError("HTTP 403")):
            with patch.object(agent, "endpoint_json", side_effect=[response]):
                self.assertFalse(agent.apply_local(self.config, MagicMock(), self.command)["success"])
        with patch.object(agent, "endpoint_json", return_value={"success": True, "result_code": "dry_run"}):
            with self.assertRaises(PermanentUploadError):
                agent.apply_local(self.config, MagicMock(), self.command)

    def test_no_commands_means_no_local_requests(self):
        with patch.object(agent, "endpoint_json", return_value={"command": None}) as request:
            agent.ControlWorker(self.config, MagicMock()).poll()
        self.assertEqual(request.call_count, 1)

    def test_training_ack_retry_does_not_start_second_run(self):
        command = {**self.command, "action": "train", "mac": None}
        self.assertEqual(agent.validate_command(command), command)
        with self.assertRaises(PermanentUploadError):
            agent.validate_command({**command, "mac": self.command["mac"]})
        worker = agent.ControlWorker(self.config, MagicMock())
        with patch.object(agent, "endpoint_json", side_effect=[
            {"command": command}, self.result, UploadError("offline"), {"success": True},
        ]) as request:
            with self.assertRaises(UploadError):
                worker.poll()
            worker.poll()
        self.assertEqual([call.args[1].method for call in request.call_args_list], ["POST", "POST", "PUT", "PUT"])

    def test_coordinator_lost_start_response_remains_unconfirmed(self):
        command = {**self.command, "action": "train", "mac": None}
        with patch.object(agent, "endpoint_json", return_value={
            "success": False, "result_code": "local_unreachable",
        }):
            self.assertEqual(agent.apply_local(self.config, MagicMock(), command),
                {"success": False, "result_code": "local_unreachable"})

    def test_device_management_is_bounded_and_acknowledged_without_replay(self):
        for action in ("register", "remove"):
            command = {**self.command, "action": action}
            if action == "register":
                command.update(device_name="Sensor", ip_address="")
            self.assertEqual(agent.validate_command(command), command)
            worker = agent.ControlWorker(self.config, MagicMock())
            with patch.object(agent, "endpoint_json", side_effect=[
                {"command": command}, self.result, UploadError("offline"), {"success": True},
            ]) as request:
                with self.assertRaises(UploadError):
                    worker.poll()
                worker.poll()
            self.assertEqual([call.args[1].method for call in request.call_args_list], ["POST", "POST", "PUT", "PUT"])
            self.assertEqual(json.loads(request.call_args_list[1].args[1].data), command)
        for extra in (
            {"device_name": " "}, {"ip_address": "host;reboot"}, {"device_name": "a" * 201},
        ):
            with self.assertRaises(PermanentUploadError):
                agent.validate_command({**self.command, "action": "register", "device_name": "Sensor", "ip_address": "", **extra})


if __name__ == "__main__":
    unittest.main()
