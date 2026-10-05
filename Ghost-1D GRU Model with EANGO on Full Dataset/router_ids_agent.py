"""Runs on the Raspberry Pi acting as the Wi-Fi access point.

Captures traffic per connected device (grouped by source MAC), extracts the
same 14 features used in training, runs the federated global model locally,
tracks a rising-confidence early-warning trend, and blocks a device's MAC
once an attack is confirmed across consecutive windows.

Requires the Pi to already be configured as the AP (hostapd + dnsmasq, see
router_setup/). Run with: sudo python3 router_ids_agent.py --iface wlan0
"""

import argparse
import csv
import json
import math
import os
import secrets
import smtplib
import ssl
import subprocess
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Literal
from uuid import UUID
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from scapy.all import ARP, Ether, ICMP, TCP, Raw, sniff

import network_control
import storage
import wifi_client
from model import Ghost1D_GRU


def load_email_environment():
    config_path = Path(__file__).resolve().parent.parent / "Database" / "email.env"
    if not config_path.exists():
        return
    for line in config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_email_environment()

ATTACK_CLASS_INDEX = 0

WINDOW_SECONDS = 5.0
MIN_PACKETS_PER_WINDOW = 4
HISTORY_LENGTH = 6
WARNING_MIN_PROBABILITY = 0.40
WARNING_RISING_STEPS = 3
CONFIRM_WINDOWS_BEFORE_BLOCK = 2
DEVICE_TIMEOUT_SECONDS = 60.0

FEATURE_NAMES = [
    "Header_Length", "syn_flag_number", "rst_flag_number", "HTTP", "ARP",
    "ICMP", "LLC", "Tot sum", "Min", "IAT", "Number", "Magnitue",
    "Covariance", "Weight",
]
EXCLUDED_DEVICE_MACS = {
    mac.strip().lower()
    for mac in os.getenv("GHOST_ROUTER_EXCLUDED_MACS", "").split(",")
    if mac.strip()
}


def is_excluded_device(mac):
    return str(mac).strip().lower() in EXCLUDED_DEVICE_MACS


def laptop_control_url(path):
    explicit_url = os.getenv("GHOST_LAPTOP_API_URL", "").strip().rstrip("/")
    if explicit_url:
        return f"{explicit_url}{path}"
    candidate_ips = [
        ip
        for mac in EXCLUDED_DEVICE_MACS
        if (ip := resolve_ip_from_neighbor_table(mac)) is not None
    ]
    candidate_ips.extend(
        neighbor["ip_address"]
        for neighbor in network_neighbors(network_control.HOSTAPD_INTERFACE)
        if neighbor["ip_address"] not in candidate_ips
    )
    for laptop_ip in candidate_ips:
        base_url = f"http://{laptop_ip}:8000"
        try:
            with urllib.request.urlopen(
                urllib.request.Request(f"{base_url}/federated-training/status",
                                       headers={
                                           "X-Gateway-Token": os.getenv("GHOST_ROUTER_TOKEN", ""),
                                           **({"X-Gateway-User": _gateway_user_email.get()} if _gateway_user_email.get() else {}),
                                       }),
                timeout=0.8
            ) as response:
                if response.status == 200:
                    return f"{base_url}{path}"
        except (OSError, urllib.error.URLError):
            continue

    raise HTTPException(
        status_code=503,
        detail="Laptop coordinator is not reachable. Set GHOST_LAPTOP_API_URL to the laptop's LAN URL; no cloud fallback is used.",
    )

_gateway_user_email: ContextVar[str] = ContextVar("gateway_user_email", default="")


def laptop_request(path):
    request = urllib.request.Request(
        laptop_control_url(path),
        headers={
            "X-Gateway-Token": os.getenv("GHOST_ROUTER_TOKEN", ""),
            **({"X-Gateway-User": _gateway_user_email.get()} if _gateway_user_email.get() else {}),
        },
    )
    return request


