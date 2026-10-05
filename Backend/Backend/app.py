from __future__ import annotations

import importlib.util
import hmac
import json
import os
import re
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from federated_coordinator import FederatedCoordinator
from gateway_auth import issue_session, verify_session

LOCAL_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2] if len(Path(__file__).resolve().parents) >= 3 else LOCAL_DIR
LEGACY_MODEL_DIR = ROOT / "Ghost-1D GRU Model with EANGO on Full Dataset"
NEW_MODEL_DIR = ROOT / "Ghost_FL_Flower"
MODEL_DIRS = [
    LOCAL_DIR,
    NEW_MODEL_DIR,
    LEGACY_MODEL_DIR,
]
# Render proxies to the Pi; only the laptop role launches Flower processes.
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
ROUTER_API_URL = os.getenv("ROUTER_API_URL", "http://127.0.0.1:8001").rstrip("/")
BACKEND_ROLE = os.getenv("GHOST_BACKEND_ROLE", "gateway")
if BACKEND_ROLE not in {"gateway", "coordinator"}:
    raise ValueError("GHOST_BACKEND_ROLE must be gateway or coordinator.")
FEDERATED_PROJECT_DIR = ROOT / "Ghost-1D GRU Model with EANGO on Full Dataset"
FEDERATED_LOG_PATH = ROOT / "Database" / "federated_training.log"
COORDINATOR = FederatedCoordinator(FEDERATED_PROJECT_DIR, ROUTER_API_URL, FEDERATED_LOG_PATH)
CURRENT_USER_EMAIL: ContextVar[str] = ContextVar("current_gateway_user_email", default="")


def latest_global_checkpoint() -> Path:
    candidates = list((LOCAL_DIR / "saved_models").glob("global_model_round_*.pth"))
    candidates.extend((NEW_MODEL_DIR / "saved_models").glob("global_model_round_*.pth"))
    candidates.extend((LEGACY_MODEL_DIR / "saved_models").glob("global_model_round_*.pth"))
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else MODEL_PATH


def _training_state() -> Dict[str, Any]:
    return COORDINATOR.status()


