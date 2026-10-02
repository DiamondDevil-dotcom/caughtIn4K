import json
import copy
import glob
import os
import random

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, recall_score
from sklearn.preprocessing import LabelEncoder, StandardScaler
from torch.utils.data import DataLoader, TensorDataset

from model import Ghost1D_GRU

# Keep this at 0.03 for a direct comparison with the previous run.  Raise it
# to 0.10 after choosing the settings, then to 1.0 if memory permits.
SEED = 42
DATASET_DIR = "CICIOT23"
SAMPLE_FRACTION = 0.03
NUM_CLIENTS = 5
BATCH_SIZE = 128
ROUNDS = 12
LOCAL_EPOCHS = 2
LEARNING_RATE = 0.001
FEDPROX_MU = 0.001

# This deliberately allows a small attack-recall trade-off in exchange for
# fewer false alarms.  Use 0.995 for a more conservative deployment policy.
TARGET_ATTACK_RECALL = 0.99
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_files(files, sample_fraction, seed):
    if not files:
        raise FileNotFoundError("No CSV files found.")

    frames = []
    for index, path in enumerate(files):
        frame = pd.read_csv(path)
        if sample_fraction < 1.0:
            frame = frame.sample(frac=sample_fraction, random_state=seed + index)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def binary_labels(frame):
    return np.where(
        frame["label"].astype(str).str.contains("benign", case=False, na=False),
        "Benign",
        "Attack",
    )


def clean_features(frame, features, fill_values=None):
    values = frame[features].copy()
    for feature in features:
        values[feature] = pd.to_numeric(values[feature], errors="coerce")
    values = values.replace([np.inf, -np.inf], np.nan)
    if fill_values is None:
        fill_values = values.median()
    return values.fillna(fill_values), fill_values


# --- HYBRID FOCAL-FEDPROX LOSS ---
class HybridFocalFedProxLoss(nn.Module):
    def __init__(self, class_weights, gamma=1.5, mu=0.001, label_smoothing=0.05):
        super().__init__()
        self.class_weights = class_weights
        self.gamma = gamma
        self.mu = mu
        self.label_smoothing = label_smoothing

    def forward(self, outputs, targets, local_model, global_model):
        # 1. Focal Loss
        log_probabilities = F.log_softmax(outputs, dim=1)
        probabilities = log_probabilities.exp()
        target_probabilities = probabilities.gather(1, targets.unsqueeze(1)).squeeze(1)
        ce_loss = F.cross_entropy(
            outputs,
            targets,
            reduction='none',
            label_smoothing=self.label_smoothing,
        )
        sample_weights = self.class_weights[targets]
        focal_loss = (sample_weights * (1 - target_probabilities) ** self.gamma * ce_loss).mean()

        # 2. Proximal Term
        proximal_term = 0.0
        for w, w_t in zip(local_model.parameters(), global_model.parameters()):
            proximal_term += torch.square((w - w_t).norm(2))

        return focal_loss + (self.mu / 2.0) * proximal_term


def fedavg(global_model, client_models, client_sizes):
    """Sample-weighted FedAvg; no client updates are discarded."""
    global_state = global_model.state_dict()
    total = sum(client_sizes)
    for key, original in global_state.items():
        states = [model.state_dict()[key] for model in client_models]
        if torch.is_floating_point(original):
            global_state[key] = sum(
                state * (size / total) for state, size in zip(states, client_sizes)
            )
        else:
            global_state[key] = states[0]
    global_model.load_state_dict(global_state)
    return global_model


def probabilities(model, inputs):
    model.eval()
    with torch.no_grad():
        return torch.softmax(model(inputs.to(DEVICE)), dim=1).cpu().numpy()


def select_threshold(y_true, benign_probabilities, attack_id, benign_id, minimum_attack_recall):
    """Tune only on validation data; maximize Benign recall under the policy."""
    best = None
    for threshold in np.arange(0.001, 1.0, 0.001):
        predicted = np.where(benign_probabilities >= threshold, benign_id, attack_id)
        attack_recall = recall_score(y_true, predicted, pos_label=attack_id, zero_division=0)
        benign_recall = recall_score(y_true, predicted, pos_label=benign_id, zero_division=0)
        if attack_recall >= minimum_attack_recall:
            candidate = (benign_recall, threshold, attack_recall)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is None:
        raise RuntimeError("No validation threshold satisfies TARGET_ATTACK_RECALL.")
    return best[1]


def report(name, y_true, predicted, class_names):
    print(f"\n--- {name} ---")
    print(f"Accuracy: {accuracy_score(y_true, predicted) * 100:.2f}%")
    print(classification_report(y_true, predicted, target_names=class_names, zero_division=0))
    print("Confusion matrix [rows=true, columns=predicted]")
    print(confusion_matrix(y_true, predicted))


set_seed(SEED)
print(f"Using device: {DEVICE}")

train = load_files(glob.glob(os.path.join(DATASET_DIR, "train", "*.csv")), SAMPLE_FRACTION, SEED)
validation = load_files(glob.glob(os.path.join(DATASET_DIR, "validation", "*.csv")), SAMPLE_FRACTION, SEED + 1000)
test = load_files(glob.glob(os.path.join(DATASET_DIR, "test", "*.csv")), SAMPLE_FRACTION, SEED + 2000)

