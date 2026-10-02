"""Opt-in CPU smoke test with real Flower server and both client roles."""

import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import torch


@unittest.skipUnless(os.getenv("GHOST_TEST_FLOWER") == "1", "Set GHOST_TEST_FLOWER=1 for the real Flower round.")
class FlowerRoundTest(unittest.TestCase):
    def test_both_clients_train_and_pi_receives_checkpoint(self):
        project = Path(__file__).resolve().parents[2] / "Ghost-1D GRU Model with EANGO on Full Dataset"
        initial = torch.load(project / "ghost1d_gru_fedavg_improved.pth", map_location="cpu", weights_only=False)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path = root / "samples.csv"
            with csv_path.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow([*initial["feature_names"], "label"])
                for index in range(8):
                    values = [float(mean) + (index - 4) * float(scale) * 0.01
                              for mean, scale in zip(initial["scaler_mean"], initial["scaler_scale"])]
                    writer.writerow([*values, "Benign" if index % 2 else "Attack"])
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            address = f"127.0.0.1:{port}"
            env = dict(os.environ, GHOST_FL_BIND=address, GHOST_FL_ROUNDS="1",
                       GHOST_FL_LOCAL_EPOCHS="1", GHOST_FL_LAPTOP_TRAIN_CSV=str(csv_path),
                       GHOST_FL_LAPTOP_SAMPLE_FRACTION="1", GHOST_FL_SAMPLES=str(csv_path),
                       GHOST_FL_PI_MODEL=str(root / "pi.pth"),
                       GHOST_FL_STATUS_FILE=str(root / "status.json"),
                       GHOST_FL_OUTPUT_DIR=str(root / "flower"),
                       GHOST_FL_LOCAL_OUTPUT_DIR=str(root / "local"),
                       CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1")
            processes = []
            logs = []
            try:
                for script, arguments in (
                    ("federated_server.py", []),
                    ("federated_client.py", ["--role", "laptop", "--server-address", address]),
                    ("federated_client.py", ["--role", "pi", "--server-address", address]),
                ):
                    log = (root / f"process-{len(processes)}.log").open("w", encoding="utf-8")
                    logs.append(log)
                    process = subprocess.Popen(
                        [sys.executable, "-u", str(project / script), *arguments],
                        cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT,
                    )
                    processes.append(process)
                    if len(processes) == 1:
                        deadline = time.monotonic() + 60
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                raise RuntimeError("Server exited during startup.")
                            try:
                                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                                    break
                            except OSError:
                                time.sleep(0.2)
                        else:
                            raise TimeoutError("Server startup timed out.")
                for process in processes:
                    self.assertEqual(process.wait(timeout=120), 0)
                status = json.loads((root / "status.json").read_text())
                self.assertEqual(status["state"], "completed")
                self.assertEqual(status["current_round"], 1)
                pi = torch.load(root / "pi.pth", map_location="cpu", weights_only=False)
                self.assertEqual(pi["federated_round"], 1)
                self.assertEqual(pi["federated_clients"], 2)
                self.assertEqual(pi["aggregation"], "FedAvg")
                self.assertTrue((root / "flower" / "global_model_round_1.pth").is_file())
                self.assertTrue(any(
                    not torch.equal(initial["model_state_dict"][key], pi["model_state_dict"][key])
                    for key in initial["model_state_dict"]
                ), "Training must change model weights.")
            except Exception:
                for log in logs:
                    log.flush()
                for path in root.glob("process-*.log"):
                    print(path.name, path.read_text(encoding="utf-8"))
                raise
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
                for log in logs:
                    log.close()


if __name__ == "__main__":
    unittest.main()