DEFAULT_MODEL_PATH = "ghost1d_gru_fedavg_improved.pth"
DEFAULT_MODEL_PATH = Path(
    os.getenv("GHOST_FL_PI_MODEL", str(Path(__file__).resolve().parent / DEFAULT_MODEL_PATH))
)
FEDERATED_SAMPLES_PATH = Path(
    os.getenv("GHOST_FL_SAMPLES", str(storage.DATA_DIR / "federated_samples.csv"))
)
_federated_samples_lock = threading.Lock()
_model_reload_lock = threading.Lock()
_federated_client_process = None
_federated_client_lock = threading.Lock()
_federated_client_log = storage.DATA_DIR / "federated_client.log"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def features_from_packets(packets):
    lengths = [len(packet) for packet in packets]
    intervals = [max(0.0, float(b.time - a.time)) for a, b in zip(packets, packets[1:])]
    tcp_packets = [packet for packet in packets if packet.haslayer(TCP)]
    total_bytes = sum(lengths)
    duration = max(1.0, float(packets[-1].time - packets[0].time))
    values = {
        "Header_Length": float(sum(len(packet.getlayer(Ether).fields) if packet.haslayer(Ether) else 0 for packet in packets)),
        "syn_flag_number": float(sum(bool(packet[TCP].flags & 0x02) for packet in tcp_packets)),
        "rst_flag_number": float(sum(bool(packet[TCP].flags & 0x04) for packet in tcp_packets)),
        "HTTP": float(sum(packet.haslayer(TCP) and (packet[TCP].sport in (80, 8080) or packet[TCP].dport in (80, 8080) or (packet.haslayer(Raw) and bytes(packet[Raw].load).startswith((b"GET ", b"POST ", b"HTTP/")))) for packet in packets)),
        "ARP": float(sum(packet.haslayer(ARP) for packet in packets)),
        "ICMP": float(sum(packet.haslayer(ICMP) for packet in packets)),
        "LLC": float(sum(packet.haslayer(Ether) and packet[Ether].type <= 1500 for packet in packets)),
        "Tot sum": float(total_bytes),
        "Min": float(min(lengths)),
        "IAT": float(statistics.mean(intervals) if intervals else 0.0),
        "Number": float(len(packets)),
        "Magnitue": float(math.sqrt(sum(length * length for length in lengths))),
        "Covariance": float(statistics.pvariance(lengths) if len(lengths) > 1 else 0.0),
        "Weight": float(total_bytes / duration),
    }
    return [values[name] for name in FEATURE_NAMES]


@dataclass
class DeviceState:
    mac: str
    name: str = "Unknown device"
    ip_address: str | None = None
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    status: str = "SAFE"
    attack_probability: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LENGTH))
    consecutive_attack_windows: int = 0
    blocked: bool = False

    def to_dict(self):
        prediction = "Attack" if self.status in {"WARNING", "ALERT", "BLOCKED"} else "Benign"
        online = self.blocked or time.time() - self.last_seen <= DEVICE_TIMEOUT_SECONDS
        return {
            "mac": self.mac,
            "name": self.name,
            "ip_address": self.ip_address,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "online": online,
            "status": self.status,
            "prediction": prediction,
            "attack_probability": round(self.attack_probability * 100, 2),
            "blocked": self.blocked,
            "model": DEFAULT_MODEL_PATH,
            "consecutive_attack_windows": self.consecutive_attack_windows,
            "interface": network_control.HOSTAPD_INTERFACE,
        }


class DeviceRegistry:
    def __init__(self):
        self._devices: dict[str, DeviceState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, mac, name=None, ip_address=None):
        mac = str(mac).strip().lower()
        with self._lock:
            state = self._devices.get(mac)
            if state is None:
                state = DeviceState(mac=mac, name=name or "Unknown device", ip_address=ip_address)
                self._devices[mac] = state
            else:
                state.last_seen = time.time()
                if name and name.strip() and name.strip() != "Unknown device":
                    state.name = name.strip()
                elif not state.name or state.name == "Unknown device":
                    if name and name.strip():
                        state.name = name.strip()
                if ip_address:
                    state.ip_address = ip_address
            return state

    def load_from_db(self, rows):
        """Rehydrates the in-memory registry after a restart so device
        counts and last-known status survive an agent restart."""
        with self._lock:
            for row in rows:
                mac = str(row["mac"]).strip().lower()
                self._devices[mac] = DeviceState(
                    mac=mac,
                    name=row["name"] or "Unknown device",
                    ip_address=row["ip_address"],
                    first_seen=row["first_seen"] or time.time(),
                    last_seen=row["last_seen"] or time.time(),
                    status=row["status"] or "SAFE",
                    attack_probability=row["attack_probability"] or 0.0,
                    blocked=bool(row["blocked"]),
                )

    def all(self):
        with self._lock:
            return [state.to_dict() for state in self._devices.values()]

    def find(self, mac):
        with self._lock:
            return self._devices.get(str(mac).strip().lower())

    def blocked_devices(self):
        with self._lock:
            return [state for state in self._devices.values() if state.blocked]

    def remove(self, mac):
        with self._lock:
            return self._devices.pop(str(mac).strip().lower(), None) is not None


registry = DeviceRegistry()


