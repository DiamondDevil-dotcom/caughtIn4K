# Raspberry Pi direct HTTP gateway

This bridge sends feature JSON directly from a Raspberry Pi or gateway to the backend inference API.

## 1) Start the backend

```powershell
cd "E:\Intrusion_Detection\Backend"
.\venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```

## 2) Configure the gateway

Copy the example environment file and update the backend address:

```powershell
cd "E:\Intrusion_Detection\Backend"
copy .env.example .env
```

Then edit `.env` and set a real backend IP, for example:

```env
BACKEND_URL=http://192.168.1.30:8000/live-predict
DEVICE_ID=rpi-gateway-01
SEND_INTERVAL_SECONDS=5
```

## 3) Run the bridge on the Raspberry Pi

```bash
python3 raspberrypi_gateway.py
```

## 4) Example payload the gateway sends

```json
{
  "device_id": "rpi-gateway-01",
  "features": {
    "Header_Length": 120,
    "syn_flag_number": 1,
    "rst_flag_number": 0,
    "HTTP": 0,
    "ARP": 1,
    "ICMP": 0,
    "LLC": 2,
    "Tot sum": 48,
    "Min": 2,
    "IAT": 9,
    "Number": 13,
    "Magnitue": 0.8,
    "Covariance": 0.33,
    "Weight": 0.45
  }
}
```

This route is already supported by the backend at `/live-predict`.
