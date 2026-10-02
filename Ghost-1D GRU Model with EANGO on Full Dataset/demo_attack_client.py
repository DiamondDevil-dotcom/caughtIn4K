"""Demo-only traffic generator for live presentations.

Sends labeled feature rows from the CICIoT23 test set to the router agent's
`/telemetry` endpoint, ramping the proportion of attack rows over time so a
demo device visibly moves SAFE -> WARNING -> ALERT -> BLOCKED in the app.
This does not send real network attack traffic; it only replays pre-recorded
feature vectors, and is intended to be run against your own lab deployment.
"""

import argparse
import csv
import json
import math
import random
import time
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_DIR = Path(__file__).resolve().parent
FEATURES_PATH = PROJECT_DIR / "selected_features.json"
DEFAULT_DATASET = PROJECT_DIR / "CICIOT23" / "test" / "test.csv"


def read_features(row, feature_names):
    values = []
    for name in feature_names:
        try:
            value = float(row.get(name, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        values.append(value if math.isfinite(value) else 0.0)
    return values


def send_event(api_url, device, mac, features):
    payload = json.dumps({
        "device": device,
        "mac": mac,
        "features": features,
    }).encode("utf-8")
    request = Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def load_rows(path):
    benign_rows, attack_rows = [], []
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if str(row.get("label", "")).lower().startswith("benign"):
                benign_rows.append(row)
            else:
                attack_rows.append(row)
    random.shuffle(benign_rows)
    random.shuffle(attack_rows)
    return benign_rows, attack_rows


def main():
    parser = argparse.ArgumentParser(
        description="Ramp a demo device from benign to attack traffic."
    )
    parser.add_argument("--device", default="Demo Device")
    parser.add_argument("--mac", default="02:00:00:00:00:99")
    parser.add_argument("--file", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--api-url", required=True, help="e.g. http://<pi-ip>:8000/telemetry")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--windows", type=int, default=20, help="how many windows to ramp over")
    args = parser.parse_args()

    with FEATURES_PATH.open(encoding="utf-8") as file:
        feature_names = json.load(file)

    benign_rows, attack_rows = load_rows(args.file)

    for step in range(args.windows):
        attack_ratio = min(1.0, step / max(1, args.windows - 1))
        use_attack = random.random() < attack_ratio
        row = (attack_rows if use_attack and attack_rows else benign_rows)[step % len(
            attack_rows if use_attack and attack_rows else benign_rows
        )]
        features = read_features(row, feature_names)
        result = send_event(args.api_url, args.device, args.mac, features)
        print(f"step={step} attack_ratio={attack_ratio:.2f} -> {json.dumps(result)}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