def resolve_ip_from_neighbor_table(mac):
    try:
        result = subprocess.run(
            ["ip", "neigh", "show"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    mac = mac.lower()
    for line in result.stdout.splitlines():
        fields = line.split()
        if mac in [field.lower() for field in fields] and fields:
            return fields[0]
    return None


def resolve_mac_from_neighbor_table(ip_address):
    try:
        result = subprocess.run(
            ["ip", "neigh", "show", ip_address],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    fields = result.stdout.split()
    if "lladdr" not in fields:
        return None
    try:
        return fields[fields.index("lladdr") + 1].lower()
    except IndexError:
        return None


def network_neighbors(interface):
    try:
        result = subprocess.run(
            ["ip", "neigh", "show", "dev", interface],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    neighbors = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        try:
            mac = fields[fields.index("lladdr") + 1].lower()
        except (ValueError, IndexError):
            continue
        state = fields[-1].upper()
        if state in {"FAILED", "INCOMPLETE"}:
            continue
        neighbors.append({"ip_address": fields[0], "mac": mac, "neighbor_state": state})
    return neighbors


def load_model():
    """Loads the training checkpoint bundle: state dict, feature scaler, and
    this model's own calibrated Benign-probability threshold."""
    checkpoint = torch.load(DEFAULT_MODEL_PATH, map_location=DEVICE, weights_only=False)

    feature_names = checkpoint["feature_names"]
    model = Ghost1D_GRU(input_dim=len(feature_names), num_classes=2).to(DEVICE)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    scaler_mean = torch.tensor(checkpoint["scaler_mean"], dtype=torch.float32, device=DEVICE)
    scaler_scale = torch.tensor(checkpoint["scaler_scale"], dtype=torch.float32, device=DEVICE)
    benign_threshold = float(checkpoint.get("benign_threshold", 0.5))
    attack_threshold = 1.0 - benign_threshold

    return model, scaler_mean, scaler_scale, attack_threshold


def refresh_global_model():
    """Reload a checkpoint written by the Pi Flower client after FedAvg."""
    try:
        modified = DEFAULT_MODEL_PATH.stat().st_mtime
    except OSError:
        return
    if modified <= _model_holder.get("model_mtime", 0):
        return
    with _model_reload_lock:
        if modified <= _model_holder.get("model_mtime", 0):
            return
        model, scaler_mean, scaler_scale, attack_threshold = load_model()
        _model_holder.update(
            model=model,
            scaler_mean=scaler_mean,
            scaler_scale=scaler_scale,
            attack_threshold=attack_threshold,
            model_mtime=modified,
        )
        print(f"Reloaded federated global model from {DEFAULT_MODEL_PATH}")


def save_labeled_demo_sample(features, traffic_type):
    """Keep Fold8's explicitly labeled demo examples on the Pi for local fit."""
    if traffic_type is None:
        return
    label = "attack" if traffic_type.lower() == "attack" else "benign"
    FEDERATED_SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _federated_samples_lock:
        new_file = not FEDERATED_SAMPLES_PATH.exists()
        with FEDERATED_SAMPLES_PATH.open("a", newline="", encoding="utf-8") as sample_file:
            writer = csv.writer(sample_file)
            if new_file:
                writer.writerow([*FEATURE_NAMES, "label", "collected_at"])
            writer.writerow([*features, label, time.time()])


def classify(model, scaler_mean, scaler_scale, features):
    x = torch.tensor([features], dtype=torch.float32, device=DEVICE)
    x = (x - scaler_mean) / scaler_scale
    with torch.no_grad():
        logits = model(x)
        probabilities = torch.softmax(logits, dim=1)
        attack_probability = probabilities[0, ATTACK_CLASS_INDEX].item()
    return attack_probability


def update_device_status(state, attack_probability, attack_threshold):
    previous_status = state.status
    state.attack_probability = attack_probability
    state.history.append(attack_probability)

    if state.blocked:
        state.status = "BLOCKED"
        _persist(state, previous_status)
        return

    if attack_probability >= attack_threshold:
        state.consecutive_attack_windows += 1
    else:
        state.consecutive_attack_windows = 0

    if state.consecutive_attack_windows >= CONFIRM_WINDOWS_BEFORE_BLOCK:
        state.status = "ALERT"
        success, detail = network_control.block_mac(state.mac, target_ip=state.ip_address)
        state.blocked = success
        if success:
            state.status = "BLOCKED"
        print(f"[block] {state.mac} ({state.name}): success={success} detail={detail}")
        _persist(state, previous_status)
        return

    if attack_probability >= attack_threshold:
        state.status = "WARNING"
        _persist(state, previous_status)
        return

    recent = list(state.history)[-WARNING_RISING_STEPS:]
    rising = len(recent) == WARNING_RISING_STEPS and all(
        recent[i] < recent[i + 1] for i in range(len(recent) - 1)
    )
    if rising and recent[-1] >= WARNING_MIN_PROBABILITY:
        state.status = "WARNING"
    else:
        state.status = "SAFE"
    _persist(state, previous_status)


def _persist(state, previous_status):
    """Writes the current device row and, on any status change, an event row
    so the app's Activity tab and device dashboard have real history."""
    storage.upsert_device(state)
    if state.status != previous_status:
        storage.log_event(state)


def capture_loop(iface, model, scaler_mean, scaler_scale, attack_threshold):
    buffers: dict[str, list] = {}
    buffer_lock = threading.Lock()

    def handle_packet(packet):
        if not packet.haslayer(Ether):
            return
        mac = packet[Ether].src.lower()
        if is_excluded_device(mac):
            return
        with buffer_lock:
            buffers.setdefault(mac, []).append(packet)

    def process_windows():
        while True:
            time.sleep(WINDOW_SECONDS)
            with buffer_lock:
                snapshot = buffers
                buffers.clear()

            for mac, packets in snapshot.items():
                if len(packets) < MIN_PACKETS_PER_WINDOW:
                    continue
                refresh_global_model()
                model = _model_holder["model"]
                scaler_mean = _model_holder["scaler_mean"]
                scaler_scale = _model_holder["scaler_scale"]
                attack_threshold = _model_holder["attack_threshold"]
                state = registry.get_or_create(mac)
                if state.blocked:
                    continue
                features = features_from_packets(packets)
                attack_probability = classify(model, scaler_mean, scaler_scale, features)
                update_device_status(state, attack_probability, attack_threshold)

            now = time.time()
            for state in list(registry._devices.values()):
                if now - state.last_seen > DEVICE_TIMEOUT_SECONDS and not state.blocked:
                    state.status = "SAFE"

    threading.Thread(target=process_windows, daemon=True).start()
    sniff(iface=iface, prn=handle_packet, store=False)


app = FastAPI()

PUBLIC_WITHOUT_HOUSEHOLD = {
    "/health",
    "/auth/signup",
    "/auth/login",
    "/auth/change-password",
    "/auth/request-password-reset",
    "/auth/reset-password",
    "/household/role",
    "/gateway/claim",
}
COORDINATOR_ROUTES = {"/federated/start-client", "/federated/stop-client"}
PRIVATE_AGENT_ROUTES = {"/cloud-agent/snapshot", "/cloud-agent/control"}


@app.middleware("http")
async def require_private_tunnel_token(request: Request, call_next):
    token = os.getenv("GHOST_ROUTER_TOKEN", "")
    if request.url.path != "/health" and not token:
        return JSONResponse(status_code=503, content={"detail": "Configure the private gateway token on the Pi before serving API requests."})
    if token and not secrets.compare_digest(request.headers.get("X-Gateway-Token", "").encode(), token.encode()):
        return JSONResponse(status_code=401, content={"detail": "Use the authenticated Render gateway."})
    if (
        request.method != "OPTIONS"
        and request.url.path not in PUBLIC_WITHOUT_HOUSEHOLD
        and request.url.path not in COORDINATOR_ROUTES
        and request.url.path not in PRIVATE_AGENT_ROUTES
    ):
        email = request.headers.get("X-Gateway-User", "").strip().lower()
        role = storage.household_role(email) if email else None
        if role is None:
            return JSONResponse(status_code=403, content={"detail": "This account is not a member of the claimed household."})
        request.state.household_email = email
        request.state.household_role = role
        context_token = _gateway_user_email.set(email)
    else:
        context_token = None
    try:
        return await call_next(request)
    finally:
        if context_token is not None:
            _gateway_user_email.reset(context_token)


def require_household_admin(request: Request, owner_only: bool = False):
    role = getattr(request.state, "household_role", None)
    allowed = {"owner"} if owner_only else {"owner", "admin"}
    if role not in allowed:
        raise HTTPException(status_code=403, detail="Household owner or admin permission is required.")


class TelemetryPayload(BaseModel):
    device: str = "Demo Device"
    mac: str = Field(pattern=r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
    ip_address: str | None = None
    features: list[float] = Field(min_length=len(FEATURE_NAMES), max_length=len(FEATURE_NAMES))
    traffic_type: str | None = None


class SignupPayload(BaseModel):
    name: str
    email: str
    password: str
    access_code: str = ""


class LoginPayload(BaseModel):
    email: str
    password: str
    access_code: str = ""


class ChangePasswordPayload(BaseModel):
    email: str = ""
    current_password: str
    new_password: str


class GatewayClaimPayload(BaseModel):
    pairing_code: str


class HouseholdInvitePayload(BaseModel):
    email: str
    role: str = "member"


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetPayload(BaseModel):
    email: str
    token: str
    new_password: str


class RegisterDevicePayload(BaseModel):
    name: str
    mac: str = Field(pattern=r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
    ip_address: str


def _ensure_household_device(mac):
    if not storage.is_household_device(mac):
        raise HTTPException(status_code=404, detail="Device is not registered to this household.")


class FederatedStartClientPayload(BaseModel):
    server_address: str = Field(pattern=r"^[0-9A-Za-z.:-]+$")


_model_holder: dict[str, object] = {}


@app.get("/cloud-agent/snapshot")
def cloud_agent_snapshot():
    if os.getenv("GHOST_CLOUD_UPLOAD_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Cloud snapshot export is disabled.")
    devices = list_devices()["devices"]
    if len(devices) > 500:
        raise HTTPException(status_code=503, detail="Cloud snapshot device limit exceeded.")
    events = [
        event for event in storage.recent_events(100)
        if not is_excluded_device(event["mac"])
    ]
    with _model_reload_lock:
        model_available = _model_holder.get("model") is not None
        model_mtime = _model_holder.get("model_mtime")
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "devices": [
            {key: device[key] for key in (
                "mac", "name", "ip_address", "status", "attack_probability", "blocked",
            )}
            for device in devices
        ],
        "alerts": [
            {
                "event_id": event["id"], "mac": event["mac"], "status": event["status"],
                "attack_probability": round(event["attack_probability"] * 100, 2),
                "timestamp": datetime.fromtimestamp(event["timestamp"], timezone.utc).isoformat(),
            }
            for event in events
        ],
        "model": {
            "available": model_available,
            "checkpoint_name": DEFAULT_MODEL_PATH.name if model_available else None,
            "updated_at": (
                datetime.fromtimestamp(model_mtime, timezone.utc).isoformat()
                if model_available and model_mtime is not None else None
            ),
        },
    }


@app.get("/devices")
def list_devices():
    for neighbor in network_neighbors(network_control.HOSTAPD_INTERFACE):
        mac = neighbor["mac"].lower()
        if is_excluded_device(mac) or storage.is_device_hidden(mac):
            continue
        state = registry.get_or_create(
            mac,
            ip_address=neighbor["ip_address"],
        )
        if neighbor["neighbor_state"] in {"REACHABLE", "DELAY", "PROBE"}:
            state.last_seen = time.time()
        storage.upsert_device(state)

    for state in list(registry._devices.values()):
        if state.ip_address is None:
            state.ip_address = resolve_ip_from_neighbor_table(state.mac)
            if state.ip_address:
                storage.upsert_device(state)
    household_macs = {device["mac"].lower() for device in storage.all_devices()}
    return {"devices": [
        device for device in registry.all()
        if device["mac"].lower() in household_macs
        and not is_excluded_device(device["mac"])
    ]}


@app.get("/household/role")
def get_household_role(request: Request):
    email = request.headers.get("X-Gateway-User", "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Sign in to check household access.")
    return {"role": storage.household_role(email)}


@app.get("/federated-status")
def federated_status():
    try:
        checkpoint = torch.load(DEFAULT_MODEL_PATH, map_location="cpu", weights_only=False)
    except (OSError, RuntimeError, EOFError) as error:
        raise HTTPException(status_code=503, detail=f"Federated model unavailable: {error}") from error
    if not isinstance(checkpoint, dict) or "model_state_dict" not in checkpoint:
        raise HTTPException(status_code=503, detail="Pi checkpoint is not an inference bundle with model and scaler metadata.")

    modified_at = checkpoint.get("updated_at") or DEFAULT_MODEL_PATH.stat().st_mtime
    try:
        with urllib.request.urlopen(
            urllib.request.Request(laptop_control_url("/federated-training/status"),
                                   headers={
                                       "X-Gateway-Token": os.getenv("GHOST_ROUTER_TOKEN", ""),
                                       **({"X-Gateway-User": _gateway_user_email.get()} if _gateway_user_email.get() else {}),
                                   }),
            timeout=3,
        ) as response:
            training = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, HTTPException) as error:
        print(f"[coordinator status] {error}")
        training = {
            "state": "unavailable",
            "current_round": 0,
            "total_rounds": 10,
            "laptop_client_running": False,
            "error": "Laptop coordinator offline; Pi monitoring and model inference are still available.",
        }

    return {
        "architecture": "federated-learning",
        "status": "federated" if checkpoint.get("aggregation") == "FedAvg" else "pretrained",
        "aggregation": checkpoint.get("aggregation", "Unknown"),
        "federated_round": checkpoint.get("federated_round"),
        "federated_clients": checkpoint.get("federated_clients"),
        "feature_count": len(checkpoint.get("feature_names", FEATURE_NAMES)),
        "updated_at": modified_at,
        "training": training,
        "model_source": "raspberry-pi",
        "participants": [
            {"role": "Laptop trainer", "monitored_device": False},
            {"role": "Raspberry Pi trainer", "monitored_device": False},
        ],
    }


@app.post("/federated/start")
def start_federated_training_from_pi(request: Request):
    require_household_admin(request)
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                laptop_control_url("/federated/train"),
                data=b"{}",
                headers={"Content-Type": "application/json",
                         "X-Gateway-Token": os.getenv("GHOST_ROUTER_TOKEN", ""),
                         **({"X-Gateway-User": _gateway_user_email.get()} if _gateway_user_email.get() else {})},
                method="POST",
            ),
            timeout=15,
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=error.code, detail=detail) from error
    except (OSError, urllib.error.URLError) as error:
        raise HTTPException(status_code=502, detail=f"Laptop Flower coordinator unavailable: {error}") from error


@app.post("/federated/start-client")
def start_pi_federated_client(payload: FederatedStartClientPayload):
    with _federated_client_lock:
        return _start_pi_federated_client(payload)


def _start_pi_federated_client(payload: FederatedStartClientPayload):
    global _federated_client_process
    if _federated_client_process is not None and _federated_client_process.poll() is None:
        raise HTTPException(status_code=409, detail="The Pi federated client is already running.")
    if not FEDERATED_SAMPLES_PATH.exists():
        raise HTTPException(status_code=400, detail=f"Pi training samples not found: {FEDERATED_SAMPLES_PATH}")

    with FEDERATED_SAMPLES_PATH.open("r", newline="", encoding="utf-8") as sample_file:
        labels = {str(row.get("label", "")).strip().lower() for row in csv.DictReader(sample_file)}
    if not {"attack", "benign"}.issubset(labels):
        raise HTTPException(status_code=400, detail="Pi training samples must include both attack and benign labels.")

    _federated_client_log.parent.mkdir(parents=True, exist_ok=True)
    with _federated_client_log.open("a", encoding="utf-8") as log_file:
        _federated_client_process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "federated_client.py"),
                "--role",
                "pi",
                "--server-address",
                payload.server_address,
            ],
            cwd=Path(__file__).resolve().parent,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    return {"success": True, "state": "starting", "pid": _federated_client_process.pid}


