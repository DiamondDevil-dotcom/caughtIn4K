# Laptop + Raspberry Pi federated learning

This setup uses the laptop as the Flower FedAvg coordinator and as one local
training participant. The Raspberry Pi is the second participant. The Fold8
demo app sends labeled feature examples to the Pi; the Pi stores and trains on
those examples locally. Only model weights and sample counts are sent to the
laptop for aggregation. Fold8 examples are not uploaded to the laptop.

This is federated optimization, not a complete privacy guarantee. FedAvg does
not encrypt model updates or prevent every inference about training data. The
Pi's labeled CSV remains on the Pi unless someone copies it manually.

## One-time setup

1. Use the same project version on the laptop and Pi. The model feature order
   must match `selected_features.json` in the model folder. When installing the
   Pi gateway, set `GHOST_ROUTER_EXCLUDED_MACS` to the laptop's Wi-Fi MAC so it
   remains an FL participant without appearing as a monitored IoT device.
2. On the laptop, use `Ghost_FL_Flower/venv` if it is valid. Install Flower in
   the Python environment used for this project if needed:

   ```powershell
   & ".\Ghost_FL_Flower\venv\Scripts\python.exe" -m pip install -r ".\Ghost-1D GRU Model with EANGO on Full Dataset\requirements_federated.txt"
   ```

3. On the Pi, install the packages in `requirements_federated.txt` into the
   Python environment used by the router agent. Keep the Pi's model folder,
   `federated_client.py`, `model.py`, `trainer.py`, and `utils.py` together.
4. Configure the Pi client to write its labeled examples somewhere writable
   by the router service. For example, set `GHOST_FL_SAMPLES` to
   `/var/lib/caughtin4k/federated_samples.csv` and `GHOST_FL_PI_MODEL` to the
   checkpoint path used by the Pi service.

## Start a training session

1. Connect the laptop to the Pi access point and get the laptop's Wi-Fi IPv4
   address from `ipconfig`. The Pi client must be able to reach that address.
2. On the laptop, open PowerShell in the project root and start the Flower
   server:

   ```powershell
   & ".\Ghost_FL_Flower\venv\Scripts\python.exe" ".\Ghost-1D GRU Model with EANGO on Full Dataset\federated_server.py"
   ```

   It listens on all laptop network interfaces at port `8080` and waits for
   both clients. If Windows Firewall asks, allow Python on the Pi's private
   network. Otherwise create an inbound TCP rule for port 8080 on that network.
3. In a second laptop PowerShell window, start the laptop's local trainer:

   ```powershell
   & ".\Ghost_FL_Flower\venv\Scripts\python.exe" ".\Ghost-1D GRU Model with EANGO on Full Dataset\federated_client.py" --role laptop
   ```

   Its private training data comes from
   `Ghost-1D GRU Model with EANGO on Full Dataset/CICIOT23/train/train.csv`.
   By default, it uses a reproducible 0.3% sample of the large CSV; change
   `GHOST_FL_LAPTOP_SAMPLE_FRACTION` to use another fraction.
4. Open the Fold8 demo app and set its router API URL to the Pi API, normally
   `http://192.168.50.1:8001` when installed with `router_setup/setup_gateway.sh`.
   Send both normal and attack examples. The Pi
   stores examples in `federated_samples.csv` under its configured data folder.
   The Pi client needs at least one example of each label before it can train.
5. On the Pi, start its Flower client, replacing the example IP with the
   laptop's address on the Pi Wi-Fi:

   ```bash
   GHOST_FL_SERVER_ADDRESS="<LAPTOP_WIFI_IP>:8080" python3 federated_client.py --role pi
   ```

   The server begins rounds after both laptop and Pi clients connect. Keep the
   server and both clients running until the configured rounds finish.

## What updates where

- The Pi saves Fold8-labeled feature rows locally. The Flower Pi client loads
  and trains on them on each round.
- The laptop client trains on its local CICIoT23 training file.
- FedAvg combines both clients' parameter updates weighted by local row count.
- Each global round is saved to `Ghost_FL_Flower/saved_models/` as a full
  inference checkpoint. Round 10 is the website backend's preferred model.
- During Flower evaluation, the Pi client also atomically writes the received
  global model to `ghost1d_gru_fedavg_improved.pth`. The running Pi detector
  checks for and reloads that updated checkpoint.
- The website backend loads its model when it starts. Restart the laptop
  backend after round 10 completes if it was already running.
- The model's feature scaling values are shared with clients so both train on
  inputs in the same feature space. This exposes preprocessing statistics but
  not the clients' feature rows.

If either client is disconnected, FedAvg waits for both. A training round
should be described as completed only after the server logs aggregation and a
round checkpoint is written. Merely sending Fold8 telemetry or seeing a
prediction is inference/demo traffic, not a federated round.
