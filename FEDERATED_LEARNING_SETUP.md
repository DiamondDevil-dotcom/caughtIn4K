# Laptop + Raspberry Pi federated learning

This setup uses the laptop as the Flower FedAvg coordinator and as one local
training participant. The Raspberry Pi is the second participant. The Fold8
demo app sends labeled feature examples to the Pi; the Pi stores and trains on
those examples locally. Only model weights and sample counts are sent to the
laptop for aggregation. Fold8 examples are not uploaded to the laptop.

This is federated optimization, not a complete privacy guarantee. FedAvg does
not encrypt model updates or prevent every inference about training data. The
Pi's labeled CSV remains on the Pi unless someone copies it manually.

## Sentra connection modes

Both Sentra and the website use `https://caughtin4k.onrender.com` as their one
public gateway. Render proxies devices, event history, account operations,
telemetry, Pi model status, and training requests to the Pi's Ngrok tunnel.
The phone/browser can use Jio, another Wi-Fi, or any internet connection; only
the laptop training participant needs access to the Pi's local network.

Configure these variables in Render's service environment and redeploy:

```env
GHOST_BACKEND_ROLE=gateway
ROUTER_API_URL=https://stimuli-clubhouse-frozen.ngrok-free.dev
GHOST_SESSION_SECRET=<long-random-secret>
GHOST_ROUTER_TOKEN=<another-long-random-secret>
```

Generate secrets privately; do not commit them. An email allowlist no longer
grants device access by itself. Login verifies the account password and
issues a signed 12-hour session; the Pi checks the signed-in identity against
household membership on every protected request. Set a stable session secret
so Render restarts do not invalidate all sessions. New accounts need either
the one-time gateway setup code or an invitation created by a household owner
or admin.

On the Pi, set the same `GHOST_ROUTER_TOKEN` before starting the router agent
on port 8001 and the Ngrok tunnel. This prevents direct anonymous tunnel access.
Set `GHOST_LAPTOP_API_URL=http://<LAPTOP_WIFI_IP>:8000`. Model status comes from
`GHOST_FL_PI_MODEL`, defaulting to `ghost1d_gru_fedavg_improved.pth` beside
`router_ids_agent.py`; a valid inference bundle must exist there.

If the Pi runs `caughtin4k-router.service`, put these values in the root-owned
`/etc/caughtin4k/router.env` (permissions `0600`) and restart that service.
Set `GHOST_GATEWAY_PAIRING_CODE` to a long, random, one-time code and share it
only with the household owner. After the owner claims the gateway, other
accounts need an invitation code; invitations are tied to an email and expire
after 24 hours. Existing Pi devices and events are assigned to the household
when it is first claimed. The Pi automatically includes newly detected devices
in that same household. Members can monitor and respond to devices; only owners
and admins can register/remove devices or start federated training. An owner
can invite admins; admins can invite members.

The laptop's `/federated/start-client` and `/federated/stop-client` requests
are private machine-to-machine calls authenticated by `GHOST_ROUTER_TOKEN`;
they do not require a household user session. Render does not expose these
routes. The user-facing training endpoint still requires owner/admin access.

For password-reset email, configure the Pi's SMTP settings in the same
root-owned environment file:

```env
GHOST_SMTP_HOST=smtp.example.com
GHOST_SMTP_PORT=587
GHOST_SMTP_USERNAME=<smtp-account>
GHOST_SMTP_PASSWORD=<smtp-app-password>
GHOST_SMTP_FROM=<verified-sender-address>
GHOST_SMTP_SSL=false
```

Port 587 uses STARTTLS. For an SMTP provider using implicit TLS on port 465,
set `GHOST_SMTP_SSL=true`. Use the provider's app password/API credential,
not a personal mailbox password. No secret belongs in source control. The
Pi's existing `Database/email.env` loader is also supported, but the service
environment file is preferred.