@app.post("/federated/stop-client")
def stop_pi_federated_client():
    with _federated_client_lock:
        return _stop_pi_federated_client()


def _stop_pi_federated_client():
    if _federated_client_process is not None and _federated_client_process.poll() is None:
        _federated_client_process.terminate()
        try:
            _federated_client_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _federated_client_process.kill()
            _federated_client_process.wait()
    return {"success": True, "state": "stopped"}


@app.post("/devices/register")
def register_device(payload: RegisterDevicePayload, request: Request):
    require_household_admin(request)
    return apply_device_registration(payload)


def apply_device_registration(payload: RegisterDevicePayload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Device name is required.")
    mac = payload.mac.strip().lower()
    if is_excluded_device(mac):
        raise HTTPException(status_code=400, detail="This MAC address is reserved for the federated-learning server.")
    with _device_control_lock:
        storage.restore_device(mac)
        ip_address = (payload.ip_address or "").strip() or resolve_ip_from_neighbor_table(mac)
        state = registry.get_or_create(
            mac,
            name=name,
            ip_address=ip_address,
        )
        state.name = name
        if ip_address:
            state.ip_address = ip_address
        storage.upsert_device(state)
        return state.to_dict()


@app.delete("/devices/{mac}")
def delete_device(mac: str, request: Request):
    require_household_admin(request)
    return apply_device_removal(mac)


def apply_device_removal(mac: str):
    normalized = mac.strip().lower()
    if is_excluded_device(normalized):
        raise HTTPException(status_code=400, detail="The federated-learning server is not managed as an IoT device.")
    with _device_control_lock:
        _ensure_household_device(normalized)
        # Firewall rules may survive a process restart without an in-memory state.
        result = apply_device_control(normalized, "unblock")
        if not result["success"]:
            raise HTTPException(status_code=503, detail="Could not unblock device before removal.")
        storage.delete_device(normalized)
        registry.remove(normalized)
    return {"success": True, "mac": normalized}


@app.get("/events")
def list_events(limit: int = 50):
    events = storage.recent_events(limit)
    return {"events": [event for event in events if not is_excluded_device(event.get("mac"))]}


@app.post("/auth/signup")
def signup(payload: SignupPayload):
    success, error = storage.create_account(
        payload.name, payload.email, payload.password, payload.access_code
    )
    if not success:
        return {"success": False, "error": error}
    return {
        "success": True,
        "name": payload.name.strip(),
        "email": payload.email.strip().lower(),
        "household_role": storage.household_role(payload.email),
    }


@app.post("/auth/login")
def login(payload: LoginPayload):
    success, error, account = storage.verify_account(payload.email, payload.password)
    if not success:
        return {"success": False, "error": error}
    if payload.access_code and account["household_role"] is None:
        accepted, invite_error, role = storage.accept_invite(
            payload.email, payload.access_code
        )
        if not accepted:
            return {"success": False, "error": invite_error}
        account["household_role"] = role
    return {"success": True, **account}


@app.post("/gateway/claim")
def claim_gateway(payload: GatewayClaimPayload, request: Request):
    email = request.headers.get("X-Gateway-User", "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Sign in before claiming this gateway.")
    success, error, role = storage.claim_gateway(email, payload.pairing_code)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True, "household_role": role}