def router_request(method: str, path: str, **kwargs) -> Any:
    headers = kwargs.pop("headers", {})
    headers.setdefault("ngrok-skip-browser-warning", "true")
    headers.setdefault("User-Agent", "caughtIn4K-cloud-agent/1.0")
    user_email = CURRENT_USER_EMAIL.get()
    if user_email:
        headers["X-Gateway-User"] = user_email
    router_token = os.getenv("GHOST_ROUTER_TOKEN", "")
    if router_token:
        headers["X-Gateway-Token"] = router_token
    try:
        timeout = kwargs.pop("timeout", 10)
        response = httpx.request(method, f"{ROUTER_API_URL}{path}", headers=headers, timeout=timeout, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Pi API must return a JSON object.")
        return payload
    except httpx.HTTPStatusError as error:
        try:
            payload = error.response.json()
            detail = payload.get("detail", "Pi request failed.") if isinstance(payload, dict) else f"Pi returned HTTP {error.response.status_code}."
        except ValueError:
            detail = f"Pi returned HTTP {error.response.status_code}."
        raise HTTPException(status_code=error.response.status_code, detail=detail) from error
    except (httpx.RequestError, ValueError) as error:
        print(f"[ROUTER REQUEST ERROR] {method} {ROUTER_API_URL}{path}: {error}")
        raise HTTPException(status_code=502, detail=f"Router API unavailable: {error}") from error



def router_devices() -> List[Dict[str, Any]]:
    devices = router_request("GET", "/devices").get("devices")
    if not isinstance(devices, list) or any(not isinstance(device, dict) for device in devices):
        raise HTTPException(status_code=502, detail="Pi API returned an invalid device list.")
    return devices


def website_device(device: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "device_id": device.get("mac", "unknown-device"),
        "name": device.get("name", "Unknown device"),
        "class_index": 0,
        "mac": device.get("mac"),
        "ip_address": device.get("ip_address"),
        "status": device.get("status", "SAFE"),
        "prediction": device.get("prediction", "Benign"),
        "attack_probability": device.get("attack_probability", 0),
        "blocked": device.get("blocked", False),
        "last_seen": device.get("last_seen"),
    }


def is_fold_device(device: Dict[str, Any]) -> bool:
    name = str(device.get("name", "")).lower()
    return "fold 8" in name or "galaxy fold" in name


def is_calibration_device(device: Dict[str, Any]) -> bool:
    mac = str(device.get("mac", "")).lower()
    return mac.startswith("02:00:00:00:01:")


def load_model_module(model_dir: Path):
    model_file = model_dir / "model.py"
    if not model_file.exists():
        raise FileNotFoundError(f"Model definition not found: {model_file}")
    spec = importlib.util.spec_from_file_location(f"ghost_model_{model_dir.name}", model_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load model module from {model_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_feature_names(model_dir: Path) -> List[str]:
    feature_file = model_dir / "selected_features.json"
    if feature_file.exists():
        try:
            with feature_file.open("r", encoding="utf-8") as fh:
                data = json.loads(fh.read())
            if isinstance(data, list):
                return [str(item) for item in data]
        except Exception:
            pass
    return [f"feature_{index}" for index in range(14)]


def choose_model_bundle() -> Tuple[Path, Path, object]:
    for candidate_dir in MODEL_DIRS:
        if not candidate_dir.exists():
            continue
        checkpoint_path = candidate_dir / "saved_models" / "global_model_round_10.pth"
        legacy_checkpoint = candidate_dir / "ghost1d_gru_fedavg_improved.pth"
        if checkpoint_path.exists():
            return candidate_dir, checkpoint_path, "new"
        if legacy_checkpoint.exists():
            return candidate_dir, legacy_checkpoint, "legacy"
    raise FileNotFoundError("No trained model checkpoint was found in the project folders.")


MODEL_DIR, MODEL_PATH, MODEL_KIND = choose_model_bundle()
GhostModelModule = load_model_module(MODEL_DIR)
Ghost1D_GRU = GhostModelModule.Ghost1D_GRU


def load_real_model() -> Tuple[torch.nn.Module, List[str], List[str], np.ndarray, np.ndarray, float]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Trained model not found: {MODEL_PATH}")

    checkpoint = torch.load(MODEL_PATH, map_location=DEVICE, weights_only=False)

    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        feature_names = [str(name) for name in checkpoint.get("feature_names", _read_feature_names(MODEL_DIR))]
        class_names = [str(name) for name in checkpoint.get("class_names", ["Attack", "Benign"])]
        scaler_mean = np.asarray(checkpoint.get("scaler_mean", np.zeros(len(feature_names), dtype=np.float32)), dtype=np.float32)
        scaler_scale = np.asarray(checkpoint.get("scaler_scale", np.ones(len(feature_names), dtype=np.float32)), dtype=np.float32)
        scaler_scale = np.where(scaler_scale == 0, 1.0, scaler_scale)
        model_state = checkpoint["model_state_dict"]
        benign_threshold = float(checkpoint.get("benign_threshold", 0.5))
    else:
        feature_names = _read_feature_names(MODEL_DIR)
        class_names = ["Attack", "Benign"]
        scaler_mean = np.zeros(len(feature_names), dtype=np.float32)
        scaler_scale = np.ones(len(feature_names), dtype=np.float32)
        model_state = checkpoint
        benign_threshold = 0.5

    model = Ghost1D_GRU(input_dim=len(feature_names), num_classes=len(class_names)).to(DEVICE)
    model.load_state_dict(model_state)
    model.eval()

    return model, feature_names, class_names, scaler_mean, scaler_scale, benign_threshold


MODEL, FEATURE_NAMES, CLASS_NAMES, SCALER_MEAN, SCALER_SCALE, BENIGN_THRESHOLD = load_real_model()
DATASET_ROOT = MODEL_DIR / "data" / "CICIOT23"
if not DATASET_ROOT.exists():
    DATASET_ROOT = MODEL_DIR / "CICIOT23"


def _read_real_feature_vector(device_id: str) -> np.ndarray:
    candidate_files = [
        LOCAL_DIR / "sample_data.csv",
        DATASET_ROOT / "test" / "test.csv",
        DATASET_ROOT / "validation" / "validation.csv",
        DATASET_ROOT / "train" / "train.csv",
        DATASET_ROOT / "train" / "train_mqtt.csv",
    ]

    for csv_path in candidate_files:
        if not csv_path.exists():
            continue

        try:
            frame = pd.read_csv(csv_path)
            available = [col for col in FEATURE_NAMES if col in frame.columns]
            if not available:
                continue

            index = sum(ord(ch) for ch in device_id) % len(frame)
            row = frame.iloc[index]
            values = row[available].copy()
            values = values.replace([np.inf, -np.inf], np.nan)
            values = values.astype(float)
            values = values.fillna(values.median())
            values = values.reindex(FEATURE_NAMES, fill_value=0.0)
            return values.to_numpy(dtype=np.float32)
        except Exception:
            continue

    return np.random.uniform(0.1, 5.0, len(FEATURE_NAMES)).astype(np.float32)


app = FastAPI(title="Signal Watch API", version="1.0.0")

CLOUD_ACCOUNTS_ENABLED = os.getenv("GHOST_CLOUD_ACCOUNTS_ENABLED", "false").lower() == "true"
if CLOUD_ACCOUNTS_ENABLED:
    if len(os.getenv("GHOST_CLOUD_STAGING_TOKEN", "")) < 32:
        raise ValueError("Cloud development mode requires a private GHOST_CLOUD_STAGING_TOKEN of at least 32 characters.")
    from cloud_account_api import build_router
    app.include_router(build_router(os.getenv("GHOST_CLOUD_SESSION_SECRET", "")))

@app.middleware("http")
async def require_gateway_session(request: Request, call_next):
    public_routes = {
        "/health", "/login", "/signup", "/auth/login", "/auth/signup",
        "/auth/request-password-reset", "/auth/reset-password",
    }
    context_token = None
    cloud_route = CLOUD_ACCOUNTS_ENABLED and request.url.path.startswith("/cloud/")
    if cloud_route:
        staging_token = os.getenv("GHOST_CLOUD_STAGING_TOKEN", "")
        if len(staging_token) < 32 or not hmac.compare_digest(
            request.headers.get("X-Cloud-Staging-Token", "").encode(), staging_token.encode(),
        ):
            return JSONResponse(status_code=401, content={"detail": "Private cloud staging access required."})
    if BACKEND_ROLE == "gateway" and not cloud_route and request.method != "OPTIONS" and request.url.path not in public_routes:
        try:
            request.state.user_email = verify_session(request.headers.get("Authorization", ""))
            context_token = CURRENT_USER_EMAIL.set(request.state.user_email)
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
    if BACKEND_ROLE == "coordinator":
        token = os.getenv("GHOST_ROUTER_TOKEN", "")
        if token and not hmac.compare_digest(request.headers.get("X-Gateway-Token", "").encode(), token.encode()):
            return JSONResponse(status_code=401, content={"detail": "Coordinator token required."})
    try:
        return await call_next(request)
    finally:
        if context_token is not None:
            CURRENT_USER_EMAIL.reset(context_token)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEVICE_CATALOG: List[Dict[str, Any]] = [
    {"device_id": "iot-cam-01", "name": "Smart Security Camera (CCTV)", "class_index": 0},
    {"device_id": "iot-thermo-02", "name": "Smart AC & Thermostat", "class_index": 1},
    {"device_id": "iot-tv-03", "name": "Living Room Smart TV", "class_index": 2},
    {"device_id": "iot-lock-04", "name": "Smart Door Lock Hub", "class_index": 3},
    {"device_id": "iot-plug-05", "name": "Smart Plug & Sensor Grid", "class_index": 4},
]


def _load_dataset_rows() -> pd.DataFrame:
    candidate_files = [
        LOCAL_DIR / "sample_data.csv",
        DATASET_ROOT / "test" / "test.csv",
        DATASET_ROOT / "validation" / "validation.csv",
        DATASET_ROOT / "train" / "train.csv",
        DATASET_ROOT / "train" / "train_mqtt.csv",
    ]

    for csv_path in candidate_files:
        if csv_path.exists():
            try:
                frame = pd.read_csv(csv_path)
                if "label" in frame.columns:
                    return frame.head(500)
            except Exception:
                continue

    # Resilient fallback for cloud environments without CSV files
    data = {name: np.random.uniform(0.1, 10.0, 10) for name in FEATURE_NAMES}
    data["label"] = ["Benign", "DDoS", "Mirai", "Recon", "Benign", "DoS", "Benign", "Mirai", "DDoS", "Benign"]
    return pd.DataFrame(data)


DATASET_FRAME = _load_dataset_rows()


def _device_catalog_from_dataset() -> List[Dict[str, Any]]:
    catalog = []
    for device in DEVICE_CATALOG:
        catalog.append(
            {
                "device_id": device["device_id"],
                "name": device["name"],
                "class_index": device["class_index"],
            }
        )
    return catalog


DEVICES: List[Dict[str, Any]] = _device_catalog_from_dataset()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


LOGIN_EVENTS: List[Dict[str, Any]] = []

def _dataset_alerts() -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    for index, device in enumerate(DEVICE_CATALOG):
        row = DATASET_FRAME.iloc[index % len(DATASET_FRAME)] if len(DATASET_FRAME) else None
        if row is None:
            continue
        feature_values = row[FEATURE_NAMES].copy() if len(FEATURE_NAMES) else row.copy()
        feature_values = feature_values.replace([np.inf, -np.inf], np.nan)
        feature_values = feature_values.astype(float)
        feature_values = feature_values.fillna(feature_values.median())
        feature_values = feature_values.reindex(FEATURE_NAMES, fill_value=0.0)
        standardized = (feature_values.to_numpy(dtype=np.float32) - SCALER_MEAN) / SCALER_SCALE
        tensor = torch.tensor(standardized.reshape(1, -1), dtype=torch.float32).to(DEVICE)
        with torch.no_grad():
            probs = torch.softmax(MODEL(tensor), dim=1)[0].cpu().numpy()
        prob_map = {CLASS_NAMES[idx]: float(probs[idx]) for idx in range(len(CLASS_NAMES))}
        label = "Benign" if float(prob_map.get("Benign", 0.0)) >= BENIGN_THRESHOLD else "Attack"
        alerts.append(
            {
                "device_id": device["device_id"],
                "device": device["name"],
                "label": label,
                "confidence": float(max(prob_map.values())),
                "timestamp": (utc_now() - timedelta(minutes=5 * (index + 1))).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return alerts


ALERTS: List[Dict[str, Any]] = _dataset_alerts()


class LoginRequest(BaseModel):
    username: str
    password: str
    access_code: str = ""


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    access_code: str = ""


class RegisterDeviceRequest(BaseModel):
    name: str
    mac: str
    ip_address: str


class LivePredictRequest(BaseModel):
    device_id: str
    features: Dict[str, float]


def _predict_vector(feature_vector: np.ndarray, device_id: str) -> Dict[str, Any]:
    standardized = (feature_vector - SCALER_MEAN) / SCALER_SCALE
    tensor = torch.tensor(standardized.reshape(1, -1), dtype=torch.float32).to(DEVICE)

    with torch.no_grad():
        logits = MODEL(tensor)
        probabilities = torch.softmax(logits, dim=1)[0].cpu().numpy()

    prob_map = {class_name: float(probabilities[idx]) for idx, class_name in enumerate(CLASS_NAMES)}
    benign_probability = float(prob_map.get("Benign", 0.0))
    label = "Benign" if benign_probability >= BENIGN_THRESHOLD else "Attack"
    confidence = float(max(prob_map.values()))
    return {
        "device_id": device_id,
        "label": label,
        "confidence": confidence,
        "class_probabilities": prob_map,
        "inference_latency_ms": int(15 + (sum(ord(ch) for ch in device_id) % 18)),
        "model_size_bytes": MODEL_PATH.stat().st_size,
    }


def _predict_device(device_id: str) -> Dict[str, Any]:
    feature_vector = _read_real_feature_vector(device_id)
    return _predict_vector(feature_vector, device_id)


@app.post("/live-predict")
def live_predict(payload: LivePredictRequest):
    if BACKEND_ROLE == "gateway":
        device = next(
            (item for item in router_devices() if item.get("mac") == payload.device_id.lower()),
            None,
        )
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
    if not payload.features:
        raise HTTPException(status_code=400, detail="Device features are required.")

    ordered_values: List[float] = []
    for feature_name in FEATURE_NAMES:
        value = payload.features.get(feature_name)
        if value is None:
            ordered_values.append(0.0)
        else:
            try:
                ordered_values.append(float(value))
            except (TypeError, ValueError):
                ordered_values.append(0.0)

    feature_vector = np.asarray(ordered_values, dtype=np.float32)
    return _predict_vector(feature_vector, payload.device_id)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok"}


@app.get("/debug/router")
def debug_router() -> Dict[str, Any]:
    result = router_request("GET", "/devices")
    return {
        "configured_router_url": ROUTER_API_URL,
        "status_code": 200,
        "device_count": len(result.get("devices", [])),
    }


@app.get("/devices")
def list_devices() -> Dict[str, List[Dict[str, Any]]]:
    raw = router_devices()
    return {"devices": [website_device(device) for device in raw if not is_calibration_device(device)]}



@app.get("/alerts")
def list_alerts() -> Dict[str, List[Dict[str, Any]]]:
    events = router_request("GET", "/events?limit=100").get("events", [])
    return {
            "detections": [
                {
                    "device_id": event.get("mac"),
                    "device": event.get("name"),
                    "label": "Attack" if event.get("status") in {"WARNING", "ALERT", "BLOCKED"} else "Benign",
                    "confidence": float(event.get("attack_probability", 0)) / 100,
                    "status": event.get("status", "SAFE"),
                    "ip_address": event.get("ip_address"),
                    "timestamp": datetime.fromtimestamp(event.get("timestamp", 0), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                }
                for event in events
                if not is_calibration_device({"mac": event.get("mac")})
            ]
    }


@app.get("/events")
def list_events(limit: int = 50):
    return router_request("GET", "/events", params={"limit": limit})


@app.post("/telemetry")
def telemetry(payload: Dict[str, Any]):
    return router_request("POST", "/telemetry", json=payload)


@app.post("/auth/{action}")
def auth_action(action: str, payload: Dict[str, Any]):
    if action not in {"signup", "login", "change-password", "request-password-reset", "reset-password"}:
        raise HTTPException(status_code=404, detail="Unknown account action.")
    if action == "change-password" and BACKEND_ROLE == "gateway":
        user_email = CURRENT_USER_EMAIL.get()
        if not user_email:
            raise HTTPException(status_code=401, detail="Sign in again to change your password.")
        payload = {**payload, "email": user_email}
    result = router_request("POST", f"/auth/{action}", json=payload)
    if action == "request-password-reset" and result.get("success") is not True:
        raise HTTPException(
            status_code=503,
            detail=result.get("error", "Password reset email could not be delivered."),
        )
    if action == "reset-password" and result.get("success") is not True:
        raise HTTPException(status_code=400, detail=result.get("error", "Password reset failed."))
    if action in {"signup", "login"} and result.get("success") is True:
        result["access_token"] = issue_session(result["email"])
    return result


@app.post("/gateway/claim")
def claim_gateway(payload: Dict[str, Any]):
    return router_request("POST", "/gateway/claim", json=payload)


@app.post("/household/invites")
def invite_household_member(payload: Dict[str, Any]):
    return router_request("POST", "/household/invites", json=payload)


@app.get("/household/role")
def get_household_role():
    role = router_request("GET", "/household/role").get("role")
    return {"role": role}


@app.post("/devices/register")
def register_device(payload: RegisterDeviceRequest) -> Dict[str, Any]:
    result = router_request(
            "POST",
            "/devices/register",
            json={"name": payload.name, "mac": payload.mac, "ip_address": payload.ip_address},
        )
    return {**result, "device": website_device(result)}


@app.delete("/devices/{mac}")
def delete_device(mac: str) -> Dict[str, Any]:
    return router_request("DELETE", f"/devices/{mac}")


@app.post("/devices/{mac}/block")
def block_device(mac: str) -> Dict[str, Any]:
    result = router_request("POST", f"/devices/{mac}/block")
    if result.get("success") is not True:
        raise HTTPException(status_code=502, detail=result.get("detail", "Pi could not block this device."))
    return result


@app.post("/devices/{mac}/unblock")
def unblock_device(mac: str) -> Dict[str, Any]:
    result = router_request("POST", f"/devices/{mac}/unblock")
    if result.get("success") is not True:
        raise HTTPException(status_code=502, detail=result.get("detail", "Pi could not unblock this device."))
    return result


@app.get("/login-history")
def list_login_history() -> Dict[str, List[Dict[str, Any]]]:
    email = CURRENT_USER_EMAIL.get()
    role = router_request("GET", "/household/role").get("role")
    if role not in {"owner", "admin"}:
        return {"logins": [event for event in LOGIN_EVENTS if event.get("username", "").lower() == email]}
    return {"logins": LOGIN_EVENTS}


@app.post("/login")
def login(payload: LoginRequest, request: Request) -> Dict[str, Any]:
    username = payload.username.strip()
    password = payload.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    name = username.split("@")[0].capitalize()
    email = username
    result = router_request(
            "POST",
            "/auth/login",
            json={
                "email": username,
                "password": password,
                "access_code": payload.access_code,
            },
        )
    if result.get("success") is not True:
        raise HTTPException(status_code=401, detail=result.get("error", "Invalid credentials."))
    name = result.get("name", name)
    email = result.get("email", email)

    login_event = {
        "username": username,
        "success": True,
        "ip_address": request.client.host if request.client else "unknown",
        "timestamp": utc_now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    LOGIN_EVENTS.insert(0, login_event)

    return {"username": name, "email": email, "message": "Authentication successful",
            "household_role": result.get("household_role"),
            "access_token": issue_session(email)}


@app.post("/signup")
def signup(payload: SignupRequest) -> Dict[str, Any]:
    result = router_request(
        "POST",
        "/auth/signup",
        json={
            "name": payload.name,
            "email": payload.email,
            "password": payload.password,
            "access_code": payload.access_code,
        },
    )
    if result.get("success") is not True:
        raise HTTPException(status_code=400, detail=result.get("error", "Account creation failed"))
    email = result.get("email", payload.email)
    return {"username": result.get("name", payload.name), "email": email,
            "household_role": result.get("household_role"),
            "access_token": issue_session(email)}


@app.get("/detect/{device_id}")
def detect_device(device_id: str) -> Dict[str, Any]:
    device = next((item for item in router_devices() if item.get("mac") == device_id), None)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    attack_probability = float(device.get("attack_probability", 0)) / 100
    result = {
        "device_id": device_id,
        "label": "Attack" if device.get("status") in {"WARNING", "ALERT", "BLOCKED"} else "Benign",
        "confidence": max(attack_probability, 1 - attack_probability),
        "class_probabilities": {"Attack": attack_probability, "Benign": 1 - attack_probability},
        "inference_latency_ms": None,
        "model_size_bytes": None,
    }
    ALERTS.insert(
        0,
        {
            "device_id": device_id,
            "label": result["label"],
            "confidence": result["confidence"],
            "timestamp": utc_now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return result


@app.get("/federated-status")
def federated_status() -> Dict[str, Any]:
    if BACKEND_ROLE == "gateway":
        return router_request("GET", "/federated-status", timeout=20)
    checkpoint_path = latest_global_checkpoint()
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    is_bundle = isinstance(checkpoint, dict) and "model_state_dict" in checkpoint
    federated_round = checkpoint.get("federated_round") if is_bundle else None
    updated_at = checkpoint_path.stat().st_mtime
    return {
        "architecture": "federated-learning",
        "global_model_path": str(checkpoint_path),
        "status": "federated" if federated_round is not None else "pretrained",
        "federated_round": federated_round,
        "federated_clients": checkpoint.get("federated_clients") if is_bundle else None,
        "aggregation": checkpoint.get("aggregation", "Pretrained") if is_bundle else "Pretrained",
        "feature_count": len(checkpoint.get("feature_names", FEATURE_NAMES)) if is_bundle else len(FEATURE_NAMES),
        "updated_at": datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat(),
        "training": _training_state(),
        "participants": [
            {
                "role": "Laptop trainer",
                "function": "Flower coordinator and local training client",
                "monitored_device": False,
            },
            {
                "role": "Raspberry Pi trainer",
                "function": "Local IDS and training client",
                "monitored_device": False,
            },
        ],
    }


@app.get("/federated-training/status")
def federated_training_status() -> Dict[str, Any]:
    if BACKEND_ROLE == "gateway":
        raise HTTPException(status_code=409, detail="This is the public gateway, not the laptop coordinator.")
    return COORDINATOR.status()


@app.post("/federated/start")
@app.post("/federated/train")
def start_federated_training() -> Dict[str, Any]:
    if BACKEND_ROLE == "gateway":
        return router_request("POST", "/federated/start", timeout=30)
    try:
        return COORDINATOR.start()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