excluded = {"label", "macro_label"}

# Load NGO-selected features
with open("selected_features.json", "r") as f:
    selected_features = json.load(f)
print("\nFeatures from NGO:")
print(selected_features)
print(f"Total NGO Features: {len(selected_features)}")

# Keep only features that exist in all datasets
features = [
    column for column in selected_features
    if column in train.columns
    and column in validation.columns
    and column in test.columns
]
missing = [f for f in selected_features if f not in features]

print("\nFeatures missing from train_federated:")
print(missing)
print(f"Total Missing: {len(missing)}")
if not features:
    raise RuntimeError("No common feature columns found.")
print(f"Using {len(features)} numeric flow features.")
print("Selected Features:")
print(features)

encoder = LabelEncoder()
y_train = encoder.fit_transform(binary_labels(train))
y_validation = encoder.transform(binary_labels(validation))
y_test = encoder.transform(binary_labels(test))
attack_id = encoder.transform(["Attack"])[0]
benign_id = encoder.transform(["Benign"])[0]
print("Class order:", list(encoder.classes_))
print("Training distribution:")
print(pd.Series(y_train).map(dict(enumerate(encoder.classes_))).value_counts())

class_counts = np.bincount(y_train, minlength=len(encoder.classes_)).astype(np.float32)
# Square-root inverse frequency improves minority-class learning without the
# instability of full inverse-frequency weighting on this 98/2 split.
class_weights = np.sqrt(class_counts.sum() / np.maximum(class_counts, 1.0))
class_weights /= class_weights.mean()
class_weights = torch.tensor(class_weights, dtype=torch.float32, device=DEVICE)
print("Class weights:", dict(zip(encoder.classes_, class_weights.cpu().tolist())))

x_train_raw, train_medians = clean_features(train, features)
x_validation_raw, _ = clean_features(validation, features, train_medians)
x_test_raw, _ = clean_features(test, features, train_medians)

scaler = StandardScaler()
x_train = scaler.fit_transform(x_train_raw)
x_validation = scaler.transform(x_validation_raw)
x_test = scaler.transform(x_test_raw)

client_indices = np.array_split(np.random.permutation(len(x_train)), NUM_CLIENTS)
client_loaders, client_sizes = [], []
for client_id, indexes in enumerate(client_indices, start=1):
    dataset = TensorDataset(
        torch.tensor(x_train[indexes], dtype=torch.float32),
        torch.tensor(y_train[indexes], dtype=torch.long),
    )
    client_loaders.append(DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True))
    client_sizes.append(len(dataset))
    print(f"Client {client_id}: {len(dataset)} samples")

global_model = Ghost1D_GRU(input_dim=len(features), num_classes=len(encoder.classes_)).to(DEVICE)

# --- INITIALIZE HYBRID LOSS HERE ---
criterion = HybridFocalFedProxLoss(
    class_weights=class_weights,
    gamma=1.5,
    mu=FEDPROX_MU,
    label_smoothing=0.05,
)

for round_number in range(1, ROUNDS + 1):
    client_models = []
    print(f"\n--- Round {round_number}/{ROUNDS} ---")
    for client_id, loader in enumerate(client_loaders, start=1):
        local_model = copy.deepcopy(global_model).to(DEVICE)
        
        # AdamW for better weight decay optimization
        optimizer = torch.optim.AdamW(local_model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
        local_model.train()
        
        for _ in range(LOCAL_EPOCHS):
            for batch_x, batch_y in loader:
                optimizer.zero_grad()
                loss = criterion(
                    local_model(batch_x.to(DEVICE)), batch_y.to(DEVICE), local_model, global_model
                )
                loss.backward()
                torch.nn.utils.clip_grad_norm_(local_model.parameters(), max_norm=5.0)
                optimizer.step()
                
        client_models.append(local_model)
        print(f"Client {client_id} complete")
        
    global_model = fedavg(global_model, client_models, client_sizes)

validation_probabilities = probabilities(global_model, torch.tensor(x_validation, dtype=torch.float32))
benign_threshold = select_threshold(
    y_validation,
    validation_probabilities[:, benign_id],
    attack_id,
    benign_id,
    TARGET_ATTACK_RECALL,
)
validation_predictions = np.where(
    validation_probabilities[:, benign_id] >= benign_threshold, benign_id, attack_id
)
print(f"\nSelected Benign threshold: {benign_threshold:.3f}")
report("Validation evaluation", y_validation, validation_predictions, encoder.classes_)

test_probabilities = probabilities(global_model, torch.tensor(x_test, dtype=torch.float32))
test_predictions = np.where(
    test_probabilities[:, benign_id] >= benign_threshold, benign_id, attack_id
)
report("Unseen test evaluation", y_test, test_predictions, encoder.classes_)

checkpoint = {
    "model_state_dict": global_model.state_dict(),
    "feature_names": features,
    "class_names": encoder.classes_,
    "scaler_mean": scaler.mean_,
    "scaler_scale": scaler.scale_,
    "train_fill_values": train_medians.to_dict(),
    "benign_threshold": benign_threshold,
    "training_class_weights": class_weights.cpu().numpy(),
    "label_smoothing": criterion.label_smoothing,
}
torch.save(checkpoint, "ghost1d_gru_fedavg_improved.pth")
print("\nSaved: ghost1d_gru_fedavg_improved.pth")