@app.post("/household/invites")
def invite_household_member(payload: HouseholdInvitePayload, request: Request):
    inviter = request.state.household_email
    success, error, invite = storage.create_invite(inviter, payload.email, payload.role)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True, **invite}


def send_reset_email(email, token=None):
    host = os.getenv("GHOST_SMTP_HOST")
    implicit_tls = os.getenv("GHOST_SMTP_SSL", "").strip().lower() in {"1", "true", "yes"}
    port = int(os.getenv("GHOST_SMTP_PORT", "465" if implicit_tls else "587"))
    username = os.getenv("GHOST_SMTP_USERNAME")
    password = os.getenv("GHOST_SMTP_PASSWORD")
    sender = os.getenv("GHOST_SMTP_FROM", username or "")
    if not host or not sender:
        return False
    message = EmailMessage()
    message["Subject"] = "caughtIn4K password reset"
    message["From"] = sender
    message["To"] = email
    if token is None:
        message.set_content("If an account exists for this address, a reset code will be sent.")
    else:
        message.set_content(f"Your caughtIn4K password reset code is {token}. It expires in 15 minutes.")
    if implicit_tls:
        smtp_factory = lambda: smtplib.SMTP_SSL(
            host, port, timeout=10, context=ssl.create_default_context()
        )
    else:
        smtp_factory = lambda: smtplib.SMTP(host, port, timeout=10)
    with smtp_factory() as smtp:
        if not implicit_tls:
            smtp.starttls(context=ssl.create_default_context())
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


