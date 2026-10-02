import numpy as np
import torch

ATTACK_CLASS_INDEX = 0
ATTACK_THRESHOLD = 0.95


def get_weights(model):
    return [
        val.cpu().numpy()
        for _, val in model.state_dict().items()
    ]


def set_weights(model, weights):
    params_dict = zip(
        model.state_dict().keys(),
        weights,
    )

    state_dict = {
        k: torch.tensor(v)
        for k, v in params_dict
    }

    model.load_state_dict(
        state_dict,
        strict=True,
    )


def predict_with_attack_threshold(logits, threshold=ATTACK_THRESHOLD):
    probabilities = torch.softmax(logits, dim=1)
    attack_probability = probabilities[:, ATTACK_CLASS_INDEX]
    return torch.where(
        attack_probability >= threshold,
        torch.tensor(ATTACK_CLASS_INDEX, device=logits.device),
        torch.tensor(1, device=logits.device),
    )