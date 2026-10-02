import copy
import torch
import torch.nn as nn
import torch.nn.functional as F

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

FEDPROX_MU = 0.001


class HybridFocalFedProxLoss(nn.Module):
    def __init__(
        self,
        alpha=0.80,
        gamma=2.0,
        mu=FEDPROX_MU,
        class_weights=None,
    ):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.mu = mu
        self.class_weights = class_weights

    def forward(self, outputs, targets, local_model, global_model):
        ce_loss = F.cross_entropy(outputs, targets, weight=self.class_weights, reduction="none")

        pt = torch.exp(-ce_loss)

        focal_loss = (
            self.alpha *
            (1 - pt) ** self.gamma *
            ce_loss
        ).mean()

        proximal_term = 0.0

        for w, wt in zip(local_model.parameters(), global_model.parameters()):
            proximal_term += torch.norm(w - wt, p=2) ** 2

        return focal_loss + (self.mu / 2.0) * proximal_term


def train_local(
    model,
    trainloader,
    epochs=4,
    lr=0.001,
    class_weights=None,
):
    global_model = copy.deepcopy(model)

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=lr,
        weight_decay=1e-4,
    )

    criterion = HybridFocalFedProxLoss(class_weights=class_weights)

    model.train()

    for epoch in range(epochs):

        running_loss = 0.0

        for x, y in trainloader:

            x = x.to(DEVICE)
            y = y.to(DEVICE)

            optimizer.zero_grad()

            outputs = model(x)

            loss = criterion(
                outputs,
                y,
                model,
                global_model,
            )

            loss.backward()

            torch.nn.utils.clip_grad_norm_(
                model.parameters(),
                5.0,
            )

            optimizer.step()

            running_loss += loss.item()

        print(
            f"Epoch {epoch+1} Loss = {running_loss/len(trainloader):.4f}"
        )

    return model