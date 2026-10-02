import ast
import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException

from federated_coordinator import FederatedCoordinator


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controller = FederatedCoordinator(self.root, "http://192.168.50.1:8001", self.root / "training.log")

    def test_missing_scripts_fail_before_scheduling(self):
        with self.assertRaises(FileNotFoundError):
            self.controller.start()
        self.assertEqual(self.controller.status()["state"], "idle")

    def test_duplicate_start_is_rejected(self):
        self.controller.state["state"] = "running"
        with self.assertRaises(RuntimeError):
            self.controller.start()

    def test_new_run_waits_for_previous_cleanup(self):
        self.controller.state["state"] = "completed"
        self.controller._active = True
        with self.assertRaises(RuntimeError):
            self.controller.start()

    def test_status_reads_actual_round_progress(self):
        self.controller.state["state"] = "running"
        self.controller.status_path.write_text(json.dumps({"current_round": 2, "phase": "round_completed"}))
        self.assertEqual(self.controller.status()["current_round"], 2)

    def test_start_schedules_controller_without_running_simulation(self):
        for name in ("federated_server.py", "federated_client.py"):
            (self.root / name).touch()
        with patch("federated_coordinator.threading.Thread") as thread:
            self.assertTrue(self.controller.start()["success"])
        thread.return_value.start.assert_called_once()
        self.assertEqual(self.controller.status()["state"], "running")
        self.assertTrue(self.controller._active)

    def test_pi_rejection_fails_training_and_cleans_processes(self):
        server = Mock()
        server.poll.return_value = None
        laptop = Mock()
        laptop.poll.return_value = None
        response = httpx.Response(400, json={"detail": "Need benign and attack samples"},
                                  request=httpx.Request("POST", "http://pi/federated/start-client"))
        with patch.object(self.controller, "_server_address", return_value="192.168.50.10:8080"), \
             patch.object(self.controller, "_wait_for_server"), \
             patch("federated_coordinator.socket.socket"), \
             patch("federated_coordinator.subprocess.Popen", side_effect=[server, laptop]), \
             patch("federated_coordinator.httpx.post", return_value=response):
            self.controller._run()
        self.assertEqual(self.controller.status()["state"], "failed")
        server.terminate.assert_called_once()
        laptop.terminate.assert_called_once()

    def test_zero_server_exit_without_completed_rounds_fails(self):
        server = Mock(returncode=0)
        server.poll.return_value = 0
        laptop = Mock()
        laptop.poll.return_value = 0
        response = Mock()
        response.json.return_value = {"success": True}
        self.controller.status_path.write_text('{"state": "running", "current_round": 0}')
        with patch.object(self.controller, "_server_address", return_value="192.168.50.10:8080"), \
             patch.object(self.controller, "_wait_for_server"), \
             patch("federated_coordinator.socket.socket"), \
             patch("federated_coordinator.subprocess.Popen", side_effect=[server, laptop]), \
             patch("federated_coordinator.httpx.post", return_value=response):
            self.controller._run()
        self.assertEqual(self.controller.status()["state"], "failed")

    def test_pi_discovery_never_falls_back_to_render(self):
        path = Path(__file__).resolve().parents[2] / "Ghost-1D GRU Model with EANGO on Full Dataset" / "router_ids_agent.py"
        module = ast.parse(path.read_text(encoding="utf-8"))
        node = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "laptop_control_url")
        namespace = {
            "os": os, "EXCLUDED_DEVICE_MACS": set(), "HTTPException": HTTPException,
            "network_neighbors": lambda interface: [],
            "network_control": Mock(HOSTAPD_INTERFACE="wlan0"),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        with patch.dict(os.environ, {"GHOST_LAPTOP_API_URL": ""}):
            with self.assertRaises(HTTPException) as error:
                namespace["laptop_control_url"]("/federated/train")
        self.assertEqual(error.exception.status_code, 503)

    def test_explicit_laptop_url_skips_discovery(self):
        path = Path(__file__).resolve().parents[2] / "Ghost-1D GRU Model with EANGO on Full Dataset" / "router_ids_agent.py"
        node = next(node for node in ast.parse(path.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "laptop_control_url")
        namespace = {"os": os}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        with patch.dict(os.environ, {"GHOST_LAPTOP_API_URL": "http://192.168.50.10:8000/"}):
            self.assertEqual(namespace["laptop_control_url"]("/federated/train"),
                             "http://192.168.50.10:8000/federated/train")

    def test_pi_concurrent_requests_launch_only_one_client(self):
        path = Path(__file__).resolve().parents[2] / "Ghost-1D GRU Model with EANGO on Full Dataset" / "router_ids_agent.py"
        names = {"start_pi_federated_client", "_start_pi_federated_client"}
        nodes = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
        for node in nodes:
            node.decorator_list = []
        samples = self.root / "samples.csv"
        samples.write_text("label\nattack\nbenign\n", encoding="utf-8")
        namespace = {
            "Path": Path, "csv": csv, "subprocess": subprocess, "sys": sys,
            "__file__": str(path), "HTTPException": HTTPException,
            "FederatedStartClientPayload": object,
            "FEDERATED_SAMPLES_PATH": samples,
            "_federated_client_log": self.root / "pi-client.log",
            "_federated_client_process": None,
            "_federated_client_lock": threading.Lock(),
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        process = Mock(pid=123)
        process.poll.return_value = None

        def start():
            try:
                return namespace["start_pi_federated_client"](Mock(server_address="laptop:8080"))["success"]
            except HTTPException as error:
                return error.status_code

        with patch("subprocess.Popen", return_value=process) as launch, ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: start(), range(2)))
        self.assertCountEqual(results, [True, 409])
        launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
