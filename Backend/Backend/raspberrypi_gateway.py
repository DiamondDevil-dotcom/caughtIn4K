#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List
from urllib import error, request

ROOT = Path(__file__).resolve().parent.parent
MODEL_FEATURES_FILE = ROOT / "Ghost_FL_Flower" / "Ghost_FL_Flower" / "selected_features.json"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000/live-predict"
DEFAULT_DEVICE_ID = "rpi-gateway-01"


def load_feature_names() -> List[str]:
    if MODEL_FEATURES_FILE.exists():
        try:
            with MODEL_FEATURES_FILE.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                return [str(item) for item in data]
        except Exception:
            pass
    return [
        "Header_Length",
        "syn_flag_number",
        "rst_flag_number",
        "HTTP",
        "ARP",
        "ICMP",
        "LLC",
        "Tot sum",
        "Min",
        "IAT",
        "Number",
        "Magnitue",
        "Covariance",
        "Weight",
    ]


FEATURE_NAMES = load_feature_names()


def env_key_for_feature(feature_name: str) -> str:
    return feature_name.upper().replace(" ", "_").replace("-", "_").replace(".", "_")


def sensor_value_for(feature_name: str, default: float = 0.0) -> float:
    env_key = env_key_for_feature(feature_name)
    value = os.getenv(env_key)
    if value is None:
        return float(default)
    try:
        return float(value)
    except ValueError:
        return float(default)


def _read_float_from_file(path: str) -> float | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
        if not text:
            return None
        return float(text)
    except OSError:
        return None


def _read_cpu_temperature() -> float:
    candidates = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/devices/platform/soc/soc:firmware/get_throttled",
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        value = _read_float_from_file(path)
        if value is None:
            continue
        if path.endswith("temp"):
            return value / 1000.0
    return 45.0


def _read_load_average() -> float:
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as handle:
            load_str = handle.read().strip().split()[0]
        return float(load_str)
    except OSError:
        return 0.5


def _read_memory_usage_percent() -> float:
    try:
        meminfo = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if ":" in line:
                    key, value = line.split(":", 1)
                    meminfo[key.strip()] = value.strip()
        total = float(meminfo.get("MemTotal", "0 kB").split()[0])
        available = float(meminfo.get("MemAvailable", "0 kB").split()[0])
        used = max(total - available, 0.0)
        return (used / total) * 100.0 if total else 0.0
    except OSError:
        return 45.0


def _read_network_usage() -> Dict[str, float]:
    total_rx = 0.0
    total_tx = 0.0
    total_packets = 0.0
    try:
        with open("/proc/net/dev", "r", encoding="utf-8") as handle:
            lines = handle.readlines()[2:]
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[0].endswith(":") is False:
                continue
            rx_bytes = float(parts[1])
            tx_bytes = float(parts[9])
            packets = float(parts[2]) + float(parts[10])
            total_rx += rx_bytes
            total_tx += tx_bytes
            total_packets += packets
    except OSError:
        return {"rx_bytes": 0.0, "tx_bytes": 0.0, "packets": 0.0}
    return {"rx_bytes": total_rx, "tx_bytes": total_tx, "packets": total_packets}


def _collect_pi_metrics() -> Dict[str, float]:
    cpu_temp = _read_cpu_temperature()
    load = _read_load_average()
    memory_percent = _read_memory_usage_percent()
    traffic = _read_network_usage()
    return {
        "cpu_temp": cpu_temp,
        "load": load,
        "memory_percent": memory_percent,
        "rx_bytes": traffic["rx_bytes"],
        "tx_bytes": traffic["tx_bytes"],
        "packets": traffic["packets"],
    }


def build_payload(device_id: str, feature_overrides: Dict[str, float] | None = None) -> Dict[str, object]:
    metrics = _collect_pi_metrics()
    features: Dict[str, float] = {
        "Header_Length": float(metrics["cpu_temp"] * 10.0 + metrics["memory_percent"]),
        "syn_flag_number": 1.0 if metrics["load"] > 1.0 else 0.0,
        "rst_flag_number": 1.0 if metrics["cpu_temp"] > 65.0 else 0.0,
        "HTTP": 1.0 if metrics["tx_bytes"] > 0.0 else 0.0,
        "ARP": 1.0 if metrics["packets"] > 0.0 else 0.0,
        "ICMP": 1.0 if metrics["load"] > 1.5 else 0.0,
        "LLC": float(min(10.0, max(0.0, metrics["cpu_temp"] / 10.0))),
        "Tot sum": float(metrics["rx_bytes"] + metrics["tx_bytes"]) / 1000.0,
        "Min": float(min(100.0, max(0.0, metrics["memory_percent"] / 2.0))),
        "IAT": float(max(0.1, 10.0 / (1.0 + metrics["packets"] / 100.0))),
        "Number": float(min(100.0, max(0.0, metrics["packets"] / 10.0))),
        "Magnitue": float(min(1.0, max(0.0, (metrics["load"] + metrics["cpu_temp"] / 100.0) / 2.0))),
        "Covariance": float(min(1.0, max(0.0, abs(metrics["load"] - 0.75) / 1.5))),
        "Weight": float(min(1.0, max(0.0, (metrics["memory_percent"] / 100.0 + metrics["cpu_temp"] / 100.0) / 2.0))),
    }

    for name in FEATURE_NAMES:
        if feature_overrides and name in feature_overrides:
            features[name] = float(feature_overrides[name])
        elif name in os.environ:
            features[name] = sensor_value_for(name, default=features.get(name, 0.0))
        elif name not in features:
            features[name] = 0.0

    return {"device_id": device_id, "features": features}


def send_prediction(payload: Dict[str, object], backend_url: str) -> Dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        backend_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def run_loop(interval_seconds: int = 5, max_cycles: int | None = None) -> None:
    backend_url = os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL)
    device_id = os.getenv("DEVICE_ID", DEFAULT_DEVICE_ID)

    print(f"Gateway started for device {device_id}")
    print(f"Sending feature payloads to {backend_url}")

    cycles = 0
    while True:
        try:
            payload = build_payload(device_id)
            result = send_prediction(payload, backend_url)
            print(json.dumps({"device_id": result.get("device_id"), "label": result.get("label"), "confidence": result.get("confidence")}, indent=2))
        except error.HTTPError as exc:
            print(f"HTTP error: {exc.code} {exc.reason}")
            print(exc.read().decode("utf-8", errors="ignore"))
        except Exception as exc:  # pragma: no cover - runtime bridge logging
            print(f"Gateway error: {exc}")

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        time.sleep(interval_seconds)


if __name__ == "__main__":
    max_cycles = int(os.getenv("MAX_RUNS", "0")) or None
    run_loop(interval_seconds=int(os.getenv("SEND_INTERVAL_SECONDS", "5")), max_cycles=max_cycles)