@app.post("/auth/change-password")
def change_password(payload: ChangePasswordPayload, request: Request):
    email = request.headers.get("X-Gateway-User", "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Sign in again to change your password.")
    success, error = storage.change_password(
        email, payload.current_password, payload.new_password
    )
    return {"success": success, **({} if success else {"error": error})}


@app.post("/auth/request-password-reset")
def request_password_reset(payload: PasswordResetRequest):
    token = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = time.time() + 900
    created = storage.create_password_reset(payload.email, token, expires_at)
    try:
        delivered = send_reset_email(
            payload.email.strip().lower(), token if created else None
        )
        if not delivered:
            if created:
                storage.delete_password_reset(payload.email)
            raise HTTPException(status_code=503, detail="Password reset email delivery is not configured.")
    except (OSError, ValueError, smtplib.SMTPException) as error:
        if created:
            storage.delete_password_reset(payload.email)
        print(f"[auth] password reset email delivery failed: {type(error).__name__}")
        raise HTTPException(status_code=503, detail="Password reset email could not be delivered.") from error
    return {"success": True, "message": "If the account exists, a reset code was sent."}


@app.post("/auth/reset-password")
def reset_password(payload: PasswordResetPayload):
    success, error = storage.reset_password(
        payload.email, payload.token, payload.new_password
    )
    return {"success": success, **({} if success else {"error": error})}


