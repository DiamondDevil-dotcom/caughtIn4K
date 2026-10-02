import json
import glob
import os
import random

import numpy as np
import pandas as pd

from sklearn.preprocessing import LabelEncoder
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold

SEED = 42
DATASET_DIR = "CICIOT23"

TRAIN_SAMPLE_FRACTION = float(
    os.getenv("CICIOT_TRAIN_FRACTION", os.getenv("CICIO_TRAIN_FRACTION", "0.03"))
)
VALIDATION_SAMPLE_FRACTION = float(
    os.getenv("CICIOT_VALIDATION_FRACTION", os.getenv("CICIO_VALIDATION_FRACTION", "1.0"))
)
TEST_SAMPLE_FRACTION = float(
    os.getenv("CICIOT_TEST_FRACTION", os.getenv("CICIO_TEST_FRACTION", "1.0"))
)

for fraction_name, fraction in (
    ("CICIOT_TRAIN_FRACTION", TRAIN_SAMPLE_FRACTION),
    ("CICIOT_VALIDATION_FRACTION", VALIDATION_SAMPLE_FRACTION),
    ("CICIOT_TEST_FRACTION", TEST_SAMPLE_FRACTION),
):
    if not 0 < fraction <= 1:
        raise ValueError(f"{fraction_name} must be greater than 0 and at most 1")


class CICIoTDataset:

    def __init__(self):
        random.seed(SEED)
        np.random.seed(SEED)

        with open("selected_features.json") as f:
            self.selected_features = json.load(f)

    def load_files(self, folder, sample_fraction):

        files = glob.glob(os.path.join(DATASET_DIR, folder, "*.csv"))

        if len(files) == 0:
            raise FileNotFoundError(f"No csv found inside {folder}")

        frames = []

        for i, file in enumerate(files):

            print(f"Reading {file}")

            df = pd.read_csv(
                file,
                usecols=self.selected_features + ["label"],
                dtype={feature: np.float32 for feature in self.selected_features},
                skiprows=lambda x: x > 0 and random.random() > sample_fraction,
            )

            frames.append(df)

            print(f"Loaded {len(df)} rows")

        return pd.concat(frames, ignore_index=True)

    def binary_labels(self, frame):

        return np.where(
            frame["label"].astype(str).str.contains(
                "benign",
                case=False,
                na=False,
            ),
            "Benign",
            "Attack",
        )

    def clean_features(self, frame, features, fill_values=None):

        values = frame[features].copy()

        for feature in features:
            values[feature] = pd.to_numeric(
                values[feature],
                errors="coerce",
            )

        values = values.replace(
            [np.inf, -np.inf],
            np.nan,
        )

        if fill_values is None:
            fill_values = values.median()

        values = values.fillna(fill_values)

        return values, fill_values

    def load_client_data(self, client_id, num_clients):

        print("Loading dataset...")

        train = self.load_files("train", TRAIN_SAMPLE_FRACTION)
        validation = self.load_files("validation", VALIDATION_SAMPLE_FRACTION)
        test = self.load_files("test", TEST_SAMPLE_FRACTION)

        features = [
            feature
            for feature in self.selected_features
            if feature in train.columns
        ]

        print(f"Using {len(features)} NGO-selected features")

        encoder = LabelEncoder()

        y_train = encoder.fit_transform(
            self.binary_labels(train)
        )

        y_val = encoder.transform(
            self.binary_labels(validation)
        )

        y_test = encoder.transform(
            self.binary_labels(test)
        )

        x_train_raw, medians = self.clean_features(
            train,
            features,
        )

        x_val_raw, _ = self.clean_features(
            validation,
            features,
            medians,
        )

        x_test_raw, _ = self.clean_features(
            test,
            features,
            medians,
        )

        scaler = StandardScaler()

        x_train = scaler.fit_transform(x_train_raw)
        x_val = scaler.transform(x_val_raw)
        x_test = scaler.transform(x_test_raw)

        skf = StratifiedKFold(
        n_splits=num_clients,
        shuffle=True,
        random_state=42,
        )

        splits = list(skf.split(x_train, y_train))

        _, client_idx = splits[client_id]

        print(
            f"Client {client_id} samples: {len(client_idx)} "
            f"Attack={np.sum(y_train[client_idx]==0)} "
            f"Benign={np.sum(y_train[client_idx]==1)}"
        )

        return (
            x_train[client_idx],
            y_train[client_idx],
            x_val,
            y_val,
            x_test,
            y_test,
            scaler,
            encoder,
            features,
        )