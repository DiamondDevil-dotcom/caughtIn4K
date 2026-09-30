from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_devices():
    response = client.get("/devices")
    assert response.status_code == 200
    data = response.json()
    assert "devices" in data
    assert len(data["devices"]) >= 1


def test_login():
    response = client.post("/login", json={"username": "demo", "password": "pass123"})
    assert response.status_code == 200
    assert response.json()["username"] == "demo"


def test_detect_device():
    response = client.get("/detect/iot-101")
    assert response.status_code == 200
    data = response.json()
    assert "label" in data
    assert "confidence" in data
    assert "class_probabilities" in data
    assert data["label"] in {"Attack", "Benign"}
    assert set(data["class_probabilities"]) >= {"Attack", "Benign"}


def test_federated_status():
    response = client.get("/federated-status")
    assert response.status_code == 200
    data = response.json()
    assert data["architecture"] == "federated-learning"
    assert "global_model_path" in data
    assert data["aggregation"] in {"FedAvg", "Pretrained"}
    assert data["feature_count"] == 14
    assert [participant["role"] for participant in data["participants"]] == [
        "Laptop trainer",
        "Raspberry Pi trainer",
    ]
    assert all(not participant["monitored_device"] for participant in data["participants"])


def test_live_predict_from_device_payload():
    payload = {
        "device_id": "iot-101",
        "features": {
            "Header_Length": 100,
            "syn_flag_number": 1,
            "rst_flag_number": 0,
            "HTTP": 0,
            "ARP": 1,
            "ICMP": 0,
            "LLC": 2,
            "Tot sum": 45.1,
            "Min": 2.0,
            "IAT": 8.5,
            "Number": 12,
            "Magnitue": 0.78,
            "Covariance": 0.31,
            "Weight": 0.42,
        },
    }
    response = client.post("/live-predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["device_id"] == "iot-101"
    assert data["label"] in {"Attack", "Benign"}
    assert 0.0 <= data["confidence"] <= 1.0
