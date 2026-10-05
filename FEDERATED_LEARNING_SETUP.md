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

### Consumer cloud foundation (not activated)

The existing deployment below still uses one Pi household. The new optional
PostgreSQL foundation does not change login, device routing, or the Pi database.
Consumer multi-household registration and onboarding are not yet available.

Use a Supabase PostgreSQL **Session pooler** connection for the backend. Keep
the Data API disabled; Flutter and Vite must never receive database credentials.
Set `GHOST_CLOUD_DATABASE_URL` privately in the shell used for database setup.
URL-encode special characters in the password and require TLS. Never commit
the populated connection string or put it in a `VITE_` environment variable.

After installing the backend requirements, run from `Backend/Backend`:

```powershell
& "..\..\.venv\Scripts\python.exe" cloud_database.py init
& "..\..\.venv\Scripts\python.exe" cloud_database.py check
```

If the environment variable is absent, the CLI prompts for the connection URL
without echoing it. A URL containing `[YOUR-PASSWORD]` triggers a second hidden
password prompt; the CLI URL-encodes that password. Nothing is saved to disk.

Initialization is explicit, transactional, and versioned; it creates only the
private `caughtin4k` schema and does not import or delete existing Pi records.
The tables cover accounts, households, memberships, gateways, invitations, and
reset tokens. Gateway credentials and pairing codes are stored as hashes, not
plaintext. Row-level security has no client-access policies. The trusted
database owner connection bypasses RLS, so backend household authorization is
still required; RLS alone does not prove tenant isolation.

Do not switch the live deployment until cloud account APIs, household-scoped
routing, gateway connectivity, and migration of existing password hashes and
memberships are implemented and tested. Keep the Pi device/event history in
place. Live database validation is required in addition to local unit tests.

Development account endpoints can be enabled with
`GHOST_CLOUD_ACCOUNTS_ENABLED=true` and a separate stable
`GHOST_CLOUD_SESSION_SECRET` of at least 32 random characters. They are under
`/cloud/auth/signup`, `/cloud/auth/login`, `/cloud/auth/me`,
`/cloud/auth/logout-all`, and `/cloud/households`. Signup grants no membership.
Membership queries use the authenticated account UUID, not client identity
fields. Cloud tokens use a distinct namespace and cannot authorize the legacy
Pi API. Logout-all increments the persisted session version. Existing imported
PBKDF2 hashes can retain their iteration count; new hashes use 600,000.

Keep this flag **false on the public deployment**. These endpoints are a
development stage, not consumer-ready: cloud recovery, abuse rate limits,
email verification, gateway pairing, household UI, and the legacy data import
still need implementation. Pi reset email remains the live recovery path.

The consumer hardware direction is a preconfigured Pi with a unique setup QR.
The trusted `cloud_gateways.provision_gateway` function registers an unclaimed
gateway with independently generated machine and pairing secrets, storing only
SHA-256 hashes. The operator must specify a future pairing expiry. Its returned
machine credential is for protected Pi configuration only; the versioned QR
payload contains only gateway ID and pairing code. Provisioning is intentionally
not exposed as a public HTTP endpoint. Secure factory tooling, labels, and Pi
credential installation remain to be built.

In development cloud mode, `POST /cloud/gateways/pair` accepts `gateway_id`,
`pairing_code`, and `household_name`. It creates a separate household owned by
the authenticated account. A transaction locks the gateway, rejects invalid,
expired, consumed, or revoked pairing codes, and clears the pairing secret on
success. `GET /cloud/households/{household_id}/gateways` requires membership and
never returns credential hashes. This first pairing flow creates a new household;
adding another Pi to an existing household is not yet supported.

These APIs do not establish a Pi connection or migrate the existing installation.
Outbound gateway connectivity, QR scanning, and integration/concurrency tests
against PostgreSQL are still required before release.

Run the opt-in live account/pairing check from `Backend/Backend`:

```powershell
& "..\..\.venv\Scripts\python.exe" test_cloud_integration.py
```

It prompts privately for the database URL, creates uniquely identified test
accounts and gateways, checks two-household access separation, pairing-code
replay, competing claims, and session revocation, then deletes only the records
it created. It does not contact the existing Pi. A process interruption may
leave test records; do not interrupt it or treat mocked unit tests as proof of
live database isolation. This check is not a full production security review.

Cloud invitations are available in development mode through
`POST /cloud/households/{household_id}/invites` (`email`, `role`) and
`POST /cloud/household-invites/accept` (`invite_code`). Owners can invite admins
or members; admins can invite members only. Invitations expire after 24 hours
and are bound to the recipient account's stored email. Acceptance checks the
inviter's current permissions, locks and consumes the invitation transactionally,
and never overwrites an existing membership. The creator receives the code
once; email delivery and consumer sharing UI are not implemented for cloud
invitations. The live test also checks wrong-recipient refusal, invitation replay,
and member invitation restrictions. Verified cloud email ownership and abuse
controls are still needed before these endpoints can be publicly enabled.

Schema version 2 adds bounded last-known gateway snapshots. Run
`cloud_database.py init` again to apply the additive migration; version 1
accounts and memberships are preserved. In development mode,
`PUT /cloud/gateways/{gateway_id}/snapshot` requires the unique Pi machine
credential in `X-Gateway-Credential`, not a user session. Only paired, non-revoked
gateways can upload. The API accepts at most 500 devices and 100 recent alerts
plus model metadata; it rejects extra fields such as raw packets/training rows.
This is a latest snapshot, not a permanent alert archive.