The setup code must be present on the Pi before first claim. Existing owner
accounts can claim from Sentra's **Settings → Claim gateway**. New installations
can create the owner account with that code; subsequent sign-ups must use a
household invitation code. Existing accounts invited by the owner enter their
invitation code at sign-in. Sign out on a shared phone before switching
accounts; cached device/event data is cleared.

Exporting variables in an SSH shell does not change an already running service.
The updated setup script loads this file. For an existing service, add
`EnvironmentFile=/etc/caughtin4k/router.env` in its `[Service]` override and run
`systemctl daemon-reload` before restarting.

The model folder is now tracked as ordinary source, not as the former broken
Git submodule. Datasets, SQLite accounts, logs, and checkpoints remain ignored.
Updating source must preserve the Pi's existing account database and checkpoint;
a fresh clone alone does not include either of them.

On the laptop, set `GHOST_BACKEND_ROLE=coordinator`,
`ROUTER_API_URL=http://192.168.50.1:8001`, the same `GHOST_ROUTER_TOKEN`, and
`GHOST_FL_ADVERTISE_ADDRESS=<LAPTOP_WIFI_IP>:8080`. Run the backend from its
folder with a valid Python environment containing both backend dependencies
and `requirements_federated.txt`:

```powershell
Set-Location ".\Backend\Backend"
# Set the role, Pi URL, shared token and advertised address in this shell first.
& "..\..\.venv\Scripts\python.exe" -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Allow ports 8000 and 8080 only on the laptop's private Pi network in Windows
Firewall. Do not expose those laptop ports to the public internet.

If another application occupies Flower port 8080, use a free port such as
8081 in `GHOST_FL_ADVERTISE_ADDRESS=<LAPTOP_WIFI_IP>:8081` and allow that port
instead. The coordinator passes the selected port to the server and both
clients automatically. Restart the coordinator after changing its environment.
Use only the managed Pi service: launching the router manually does not load
the service's private token and laptop URL environment file.

Select **Shared Render Gateway** in Sentra settings and sign in again. Existing
saved Pi URLs are not overwritten automatically. Set the website's Vercel
environment variable `VITE_API_URL=https://caughtin4k.onrender.com` and rebuild.
If the Ngrok URL changes, update only Render's `ROUTER_API_URL`.

The **Update global model** button starts the real Flower server and laptop
client on the laptop, then the Pi client. It requires both attack and benign
samples on the Pi, and the laptop's local training CSV. Completion is reported
only after both clients finish all aggregation/evaluation rounds. The Pi client
saves the global checkpoint locally. There is no simulated training fallback.
The Fold8 demo sender also uses the Render URL: sign in with an allowed Pi
owner account before sending labeled examples. Never embed the private
Render-to-Pi token in either mobile app.
The laptop coordinator must be online for updates, but devices and Pi model
status remain available when it is offline; training is reported unavailable.
Do not simultaneously start the manual Flower processes below when using the
button. Missing prerequisites and client failures appear as errors.

The Pi router and tunnel must stay online, and the Pi needs internet uplink.
A Pi hotspot with no upstream internet cannot maintain a public Ngrok tunnel.
A sleeping Render service can take time to wake; client reads allow 60 seconds.
The gateway and shared-token protection are not a full production security
assessment: use HTTPS, protect environment secrets, and keep software patched.

## Deploying to an existing Pi service

The local APK builds and tests do not deploy anything to Render or the Pi.
Publish the changed source to the connected repository and redeploy Render and
Vercel separately. Include the new backend helper modules and the now-tracked
Pi source folder. Do not publish virtual environments, private environment
files, databases, or datasets.

If SSH uses a password, run the following yourself in your local terminal.
Type passwords only into the SSH/SCP prompts, never into chat. From the
Windows project root:

