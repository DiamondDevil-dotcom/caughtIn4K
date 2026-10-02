"""Laptop FedAvg coordinator for the laptop + Raspberry Pi deployment.

Run this on the laptop from this project directory. It waits for the laptop
training client and the Pi training client, aggregates their model updates,
and writes inference-ready checkpoints for both the website and Pi agent.
"""

import json
import os
from pathlib import Path

import flwr as fl
import numpy as np
import torch
from flwr.common import ndarrays_to_parameters, parameters_to_ndarrays

from model import Ghost1D_GRU
from utils import set_weights


PROJECT_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECT_DIR.parent
FLOWER_OUTPUT_DIR = Path(os.getenv("GHOST_FL_OUTPUT_DIR", str(ROOT_DIR / "Ghost_FL_Flower" / "saved_models")))
LOCAL_OUTPUT_DIR = Path(os.getenv("GHOST_FL_LOCAL_OUTPUT_DIR", str(PROJECT_DIR / "saved_models")))
INITIAL_CHECKPOINT = Path(
    os.getenv("GHOST_FL_INITIAL_MODEL", str(PROJECT_DIR / "ghost1d_gru_fedavg_improved.pth"))
)
SERVER_ADDRESS = os.getenv("GHOST_FL_BIND", "0.0.0.0:8080")
ROUNDS = int(os.getenv("GHOST_FL_ROUNDS", "10"))
MIN_CLIENTS = 2
STATUS_FILE = Path(os.getenv("GHOST_FL_STATUS_FILE", str(ROOT_DIR / "Database" / "federated_status.json")))


def write_status(state, server_round=0, phase="waiting_for_clients", error=None):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "state": state, "current_round": server_round, "total_rounds": ROUNDS,
        "phase": phase, "error": error,
    }), encoding="utf-8")
    os.replace(temporary, STATUS_FILE)


def main():
    write_status("running")
    checkpoint = torch.load(INITIAL_CHECKPOINT, map_location="cpu", weights_only=False)
    feature_names = list(checkpoint["feature_names"])
    class_names = list(checkpoint.get("class_names", ["Attack", "Benign"]))
    scaler_mean = np.asarray(checkpoint["scaler_mean"], dtype=np.float32)
    scaler_scale = np.asarray(checkpoint["scaler_scale"], dtype=np.float32)
    scaler_scale = np.where(scaler_scale == 0, 1.0, scaler_scale)
    fill_values = {
        str(name): float(value)
        for name, value in checkpoint.get("train_fill_values", {}).items()
    }
    benign_threshold = float(checkpoint.get("benign_threshold", 0.5))

    if len(feature_names) != len(scaler_mean) or len(feature_names) != len(scaler_scale):
        raise ValueError("Checkpoint feature names and scaler dimensions do not match.")
    if class_names != ["Attack", "Benign"]:
        raise ValueError("Federated client label order must be ['Attack', 'Benign'].")

    # Keep the pretrained detector as the common starting point for both clients.
    model = Ghost1D_GRU(input_dim=len(feature_names), num_classes=2)
    model.load_state_dict(checkpoint["model_state_dict"])
    initial_parameters = ndarrays_to_parameters(
        [value.detach().cpu().numpy() for value in model.state_dict().values()]
    )
    fit_config = {
        "feature_names": json.dumps(feature_names),
        "scaler_mean": json.dumps(scaler_mean.tolist()),
        "scaler_scale": json.dumps(scaler_scale.tolist()),
        "train_fill_values": json.dumps(fill_values),
        "benign_threshold": benign_threshold,
    }

    def round_config(server_round):
        return {
            **fit_config,
            "federated_round": server_round,
            "federated_clients": MIN_CLIENTS,
        }

    class SaveGlobalFedAvg(fl.server.strategy.FedAvg):
        completed_round = 0

        def aggregate_fit(self, server_round, results, failures):
            if failures or len(results) != MIN_CLIENTS:
                raise RuntimeError("A round requires updates from both laptop and Pi.")
            aggregated = super().aggregate_fit(server_round, results, failures)
            if aggregated is None or aggregated[0] is None:
                return aggregated

            global_model = Ghost1D_GRU(input_dim=len(feature_names), num_classes=2)
            set_weights(global_model, parameters_to_ndarrays(aggregated[0]))
            bundle = {
                "model_state_dict": global_model.state_dict(),
                "feature_names": feature_names,
                "class_names": class_names,
                "scaler_mean": scaler_mean,
                "scaler_scale": scaler_scale,
                "train_fill_values": fill_values,
                "benign_threshold": benign_threshold,
                "federated_round": server_round,
                "federated_clients": len(results),
                "aggregation": "FedAvg",
            }
            for output_dir in (LOCAL_OUTPUT_DIR, FLOWER_OUTPUT_DIR):
                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / f"global_model_round_{server_round}.pth"
                temporary = target.with_suffix(".pth.tmp")
                torch.save(bundle, temporary)
                os.replace(temporary, target)
            print(
                f"Round {server_round}: FedAvg combined {len(results)} client updates; "
                f"checkpoint saved for laptop website."
            )
            write_status("running", server_round, "evaluating_global_model")
            return aggregated

        def aggregate_evaluate(self, server_round, results, failures):
            if failures or len(results) != MIN_CLIENTS:
                raise RuntimeError("Both clients must evaluate the global model before a round completes.")
            aggregated = super().aggregate_evaluate(server_round, results, failures)
            if aggregated is None or aggregated[0] is None:
                raise RuntimeError("Global model evaluation did not complete.")
            self.completed_round = server_round
            write_status("running", server_round, "round_completed")
            return aggregated

    strategy = SaveGlobalFedAvg(
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=MIN_CLIENTS,
        min_evaluate_clients=MIN_CLIENTS,
        min_available_clients=MIN_CLIENTS,
        initial_parameters=initial_parameters,
        on_fit_config_fn=round_config,
        on_evaluate_config_fn=round_config,
        accept_failures=False,
    )

    print(f"FedAvg server listening on {SERVER_ADDRESS}; waiting for {MIN_CLIENTS} clients.")
    print(f"Initial model: {INITIAL_CHECKPOINT}")
    fl.server.start_server(
        server_address=SERVER_ADDRESS,
        config=fl.server.ServerConfig(num_rounds=ROUNDS),
        strategy=strategy,
    )
    if strategy.completed_round != ROUNDS:
        raise RuntimeError("Training stopped before all configured rounds completed.")
    write_status("completed", ROUNDS, "completed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        write_status("failed", error=str(error), phase="failed")
        raise
