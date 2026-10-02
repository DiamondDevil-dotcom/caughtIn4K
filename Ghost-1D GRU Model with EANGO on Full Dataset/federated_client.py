"""Flower client run as either the laptop's local trainer or the Pi trainer."""

import argparse
import csv
import json
import os
import time
from pathlib import Path

import flwr as fl
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from model import Ghost1D_GRU
from trainer import train_local
from utils import get_weights, set_weights


PROJECT_DIR = Path(__file__).resolve().parent
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
BATCH_SIZE = 128
LOCAL_EPOCHS = int(os.getenv("GHOST_FL_LOCAL_EPOCHS", "1"))
LEARNING_RATE = float(os.getenv("GHOST_FL_LEARNING_RATE", "0.0005"))
_LAPTOP_DATA_CACHE = None


def load_laptop_rows(feature_names, scaler_mean, scaler_scale, fill_values):
    global _LAPTOP_DATA_CACHE
    if _LAPTOP_DATA_CACHE is not None:
        return _LAPTOP_DATA_CACHE
    train_path = Path(os.getenv("GHOST_FL_LAPTOP_TRAIN_CSV", PROJECT_DIR / "CICIOT23" / "train" / "train.csv"))
    feature_set = set(feature_names) | {"label"}
    fraction = float(os.getenv("GHOST_FL_LAPTOP_SAMPLE_FRACTION", "0.003"))
    sampled_chunks = []
    for chunk_number, chunk in enumerate(
        pd.read_csv(train_path, usecols=lambda column: column in feature_set, chunksize=100_000)
    ):
        sampled = chunk.sample(frac=fraction, random_state=42 + chunk_number)
        if not sampled.empty:
            sampled_chunks.append(sampled)
    if not sampled_chunks:
        raise ValueError("Laptop training CSV sampling returned no rows.")
    frame = pd.concat(sampled_chunks, ignore_index=True)
    missing = [name for name in feature_names if name not in frame.columns]
    if missing:
        raise ValueError(f"Laptop training CSV is missing required features: {missing}")
    x = frame[feature_names].apply(pd.to_numeric, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(pd.Series(fill_values).reindex(feature_names))
    x = (x.to_numpy(dtype=np.float32) - scaler_mean) / scaler_scale
    labels = frame["label"].astype(str).str.contains("benign", case=False, na=False).to_numpy()
    y = np.where(labels, 1, 0).astype(np.int64)
    _LAPTOP_DATA_CACHE = (x, y)
    return _LAPTOP_DATA_CACHE


def load_pi_rows(feature_names, scaler_mean, scaler_scale, fill_values):
    samples_path = Path(os.getenv("GHOST_FL_SAMPLES", PROJECT_DIR.parent / "Database" / "federated_samples.csv"))
    if not samples_path.exists():
        raise ValueError(f"No Pi training samples yet: {samples_path}")
    frame = pd.read_csv(samples_path)
    if frame.empty or "label" not in frame.columns:
        raise ValueError("Pi local training file has no labeled rows yet.")
    missing = [name for name in feature_names if name not in frame.columns]
    if missing:
        raise ValueError(f"Pi training file is missing required features: {missing}")
    x = frame[feature_names].apply(pd.to_numeric, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(pd.Series(fill_values).reindex(feature_names))
    x = (x.to_numpy(dtype=np.float32) - scaler_mean) / scaler_scale
    y = frame["label"].astype(str).str.lower().map({"attack": 0, "benign": 1}).to_numpy()
    valid = np.isfinite(y)
    x, y = x[valid], y[valid].astype(np.int64)
    if len(y) < 2 or len(np.unique(y)) < 2:
        raise ValueError("Pi needs labeled Attack and Benign samples before it can train.")
    return x, y


class LocalFlowerClient(fl.client.NumPyClient):
    def __init__(self, role):
        self.role = role
        self.model = None
        self.criterion = nn.CrossEntropyLoss()
        self.feature_names = None
        self.scaler_mean = None
        self.scaler_scale = None
        self.fill_values = {}
        self.trainloader = None
        self.x = None
        self.y = None
        self.benign_threshold = 0.5

    def _configure(self, config):
        self.feature_names = json.loads(config["feature_names"])
        self.scaler_mean = np.asarray(json.loads(config["scaler_mean"]), dtype=np.float32)
        self.scaler_scale = np.asarray(json.loads(config["scaler_scale"]), dtype=np.float32)
        self.fill_values = json.loads(config.get("train_fill_values", "{}"))
        self.benign_threshold = float(config.get("benign_threshold", 0.5))
        if self.role == "laptop":
            self.x, self.y = load_laptop_rows(
                self.feature_names, self.scaler_mean, self.scaler_scale, self.fill_values
            )
        else:
            self.x, self.y = load_pi_rows(
                self.feature_names, self.scaler_mean, self.scaler_scale, self.fill_values
            )
        self.trainloader = DataLoader(
            TensorDataset(torch.from_numpy(self.x), torch.from_numpy(self.y)),
            batch_size=BATCH_SIZE,
            shuffle=True,
        )
        if self.model is None:
            self.model = Ghost1D_GRU(input_dim=len(self.feature_names), num_classes=2).to(DEVICE)

    def get_parameters(self, config):
        return get_weights(self.model)

    def fit(self, parameters, config):
        self._configure(config)
        set_weights(self.model, parameters)
        self.model = train_local(
            self.model,
            self.trainloader,
            epochs=LOCAL_EPOCHS,
            lr=LEARNING_RATE,
            class_weights=self._class_weights(),
        )
        print(f"{self.role} client trained locally on {len(self.y)} rows.")
        return get_weights(self.model), len(self.y), {"role": self.role}

    def _class_weights(self):
        counts = np.bincount(self.y, minlength=2).astype(np.float32)
        weights = np.sqrt(max(float(counts.sum()), 1.0) / np.maximum(counts, 1.0))
        weights /= max(float(weights.mean()), 1e-12)
        return torch.tensor(weights, dtype=torch.float32, device=DEVICE)

    def evaluate(self, parameters, config):
        self._configure(config)
        set_weights(self.model, parameters)
        self.model.eval()
        total_loss = 0.0
        with torch.no_grad():
            for x_batch, y_batch in self.trainloader:
                logits = self.model(x_batch.to(DEVICE))
                loss = self.criterion(logits, y_batch.to(DEVICE))
                total_loss += float(loss.item()) * len(y_batch)

        if self.role == "pi":
            self._save_global_model(config)
        return total_loss / max(1, len(self.y)), len(self.y), {"role": self.role}

    def _save_global_model(self, config):
        target = Path(os.getenv("GHOST_FL_PI_MODEL", str(PROJECT_DIR / "ghost1d_gru_fedavg_improved.pth")))
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "model_state_dict": self.model.cpu().state_dict(),
            "feature_names": self.feature_names,
            "class_names": ["Attack", "Benign"],
            "scaler_mean": self.scaler_mean,
            "scaler_scale": self.scaler_scale,
            "train_fill_values": self.fill_values,
            "benign_threshold": self.benign_threshold,
            "updated_at": time.time(),
            "federated_round": int(config.get("federated_round", 0)),
            "federated_clients": int(config.get("federated_clients", 0)),
            "aggregation": "FedAvg",
        }
        temporary = target.with_suffix(target.suffix + ".tmp")
        torch.save(bundle, temporary)
        os.replace(temporary, target)
        self.model.to(DEVICE)
        print(f"Pi received and saved the new global model: {target}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("laptop", "pi"), required=True)
    parser.add_argument(
        "--server-address",
        default=os.getenv("GHOST_FL_SERVER_ADDRESS", "127.0.0.1:8080"),
    )
    args = parser.parse_args()
    print(f"Connecting {args.role} client to laptop FedAvg server at {args.server_address}")
    fl.client.start_numpy_client(
        server_address=args.server_address,
        client=LocalFlowerClient(args.role),
    )


if __name__ == "__main__":
    main()
