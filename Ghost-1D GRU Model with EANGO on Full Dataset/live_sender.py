import argparse
import csv
import json
import math
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_DIR = Path(__file__).resolve().parent
FEATURES_PATH = PROJECT_DIR / "selected_features.json"
DEFAULT_DATASET = PROJECT_DIR / "CICIOT23" / "test" / "test.csv"
DEFAULT_API_URL = os.getenv(
    "GHOST_API_URL",
    "http://192.168.29.141:8000/traffic",
)


def read_features(row, feature_names):
    values = []
    for name in feature_names:
        try:
            value = float(row.get(name, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        values.append(value if math.isfinite(value) else 0.0)
    return values


def send_event(api_url, device_name, features):
    payload = json.dumps({
        "device": device_name,
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


def balanced_rows(rows):
    pending_attack = None
    pending_benign = None
    next_label = "benign"

    for row in rows:
        is_benign = str(row.get("label", "")).lower().startswith("benign")
        if is_benign and pending_benign is None:
            pending_benign = row
        elif not is_benign and pending_attack is None:
            pending_attack = row

        if pending_benign is not None and pending_attack is not None:
            if next_label == "benign":
                yield pending_benign
                pending_benign = None
                next_label = "attack"
            else:
                yield pending_attack
                pending_attack = None
                next_label = "benign"


def main():
    parser = argparse.ArgumentParser(
        description="Send live feature windows to the Ghost global-model API."
    )
    parser.add_argument("--device", default="IoT Device")
    parser.add_argument("--file", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Replay the CSV order instead of alternating benign and attack rows.",
    )
    args = parser.parse_args()

    with FEATURES_PATH.open(encoding="utf-8") as file:
        feature_names = json.load(file)

    with args.file.open(newline="", encoding="utf-8") as file:
        rows = csv.DictReader(file)
        stream = rows if args.sequential else balanced_rows(rows)
        for row in stream:
            result = send_event(
                args.api_url,
                args.device,
                read_features(row, feature_names),
            )
            print(json.dumps(result), flush=True)
            if args.once:
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    main()