```powershell
$model = '.\Ghost-1D GRU Model with EANGO on Full Dataset'
$files = @(
  'router_ids_agent.py', 'federated_server.py', 'federated_client.py',
  'model.py', 'trainer.py', 'utils.py', 'storage.py', 'network_control.py',
  'wifi_client.py', 'selected_features.json',
  'requirements_router.txt', 'requirements_federated.txt'
)
$sources = $files | ForEach-Object { Join-Path $model $_ }
ssh pi@caughtin4k-pi-1.local 'mkdir -p ~/caughtin4k-update'
scp @sources pi@caughtin4k-pi-1.local:caughtin4k-update/
ssh pi@caughtin4k-pi-1.local
```

On the Pi, find the existing installation rather than guessing its path:

```bash
systemctl show caughtin4k-router.service -p WorkingDirectory -p ExecStart
```

Back up the existing source files, then copy the uploaded source files into
that service's working directory so the router and training client run the
same tested version. Keep the existing checkpoint, database, and training
datasets in place; none are included in the upload above. Install
`requirements_router.txt` using the same Python executable shown in
`ExecStart`, not an unrelated system Python.

Create `/etc/caughtin4k/router.env` as a root-owned file with permissions
`0600`. Enter the matching private token and laptop URL there:

```env
GHOST_ROUTER_TOKEN=<same-private-value-as-Render-and-laptop>
GHOST_LAPTOP_API_URL=http://<LAPTOP_WIFI_IP>:8000
```

Run `sudo systemctl edit caughtin4k-router.service` and add:

```ini
[Service]
EnvironmentFile=/etc/caughtin4k/router.env
```

Then run `sudo systemctl daemon-reload` and
`sudo systemctl restart caughtin4k-router.service`. Check its active status and
logs locally. Do not rerun the hotspot setup script on an already configured
Pi merely to update the API. Keep Ngrok forwarding to Pi port 8001.

After configuring/redeploying Render, install the rebuilt Sentra APK, select
**Shared Render Gateway**, and sign in. Turn off phone Wi-Fi and verify devices
and Pi model status over Jio. Start the laptop coordinator before testing the
training button; training intentionally updates the Pi checkpoint.

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

3. On the Pi, install the packages in `requirements_router.txt` into the
   Python environment used by the router agent. Keep the Pi's model folder,
   `federated_client.py`, `model.py`, `trainer.py`, and `utils.py` together.
   This includes the web API and packet capture dependencies in addition to
   Flower; the laptop only needs backend plus federated requirements.
4. Configure the Pi client to write its labeled examples somewhere writable
   by the router service. For example, set `GHOST_FL_SAMPLES` to
   `/var/lib/caughtin4k/federated_samples.csv` and `GHOST_FL_PI_MODEL` to the
   checkpoint path used by the Pi service.

## Alternative: manually start a training session

These steps are an alternative to the app's managed training button. Do not
use both at once. The recommended route is to start the laptop coordinator
above and use **Update global model**.

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
4. Open the updated Fold8 demo app, use `https://caughtin4k.onrender.com`,
   and sign in with an allowed owner account. Send both normal and attack
   examples. Do not use the private Pi URL with the updated sender. The Pi
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
  inference checkpoint. The public website displays the Pi's checkpoint
  metadata through Render, not a separate Render training model.
- During Flower evaluation, the Pi client also atomically writes the received
  global model to `ghost1d_gru_fedavg_improved.pth`. The running Pi detector
  checks for and reloads that updated checkpoint.
- The legacy `/live-predict` backend endpoint loads its local model when it
  starts; restart that backend to refresh that endpoint. This is not needed
  for the app/website's proxied Pi model status.
- The model's feature scaling values are shared with clients so both train on
  inputs in the same feature space. This exposes preprocessing statistics but
  not the clients' feature rows.

If either client is disconnected, FedAvg waits for both. A training round
should be described as completed only after the server logs aggregation and a
round checkpoint is written. Merely sending Fold8 telemetry or seeing a
prediction is inference/demo traffic, not a federated round.
