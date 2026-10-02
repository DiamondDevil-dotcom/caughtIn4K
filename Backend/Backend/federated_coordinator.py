"""Manage the real laptop Flower processes, never simulated participants."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx


class FederatedCoordinator:
    def __init__(self, project_dir, router_url, log_path):
        self.project_dir = Path(project_dir)
        self.router_url = router_url
        self.log_path = Path(log_path)
        self.status_path = self.log_path.with_name("federated_status.json")
        self.lock = threading.Lock()
        self._active = False
        self.state = {
            "state": "idle",
            "current_round": 0,
            "total_rounds": int(os.getenv("GHOST_FL_ROUNDS", "10")),
            "laptop_client_running": False,
            "started_at": None,
            "error": None,
        }

    def status(self):
        with self.lock:
            result = dict(self.state)
            if result["state"] == "running" and self.status_path.exists():
                progress = json.loads(self.status_path.read_text(encoding="utf-8"))
                result["current_round"] = progress.get("current_round", 0)
                result["phase"] = progress.get("phase", "waiting_for_clients")
            return result

    def start(self):
        with self.lock:
            if self._active or self.state["state"] == "running":
                raise RuntimeError("Federated training is already running.")
            for name in ("federated_server.py", "federated_client.py"):
                if not (self.project_dir / name).is_file():
                    raise FileNotFoundError(f"Laptop training script not found: {name}")
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status_path.unlink(missing_ok=True)
            self.state.update(
                state="running", current_round=0, started_at=time.time(),
                laptop_client_running=False, error=None,
            )
            self._active = True
            threading.Thread(target=self._run, daemon=True).start()
        return {"success": True, "message": "Starting real laptop + Pi Flower training."}

    def _server_address(self):
        configured = os.getenv("GHOST_FL_ADVERTISE_ADDRESS", "").strip()
        if configured:
            return configured
        host = httpx.URL(self.router_url).host
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect((host, 80))
            return f"{route.getsockname()[0]}:8080"

    def _wait_for_server(self, process, port):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Flower server exited during startup; check the training log.")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.25)
        raise TimeoutError("Flower server did not open its port within 60 seconds.")

    def _run(self):
        processes = []
        pi_started = False
        try:
            address = self._server_address()
            port = int(address.rsplit(":", 1)[1])
            # A pre-existing server would make this run's progress ambiguous.
            with socket.socket() as probe:
                probe.bind(("0.0.0.0", port))
            env = dict(os.environ, GHOST_FL_BIND=f"0.0.0.0:{port}",
                       GHOST_FL_STATUS_FILE=str(self.status_path))
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as log:
                server = subprocess.Popen(
                    [sys.executable, "-u", str(self.project_dir / "federated_server.py")],
                    cwd=self.project_dir, env=env, stdout=log, stderr=subprocess.STDOUT,
                )
                processes.append(server)
                self._wait_for_server(server, port)
                laptop = subprocess.Popen(
                    [sys.executable, "-u", str(self.project_dir / "federated_client.py"),
                     "--role", "laptop", "--server-address", f"127.0.0.1:{port}"],
                    cwd=self.project_dir, env=env, stdout=log, stderr=subprocess.STDOUT,
                )
                processes.append(laptop)
                with self.lock:
                    self.state["laptop_client_running"] = True
                response = httpx.post(
                    f"{self.router_url}/federated/start-client",
                    json={"server_address": address}, timeout=15,
                    headers={"ngrok-skip-browser-warning": "true",
                             "X-Gateway-Token": os.getenv("GHOST_ROUTER_TOKEN", "")},
                )
                response.raise_for_status()
                pi_started = True
                if response.json().get("success") is not True:
                    raise RuntimeError("Pi did not accept the training-client request.")
                deadline = time.monotonic() + float(os.getenv("GHOST_FL_TIMEOUT_SECONDS", "1800"))
                while server.poll() is None:
                    if laptop.poll() not in (None, 0):
                        raise RuntimeError("Laptop training client failed; check the training log.")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Training timed out waiting for both clients and aggregation.")
                    time.sleep(0.5)
                if server.returncode != 0:
                    raise RuntimeError("Flower server failed; check the training log.")
                progress = json.loads(self.status_path.read_text(encoding="utf-8"))
                if progress.get("state") != "completed":
                    raise RuntimeError("Flower exited without completing all fit and evaluation rounds.")
                with self.lock:
                    self.state.update(state="completed", current_round=progress["current_round"])
        except (OSError, ValueError, RuntimeError, TimeoutError, httpx.HTTPError) as error:
            print(f"[FEDERATED COORDINATOR ERROR] {error}")
            with self.lock:
                self.state.update(state="failed", error=str(error))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            if pi_started:
                try:
                    response = httpx.post(
                        f"{self.router_url}/federated/stop-client", timeout=15,
                        headers={"ngrok-skip-browser-warning": "true",
                                 "X-Gateway-Token": os.getenv("GHOST_ROUTER_TOKEN", "")},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as error:
                    print(f"[PI CLIENT CLEANUP ERROR] {error}")
                    with self.lock:
                        previous_error = self.state["error"]
                        cleanup_error = f"Pi client cleanup failed: {error}"
                        self.state.update(
                            state="failed",
                            error=f"{previous_error}; {cleanup_error}" if previous_error else cleanup_error,
                        )
            with self.lock:
                self.state["laptop_client_running"] = False
                self._active = False
