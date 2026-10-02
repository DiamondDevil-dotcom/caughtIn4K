import sys
import torch
import torch.nn as nn
import flwr as fl

from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import confusion_matrix, precision_score, recall_score, f1_score

from model import Ghost1D_GRU
from dataset import CICIoTDataset
from trainer import train_local
from utils import get_weights, predict_with_attack_threshold, set_weights

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

BATCH_SIZE = 128
LOCAL_EPOCHS = 2
LEARNING_RATE = 0.001


class FlowerClient(fl.client.NumPyClient):

    def __init__(self, client_id):

        self.client_id = client_id

        dataset = CICIoTDataset()

        (
            x_train,
            y_train,
            x_val,
            y_val,
            _,
            _,
            _,
            _,
            features,
        ) = dataset.load_client_data(
            client_id=client_id,
            num_clients=5,
        )

        self.trainloader = DataLoader(
            TensorDataset(
                torch.tensor(x_train, dtype=torch.float32),
                torch.tensor(y_train, dtype=torch.long),
            ),
            batch_size=BATCH_SIZE,
            shuffle=True,
        )

        self.valloader = DataLoader(
            TensorDataset(
                torch.tensor(x_val, dtype=torch.float32),
                torch.tensor(y_val, dtype=torch.long),
            ),
            batch_size=BATCH_SIZE,
            shuffle=False,
        )

        self.model = Ghost1D_GRU(
            input_dim=len(features),
            num_classes=2,
        ).to(DEVICE)


    def get_parameters(self, config):
        return get_weights(self.model)

    def fit(self, parameters, config):

        set_weights(self.model, parameters)

        labels = []
        for _, y in self.trainloader:
            labels.extend(y.numpy())

        labels = torch.tensor(labels)

        class_counts = torch.bincount(labels)

        class_weights = (
            class_counts.sum().float()
            / (2.0 * class_counts.float())
        ).to(DEVICE)

        self.model = train_local(
            self.model,
            self.trainloader,
            epochs=LOCAL_EPOCHS,
            lr=LEARNING_RATE,
            class_weights=class_weights,
        )

        return (
            get_weights(self.model),
            len(self.trainloader.dataset),
            {},
        )

    def evaluate(self, parameters, config):

        set_weights(self.model, parameters)

        self.model.eval()

        total_loss = 0
        correct = 0
        total = 0

        all_preds = []
        all_labels = []

        with torch.no_grad():

            for x, y in self.valloader:

                x = x.to(DEVICE)
                y = y.to(DEVICE)

                outputs = self.model(x)

                loss = torch.nn.functional.cross_entropy(outputs, y)

                total_loss += loss.item() * x.size(0)

                pred = predict_with_attack_threshold(outputs)

                correct += (pred == y).sum().item()

                total += y.size(0)

                all_preds.extend(pred.cpu().numpy())
                all_labels.extend(y.cpu().numpy())

        accuracy = correct / total

        precision = precision_score(
            all_labels,
            all_preds,
            average="macro",
            zero_division=0,
        )

        recall = recall_score(
            all_labels,
            all_preds,
            average="macro",
            zero_division=0,
        )

        f1 = f1_score(
            all_labels,
            all_preds,
            average="macro",
            zero_division=0,
        )

        attack_tp, attack_fn, attack_fp, attack_tn = confusion_matrix(
            all_labels,
            all_preds,
            labels=[0, 1],
        ).ravel()

        print(
            f"Client {self.client_id} | "
            f"Accuracy={accuracy*100:.2f}% "
            f"F1={f1:.4f}"
        )

        return (
            total_loss / total,
            total,
            {
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "attack_tn": int(attack_tn),
                "attack_fp": int(attack_fp),
                "attack_fn": int(attack_fn),
                "attack_tp": int(attack_tp),
            },
        )


if __name__ == "__main__":

    client_id = int(sys.argv[1])

    fl.client.start_numpy_client(
        server_address="10.163.11.102:8080",
        client=FlowerClient(client_id),
    )