`GET /cloud/households/{household_id}/gateways/{gateway_id}/snapshot` requires
account membership in that exact household. `snapshot_available=false` means
no data has arrived; it is not an empty-device success. `recent_contact` reflects
server-observed gateway contact within 90 seconds, while `data_stale` reflects
the observation timestamp. Neither field proves continuous connectivity.
Old/replayed snapshots cannot overwrite newer observations. Snapshots remain
readable when a gateway is offline, with explicit freshness timestamps.
Command delivery, consumer UI, and a retention policy are not yet implemented.
Keep public cloud mode disabled.

The opt-in `cloud_uploader.py` runs as a separate Pi process using only Python's
standard library. It reads the token-protected loopback `/cloud-agent/snapshot`
export, then uploads metadata over HTTPS every 30 seconds. Both source export
and uploader require `GHOST_CLOUD_UPLOAD_ENABLED=true`. Additional private
settings are `GHOST_CLOUD_API_URL` (HTTPS origin), `GHOST_CLOUD_GATEWAY_ID`, and
`GHOST_CLOUD_GATEWAY_CREDENTIAL` (the separately provisioned machine secret).
The uploader never receives the cloud database password or a user session.
No proxy-environment settings or redirects can forward its credentials elsewhere.

Temporary connectivity failures use bounded exponential retries with jitter.
Invalid credentials/configuration stop the uploader with an explicit error.
The existing router token goes only to loopback; the cloud credential goes only
to the configured cloud origin. Model availability reflects the router's loaded
model, not merely an existing checkpoint file; this upload does not claim or
trigger a federated round. Devices and alerts express attack probability as
percentages (0–100) and preserve SAFE/WARNING/ALERT/BLOCKED statuses.
Capture, local training CSVs, Flower ports/processes,
and inference checkpoints are unchanged. No uploader service is deployed yet.
End-to-end Pi upload verification, provisioning tooling, command delivery, and
consumer UI remain outstanding. Keep existing Ngrok monitoring until cutover.

`provision_cloud_gateway.py` is trusted operator tooling for **new** gateways,
not an import tool for the existing claimed Pi. It prompts privately for the
database URL, checks the schema, and requires a name, explicit timezone-aware
pairing expiry, HTTPS cloud origin, and a new absolute output directory outside
the repository. On Windows it removes inherited directory permissions and grants
the current Windows SID access; on POSIX the directory is mode 0700 and files
are mode 0600. Files are created exclusively, never overwritten.

The bundle contains `gateway.env` (machine credential; uploader disabled),
`pairing-label.json` (customer setup secret and gateway ID), and
`pairing-expiry.txt`. These are sensitive operator outputs: do not upload them
to GitHub, chat, or third-party QR generators. The JSON is QR content, not yet a
rendered QR image. Registration commits only after the files are written.
On failure, do not use partial bundles; ambiguous database commit failures need
operator reconciliation. Do not run this on the existing Pi yet: migration must
preserve its owner, members, password hashes, history, and FL checkpoint.

`migrate_pi_household.py --backup <private-sqlite-backup>` inspects a consistent
Pi backup read-only, validates integrity and owner/member relationships, and
prints counts only. It never creates a missing SQLite file. Explicit `--apply`
also requires `--name`, `--cloud-url`, and a new private `--output` folder, then
prompts for the cloud database URL. Import preserves PBKDF2 hashes/salts with
the legacy 100,000 iteration count, account timestamps, and household roles.
Existing non-member accounts are imported without household access.

The import transaction refuses all existing cloud email conflicts, including
a second import of the same backup; no account is silently merged or overwritten.
It creates an already-owned gateway with no customer pairing secret and saves
its machine configuration with uploads disabled. Pending invitations and reset
codes are intentionally not imported; reissue them after cutover. Device/event
history, datasets, checkpoints, and Flower processes stay on the Pi.
Source backups and output credentials must remain private and outside Git.
Import does not switch live login or routing. A backup can become stale if users
change passwords or memberships afterward; final migration requires a coordinated
write freeze/fresh backup and live imported-account verification before cutover.

After importing, run `verify_cloud_import.py --bundle <private-output-folder>`.
It prompts privately for the database URL, existing owner email, and existing
account password; it performs only reads and checks password compatibility,
owner membership in the imported household, and the expected non-revoked
gateway. It does not install the gateway credential or enable cloud uploads.
Never paste account passwords or generated machine configuration into chat.

Use a separate Render staging service for development cloud APIs, not the live
gateway. Enabling cloud mode also requires a separate
`GHOST_CLOUD_STAGING_TOKEN` of at least 32 random characters. Every `/cloud/`
request must include it in `X-Cloud-Staging-Token` in addition to the user or
machine credentials required by that route. Missing/invalid staging access
fails closed before route execution. This operator-only gate is temporary and
must not be embedded in a public app/website or treated as household authorization.
The current uploader does not yet send the staging header. Do not install or
enable it until the private staging test workflow is wired. Free-tier staging
sleeping is not evidence of production availability.

For the separate cloud staging service, use root `Backend/Backend`, build
`pip install -r requirements_cloud.txt`, and start
`uvicorn cloud_staging_app:app --host 0.0.0.0 --port $PORT`.
Set health path `/health`. This entry point does not import Torch, load an
inference checkpoint, or expose legacy Pi/coordinator routes. Its dependencies
exclude GPU/CUDA packages. The Pi and laptop continue using their existing
requirements and entry points; real federated training is not removed.
Staging requires the database URL, cloud session secret, and staging token.
Its public health check proves process readiness, not database connectivity.

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