@app.post("/devices/{mac}/block")
def force_block(mac: str, request: Request):
    if getattr(request.state, "household_role", None) not in {"owner", "admin", "member"}:
        raise HTTPException(status_code=403, detail="Household access is required.")
    return apply_device_control(mac, "block")


_device_control_lock = threading.RLock()


def apply_device_control(mac: str, action: Literal["block", "unblock"]):
    mac = mac.lower()
    if is_excluded_device(mac):
        raise HTTPException(status_code=400, detail="The federated-learning server is not managed as an IoT device.")
    _ensure_household_device(mac)
    with _device_control_lock:
        state = registry.find(mac)
        if action == "block":
            target_ip = state.ip_address if state is not None else None
            success, detail = network_control.block_mac(mac, target_ip=target_ip)
        else:
            success, detail = network_control.unblock_mac(mac)
        if state is not None and success:
            state.blocked = action == "block"
            state.status = "BLOCKED" if state.blocked else "SAFE"
            if action == "unblock":
                state.consecutive_attack_windows = 0
            storage.upsert_device(state)
            storage.log_event(state)
    return {"mac": mac, "success": success, "detail": detail}


class CloudControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    action: Literal["block", "unblock", "register", "remove"]
    mac: str = Field(pattern=r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
    expires_at: datetime
    device_name: str | None = Field(default=None, min_length=1, max_length=200)
    ip_address: str | None = Field(default=None, max_length=15)


@app.post("/cloud-agent/control")
def cloud_device_control(payload: CloudControlPayload, request: Request):
    if os.getenv("GHOST_CLOUD_CONTROL_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Cloud controls are disabled.")
    if request.client is None or request.client.host != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Cloud controls require a loopback connection.")
    if payload.expires_at.tzinfo is None or payload.expires_at <= datetime.now(timezone.utc):
        return {"success": False, "result_code": "expired"}
    if payload.action in {"register", "remove"} and os.getenv(
        "GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED", "false"
    ).lower() != "true":
        raise HTTPException(status_code=404, detail="Cloud device management is disabled.")
    if payload.action == "register":
        from ipaddress import IPv4Address
        if not payload.device_name or payload.device_name != payload.device_name.strip() or payload.ip_address is None:
            raise HTTPException(status_code=422, detail="Device registration details are invalid.")
        try:
            if payload.ip_address:
                IPv4Address(payload.ip_address)
        except ValueError:
            raise HTTPException(status_code=422, detail="Device IPv4 address is invalid.") from None
        apply_device_registration(RegisterDevicePayload(
            name=payload.device_name, mac=payload.mac, ip_address=payload.ip_address,
        ))
        result = {"success": True}
    else:
        if payload.device_name is not None or payload.ip_address is not None:
            raise HTTPException(status_code=422, detail="Unexpected device registration details.")
        if payload.action == "remove":
            result = apply_device_removal(payload.mac)
        else:
            result = apply_device_control(payload.mac, payload.action)
    if not result["success"]:
        print(f"[cloud-control] Network enforcement failed: {result['detail']}", flush=True)
    return {
        "success": result["success"],
        "result_code": "applied" if result["success"] else "enforcement_failed",
    }


@app.post("/wifi/connect")
def wifi_connect(ssid: str, password: str, request: Request):
    """Lets the Pi join any Wi-Fi network on demand, instead of being locked
    to one. The Pi's IP will change after switching networks; re-fetch it
    (e.g. via /wifi/status or your router setup) and update the app's
    ROUTER_API_URL accordingly."""
    require_household_admin(request)
    success, detail = wifi_client.connect(ssid, password)
    return {"success": success, "detail": detail}


@app.get("/wifi/status")
def wifi_status(request: Request):
    require_household_admin(request)
    return {"ssid": wifi_client.current_status()}


@app.post("/devices/{mac}/unblock")
def force_unblock(mac: str, request: Request):
    if getattr(request.state, "household_role", None) not in {"owner", "admin", "member"}:
        raise HTTPException(status_code=403, detail="Household access is required.")
    return apply_device_control(mac, "unblock")


@app.post("/telemetry")
def ingest_demo_telemetry(payload: TelemetryPayload, request: Request):
    """Feature-replay endpoint for demonstrations; does not require real packets."""
    source_ip = request.client.host if request.client is not None else payload.ip_address
    observed_mac = resolve_mac_from_neighbor_table(source_ip) if source_ip else None
    device_mac = observed_mac or payload.mac.lower()
    if is_excluded_device(device_mac):
        if payload.mac and not is_excluded_device(payload.mac.lower()):
            device_mac = payload.mac.lower()
        else:
            raise HTTPException(status_code=403, detail="This MAC address is reserved for the federated-learning server.")
    if not storage.is_household_device(device_mac):
        raise HTTPException(status_code=403, detail="Telemetry target is not registered to this household.")
    if storage.is_device_hidden(device_mac):
        storage.restore_device(device_mac)
    if payload.traffic_type is not None and payload.traffic_type.lower() not in {"attack", "normal", "benign"}:
        raise HTTPException(status_code=422, detail="traffic_type must be attack, normal, or benign.")
    if payload.traffic_type is not None:
        save_labeled_demo_sample(payload.features, payload.traffic_type)
    refresh_global_model()
    model = _model_holder["model"]
    scaler_mean = _model_holder["scaler_mean"]
    scaler_scale = _model_holder["scaler_scale"]
    attack_threshold = _model_holder["attack_threshold"]
    device_name = payload.device.strip() if payload.device else None
    state = registry.get_or_create(
        device_mac,
        name=device_name,
        ip_address=source_ip or payload.ip_address,
    )
    if device_name and device_name != "Unknown device":
        state.name = device_name
    if state.ip_address is None:
        state.ip_address = resolve_ip_from_neighbor_table(state.mac)
    if state.blocked:
        return {"mac": state.mac, "name": state.name, "status": state.status, "attack_probability": state.attack_probability}
    attack_probability = classify(model, scaler_mean, scaler_scale, payload.features)
    update_device_status(state, attack_probability, attack_threshold)
    return {
        "mac": state.mac,
        "name": state.name,
        "status": state.status,
        "attack_probability": round(state.attack_probability * 100, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="caughtIn4K router-based IDS agent")
    parser.add_argument("--iface", default="wlan0", help="AP interface to sniff on")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--no-capture", action="store_true", help="Serve API only, for demo without real Wi-Fi capture")
    args = parser.parse_args()

    model, scaler_mean, scaler_scale, attack_threshold = load_model()
    storage.init_db()
    registry.load_from_db(storage.all_devices())
    for state in registry.blocked_devices():
        if is_excluded_device(state.mac):
            success, detail = network_control.unblock_mac(state.mac)
            if success:
                state.blocked = False
                state.status = "SAFE"
                storage.upsert_device(state)
            else:
                print(f"[block restore] excluded server {state.mac}: failed to unblock ({detail})")
            continue
        success, detail = network_control.block_mac(
            state.mac,
            target_ip=state.ip_address,
        )
        if not success:
            state.blocked = False
            state.status = "SAFE"
            storage.upsert_device(state)
            print(f"[block restore] {state.mac}: failed ({detail})")
    _model_holder["model"] = model
    _model_holder["scaler_mean"] = scaler_mean
    _model_holder["scaler_scale"] = scaler_scale
    _model_holder["attack_threshold"] = attack_threshold
    _model_holder["model_mtime"] = DEFAULT_MODEL_PATH.stat().st_mtime
    print(f"Loaded model; attack_threshold={attack_threshold:.3f}")

    if not args.no_capture:
        threading.Thread(
            target=capture_loop,
            args=(args.iface, model, scaler_mean, scaler_scale, attack_threshold),
            daemon=True,
        ).start()

    uvicorn.run(app, host="0.0.0.0", port=args.api_port)


if __name__ == "__main__":
    main()
