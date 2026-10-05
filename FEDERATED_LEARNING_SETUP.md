# Laptop + Raspberry Pi federated learning

This setup uses the laptop as the Flower FedAvg coordinator and as one local
training participant. The Raspberry Pi is the second participant. The Fold8
demo app sends labeled feature examples to the Pi; the Pi stores and trains on
those examples locally. Only model weights and sample counts are sent to the
laptop for aggregation. Fold8 examples are not uploaded to the laptop.

This is federated optimization, not a complete privacy guarantee. FedAvg does
not encrypt model updates or prevent every inference about training data. The
Pi's labeled CSV remains on the Pi unless someone copies it manually.

## Customer app and website rollout

IoT devices connect to the Pi Wi-Fi access point. The Pi captures traffic,
runs detection and applies real firewall rules. Customers sign in to the shared
service from any internet connection; they do not enter a server URL, operator
token, or connection mode. New users verify email and pair the Pi using its
one-time setup QR label, or accept a household invitation. One home opens
automatically; **Your home / Manage homes** allows selecting or adding homes.

Building locally does not deploy the customer app, website, backend, or Pi
worker. Use the following deliberate rollout for a new installation or update:

1. Apply schema version **7** with the private `cloud_database.py init` command
   below, then run `cloud_database.py check`. This is additive: accounts,
   password hashes, memberships, gateways and Pi data are retained. Existing
   accounts are **not** falsely marked email-verified; they confirm their email
   once before accessing a home through the public customer service.
2. Keep the existing private database URL and session signing secret. Configure
   the backend privately with `GHOST_CLOUD_CUSTOMER_ENABLED=true`,
   `GHOST_SMTP_HOST`, `GHOST_SMTP_PORT` (`587` STARTTLS or `465` TLS),
   `GHOST_SMTP_USERNAME`, `GHOST_SMTP_PASSWORD`, and `GHOST_SMTP_FROM`.
   Use an app password where required by the email provider. Never put these
   credentials in chat, Git, the app, or `VITE_` variables.
   Render Free blocks outbound SMTP ports 25, 465 and 587. Gmail SMTP requires
   a paid Render instance; otherwise use a supported HTTPS mail integration.
3. Set `GHOST_CLOUD_WEB_ORIGINS` to the exact deployed HTTPS website origin
   (comma-separated if there are several). No wildcard, path or trailing slash
   is accepted. An empty list permits mobile access but not browser access.
   Preserve the **original** live gateway; change only the separate service
   after authorizing and deploying the customer source.
4. Keep build command `pip install -r requirements_cloud.txt`; switch the
   separate service start command to
   `uvicorn cloud_customer_app:app --host 0.0.0.0 --port $PORT`.
   Health path is `/health`. This public entrypoint does not require an operator
   staging token. User bearer sessions and Pi machine credentials are still
   mandatory on their respective protected routes. The health endpoint only
   proves process readiness, not database, email or Pi connectivity.
5. Verify real login, delivery of verification/reset email, home access and
   fresh Pi snapshots before installing the new APK or publishing the website.
   Build Flutter with `--dart-define=CLOUD_API_URL=<customer-https-origin>`,
   and Vite with `VITE_CLOUD_API_URL=<customer-https-origin>`. Both defaults
   currently point to `https://caughtin4k-1.onrender.com`, which must first run
   the customer entrypoint. Origins are build configuration, never customer
   settings. Rebuild the website; do not publish stale tracked build output.
6. Keep the working Pi uploader/control services and raw datasets/models in
   place. Their optional old staging header is ignored by the customer
   entrypoint; the gateway credential remains required. Do not restart capture
   or active FL training just to change the web service.
7. On a nonessential Pi Wi-Fi client, verify **both** clients' Block/Unblock
   buttons over a different internet connection. Keep the SSH/training laptop
   available for restoration and disable cellular fallback when measuring the
   target client's Wi-Fi connectivity.

Only household owners/admins can submit controls. Stale/offline data disables
buttons. Queued/delivered never means blocked; only a Pi `succeeded` result with
`applied` confirms enforcement. Unconfirmed commands retain their UUID for
read-only recovery without replay: secure storage on the phone, account-scoped
session storage in the browser. Closing a browser session can discard browser
recovery state; inspect the Pi/device before attempting another command.
Successful password changes/reset invalidate older sessions.

Authentication and API limits use shared PostgreSQL counters and fail closed
when that storage is unavailable. They use the ASGI client's address, **not**
arbitrary client-supplied forwarding headers. Before public deployment verify
the hosting proxy configuration preserves the real client address with trusted
proxy handling; otherwise multiple customers may share a limit. Do not enable
unrestricted forwarded-header trust on an internet-accessible backend.

Local checks: backend customer/household/command tests, `flutter test`,
`flutter analyze`, `flutter build apk --debug`, and website
`node --test src/cloud-client.test.js` followed by `npm run build`.
Mobile tabs switch directly with a short fade instead of paging through
intermediate screens. Visited tabs retain their state and scroll position;
hidden tab animations pause, while live monitoring providers keep polling.
System reduced-motion settings disable the tab/navigation animations.
Judge device animation performance using a profile or release APK, not debug.
Account signup validates email syntax and field lengths before submission.
Known account-validation errors are shown directly; unexpected server details
are not displayed, and signup failures do not suggest device-control recovery.
For opt-in live schema/email-token/session-revocation checks run
`test_cloud_integration.py` privately after schema 5 is applied; email delivery
is mocked in that suite and must also be checked with an actual account.
The live suite creates and deletes only its uniquely named test records.

Customer model metadata shows the Pi checkpoint's availability, not proof of
a completed FL round. Genuine laptop/Pi Flower training remains operational
through the existing coordinator workflow below, not the customer service.
Production availability and email delivery must be tested separately;
a sleeping free-tier instance is not an always-available smart-home service.

### Restoring remote Add/Remove controls

Schema 5 expands the existing outbound queue with bounded `register` and
`remove` actions. Registration accepts only a device name, MAC address and
optional IPv4 address; it is not a shell-command or arbitrary-payload channel.
Removal clears firewall enforcement before deleting the record and its
detection history. It does not disconnect Wi-Fi permanently: a removed device
can still use the access point but is hidden from monitoring until re-added.

Roll out in this order:

1. Apply and check schema 5 **before** deploying the updated command backend.
   Even Block/Unblock inserts now reference its additive columns. Keep
   `GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED` absent or `false` in the cloud.
2. Back up and update both `router_ids_agent.py` and `cloud_control_agent.py`
   in the existing Pi service directory. Preserve databases, datasets,
   checkpoints, environment secrets and network configuration.
3. Check both files with the Pi service's Python interpreter. Confirm no
   federated training is running before restarting the router. Enable
   `GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED=true` in the router environment,
   restart the router and control worker, and verify both are active. Retain
   the existing loopback/token restrictions and cloud-control flag.
4. Deploy the backend; verify fresh snapshots and existing Block/Unblock.
   Only after both Pi components are updated, enable
   `GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED=true` on the cloud service.
   The snapshot capability comes from this rollout flag, not automatic
   machine-version attestation, so never enable it ahead of the Pi update.
5. Build/install the updated consumer app and deploy the rebuilt website.
   Owners/admins get Add/Remove; members remain read-only. Use a nonessential
   test device to verify Add, Remove, re-add and Block/Unblock from each
   deployed client. Do not use the controller, uplink, or FL laptop as targets.

Clients wait for the Pi's applied acknowledgement. Old snapshots must not
restore a removed device or contradict a confirmed Block/Unblock button.
An added device may take up to 30 seconds to appear in the next upload.
On an unknown outcome, check the saved command instead of submitting again.
The dashboard reports Devices, Threats and Blocked separately; a manual block
does not by itself prove an attack, and stale/empty data is not "Protected".

The demo sender remains on the original gateway's `/auth/login` and
`/telemetry` routes, not the customer service. Its Pi account password is not
synchronized with a later cloud password reset. A timeout is a connectivity
failure, not an invalid-password response: check the original gateway and
Pi tunnel, then retry only after connectivity returns. A health response
alone does not prove login forwarding; validate the actual login round-trip.

### Low-latency monitoring and brief warnings

The uploader defaults to a 2-second cadence, configurable with
`GHOST_CLOUD_UPLOAD_INTERVAL` (2-60 seconds). The active mobile Devices/Home
provider and website poll every 2 seconds, fetching all devices together rather
than making one request per device. Requests never overlap within a poller.
Successful uploads subtract request duration from the next wait; failures still
back off. Network/hosting delays remain possible: this is not a hard real-time
guarantee. Under normal connectivity, two polling stages add up to roughly
4 seconds plus request latency instead of the old 30+15 second waits.

Home and Devices also show **Recent WARNING** from real Pi event history for
60 seconds, independently per MAC. This preserves brief warnings even if the
current state has already become BLOCKED or SAFE. It does not relabel the
current state, delay firewall enforcement, or alter model thresholds. Stale
snapshots and removed devices do not show these banners; Activity retains the
actual transition history. Validate using two registered devices sending
samples concurrently and measure sender acknowledgement-to-display latency.

Deploy the updated `cloud_uploader.py` to the Pi and restart only the uploader
service after syntax validation; no router/training restart is needed.
Rebuild/install the mobile app and publish the rebuilt website. The backend
snapshot contract and database schema are unchanged.

Activity polls every 2 seconds as well. While the app is running, fresh Pi
WARNING/ATTACK/ALERT/BLOCKED events generate Android notifications once per
event, independently per device, including transitions missed between snapshots.
Old events are not replayed on login. The Settings notification toggle applies
to cloud events; permission/plugin failures are shown on Home and Devices.
Closed-app/locked-phone delivery uses the separately enabled Firebase push
outbox below; local polling alone does not guarantee background delivery.

### Android background notification rollout

1. Download `google-services.json` from Firebase to
   `Sentra/android/app/google-services.json` as local Android client
   configuration (ignored by Git). Never put a Firebase service-account private key in the app
   or Git. Store that private key as the customer Render service's secret file
   `firebase-service-account.json`.
2. Apply additive schema **6** using `cloud_database.py init`, then `check`,
   before enabling push. Deploy the cloud requirements and source changes.
3. Set `GHOST_CLOUD_PUSH_ENABLED=true` on the customer backend.
   `GHOST_FIREBASE_CREDENTIALS_FILE` defaults to
   `/etc/secrets/firebase-service-account.json`. Startup validates the schema
   and credential; an invalid configuration fails explicitly. The Firebase
   service account must belong to the Android client's project, and the
   Firebase Cloud Messaging API must be enabled.
4. Rebuild/install the Android app, allow notifications, and sign in with a
   verified account. Registration is automatic; Settings controls both local
   and remote alerts. Background setup/removal failures appear in an app-wide
   error banner with Retry, without discarding a working customer session.
5. Send a genuine WARNING and BLOCKED transition with the app foregrounded,
   then repeat with the phone locked and with the app swiped away. Confirm
   notifications on each device and that an unrelated verified account with
   no membership receives none. Do not declare push verified until these
   physical checks pass.

Push recipients are resolved server-side from current household membership,
verified account and session version, never client-provided home/topic IDs.
Token rotation/account switching removes the old installation's pending queue;
logout and disable revoke via a private installation credential even when the
account token expired. If offline logout cannot confirm revocation, the app
reports it and retries on reconnection. Lock-screen text is deliberately generic;
details require authenticated household access. A push already accepted by
Google cannot be recalled during logout.

The durable outbox deduplicates gateway/event/installations, rechecks access
before sending, drops events older than 60 seconds, retries at most four times,
and deletes unregistered tokens. Registrations expire after 30 days without an
app refresh, with at most 20 notification installations per account.
Monitoring uploads remain successful during a push outage.
Delivery is at-least-once across a backend crash; Android event tags and saved
event history reduce duplicates. Foreground notifications continue to use
snapshot polling, not a duplicate FCM dispatcher.
Android force-stop, denied permissions, Doze/network conditions or vendor
battery restrictions can prevent/delay delivery; swiping away is not force-stop.

A signup HTTP 409 means the normalized email is already registered. Sign in
or recover that account, or use a genuinely unregistered email for isolation
tests. A second account must verify email and must not see the first account's
home unless explicitly invited. Do not invite the second account when testing
denied access; assigning the same Pi to two independent homes is not an
isolation test.

## Earlier foundation and legacy gateway procedures

### Restoring the customer app's real federated model update

The cloud Home screen has an owner/admin **Update global model** action.
It submits a gateway-scoped `train` command (no MAC, dataset, coordinator URL
or arbitrary process arguments). The existing Pi control worker forwards it
locally to the existing laptop Flower coordinator using the private gateway
credential. Training remains the real laptop + Pi local-training/FedAvg flow.
Cloud stores only bounded checkpoint/training metadata, never model weights,
raw packets, training rows or laptop filesystem paths.

Rollout requires additive schema **7**, updated Pi `router_ids_agent.py` and
`cloud_control_agent.py`, and `GHOST_CLOUD_TRAINING_ENABLED=true` on both the
Pi router service and customer backend. Update the Pi before enabling the
backend flag, with router/control backups and Python syntax checks. Restart
only the router and cloud-control services; keep existing credential settings.
The uploader does not need a code update for this nested model metadata.
The laptop coordinator must be running and reachable from the Pi, with the
existing shared gateway credential and configured Flower address/port.

Training startup acknowledgement is **not completion**. Home shows the real
coordinator state and current/total rounds separately from the Pi checkpoint's
FedAvg round. A coordinator outage disables startup without disabling threat
monitoring. Status is collected in a background thread at most every 10 seconds
so the two-second monitoring uploader is not blocked by laptop requests or
checkpoint reads. Progress older than 30 seconds is not treated as current.
The command queue never automatically redelivers a training start. Unknown
outcomes require checking the command/status rather than blindly starting again.

Verify owner/admin access, member read-only behavior and cross-household denial,
then run one real training cycle and confirm both laptop/Pi participants, round
progress, coordinator completion and the new Pi checkpoint. A passing button
test alone is not proof of federated training.

### Website and mobile synchronization

The customer website uses the same account, household, gateway snapshots and
command queue as the mobile app. It retains the original security-operations
presentation: branded header, "Know your exposure" sidebar, Operations metrics
and device cards, Detection history chart/table, and Federated model view.
Settings & access contains the new customer account and notification controls.
These views show real Pi data; there are no simulated devices or independent
website model runs. The chart groups uploaded detection statuses rather than
inventing attack-type labels. Legacy access-audit data is not exposed through
the customer API, so it is not substituted with fabricated login records.
Both clients poll every two seconds while active. A command acknowledged by
the Pi becomes visible to the other client through the next fresh snapshot.
Browser background throttling, network delay and a sleeping backend can slow
that interval; returning focus to the website requests a fresh snapshot.

The website includes real gateway-scoped federated training with null MAC,
owner/admin checks, rollout and fresh-coordinator guards, startup acknowledgement
distinct from completion, round progress and a separate Pi checkpoint round.
Uncertain commands remain recoverable by UUID without automatic replay.
Recent warnings remain visible for 60 seconds independently of current blocked
state. Activity uses the same uploaded event history as the customer app.

Optional browser notifications require explicit permission, are scoped to the
current signed-in account/home, and alert only on new recent threat events,
not the initial history. They work only while the website is open; closed-browser
web push is not implemented. Preferences are browser-local and do not change
Android push preferences. Muting, leaving a home or signing out closes current
browser notifications. Notification display failure is shown explicitly and
does not stop live snapshots. Themes and tab presentation are also client-local.

Build from `Frontend/Frontend` with
`VITE_CLOUD_API_URL=https://caughtin4k-1.onrender.com`. Configure the customer
Render service's `GHOST_CLOUD_WEB_ORIGINS` with the exact production website
origin (for the existing deployment, `https://caught-in4-k.vercel.app`), keeping
any other deliberately authorized HTTPS origins. Do not add wildcards, paths,
tokens, database URLs or service-account JSON to frontend configuration.
Deploy the rebuilt Vite source through Vercel; do not commit generated `dist`.
Local HTTP previews are for UI tests; the production backend deliberately
accepts only its configured HTTPS browser origins.

Run `node --test src/cloud-client.test.js` and `npm run build` before deployment.
Then use the same household on phone and deployed website to verify a real
device control from each direction, new parallel-device warning/block events,
Activity refresh, and coordinator/checkpoint progress. Pure UI mock tests do
not establish live cross-client synchronization.

### Consumer cloud foundation setup

The legacy deployment below uses one Pi household. The opt-in PostgreSQL
foundation does not rewrite that Pi database; public customer registration and
onboarding require the separate customer entrypoint described above.

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
The uploader can send this header using the separate staging environment.
After a successful one-shot upload, add `--require-snapshot` to
`verify_cloud_staging.py` to check that the owner can read the stored metadata
through the household-scoped endpoint. It reports only device/alert counts and
freshness flags, not private device details. Stale data is expected when only a
one-shot upload has run; this check does not enable continuous uploads.
An uploader error prefixed `Local Pi snapshot` concerns the local export;
`Cloud staging upload` concerns the cloud request. A rejected staging token
must be corrected before the cloud can check the gateway machine credential.

### Outbound network controls (staging rollout required)

Schema migration 003 adds a private command queue. Apply it with the existing
private database initialization CLI before using the new command endpoints.
No existing accounts, memberships, snapshots, Pi datasets, or models are
replaced. The new channel remains disabled on the Pi by default.

- An authenticated household owner/admin submits a block/unblock command to
  `POST /cloud/households/{household_id}/gateways/{gateway_id}/commands`,
  using a client-generated UUID `command_id`, lowercase `mac`, and `action`.
  Repeating the same ID and payload returns the original command; changing
  its creator, gateway, or payload is rejected. Regular members can read
  status but cannot submit network controls.
- The cloud checks gateway membership, revocation, and snapshot device
  presence. Only one queued/delivered command per gateway is allowed.
  A queued command expires after 120 seconds rather than executing on a
  device that reconnects much later.
- The separate `cloud_control_agent.py` polls outbound every 10 seconds with
  the gateway machine credential and, during private staging, the staging
  token. Delivery rechecks the initiating account's owner/admin role.
  This is independent of the 30-second metadata uploader and Flower.
- The Pi endpoint `/cloud-agent/control` requires the local private router
  token, a loopback connection, and `GHOST_CLOUD_CONTROL_ENABLED=true` in
  the router process. Set the same flag for the separate worker service.
  The worker is unprivileged; the existing router uses its existing
  restricted firewall helper. No remote shell, IP, or executable is accepted.
  Registered-device and excluded-coordinator checks still apply.
- The existing AP/nftables enforcement is reused. Dry-run, unsupported
  topology, missing helper permission, and failed enforcement do not count
  as successful blocking. The Pi must be the device's actual network gateway;
  receiving a cloud command alone cannot isolate a device on another router.
- User clients poll the household-scoped command status endpoint.
  `queued`/`delivered` are not success; `succeeded` means the Pi reported
  enforcement. `expired` means not dispatched, `cancelled` means role no
  longer permits execution, and `unknown` means execution is unconfirmed.
  The worker retries a result acknowledgement, never the firewall operation.
  Lost delivery responses or worker restarts can therefore leave an unknown
  outcome; reconcile against a fresh snapshot before issuing a new command.

The command channel is not deployed or enabled by source changes alone.
After deployment and explicit Pi worker enablement, use the local
`Backend/Backend/verify_cloud_control.py --url <staging-origin> --bundle
<private-import-bundle> --action block` operator helper. It prompts privately
for staging access and owner login, requires fresh household-scoped metadata,
lists devices locally, and requires a numbered selection plus exact `BLOCK`
confirmation. Choose only a nonessential client of the Pi-hosted Wi-Fi, never
the Pi, uplink, or SSH/training laptop. Run again with `--action unblock`
and select the same MAC to restore access. Confirm actual Wi-Fi connectivity
with cellular fallback disabled; a firewall acknowledgement alone does not
prove end-to-end isolation.
The helper prints a command UUID before submission. If interrupted or timed
out, recover with `--action status --command-id <UUID>` instead of blindly
resubmitting. Queued/delivered/unknown status never counts as success.
The installed earlier test APK exposed private staging setup. That workflow
has been removed from the current customer source in favor of normal account
sign-in, verification, home pairing and remote controls in both clients. Do not
install the new customer APK against the still-private staging entrypoint:
customer requests intentionally do not contain its operator access token.
Follow the public customer rollout above before replacing consumer clients.

For the separate cloud staging service, use root `Backend/Backend`, build
`pip install -r requirements_cloud.txt`, and start
`uvicorn cloud_staging_app:app --host 0.0.0.0 --port $PORT`.
Set health path `/health`. This entry point does not import Torch, load an
inference checkpoint, or expose legacy Pi/coordinator routes. Its dependencies
exclude GPU/CUDA packages. The Pi and laptop continue using their existing
requirements and entry points; real federated training is not removed.
Staging requires the database URL, cloud session secret, and staging token.
Its public health check proves process readiness, not database connectivity.

Once deployed, run `verify_cloud_staging.py --url <staging-https-origin>
--bundle <private-migration-folder>` locally. It prompts privately for the
staging access token and existing owner credentials, then verifies cloud login,
owner membership, and the imported gateway through HTTPS. It prints no tokens
or account details, follows no redirects, and does not enable uploads or change
Pi configuration. This verifies the imported owner only, not every consumer flow.
The verifier first checks the private staging gate without submitting account
credentials. Its errors distinguish a rejected staging token from rejected
owner credentials. Pi password changes after import are not synchronized to
the cloud snapshot; do not reset passwords blindly when diagnosing staging.

`prepare_pi_staging.py --bundle <import-bundle> --url <staging-origin>
--output <new-private-folder>` prompts for the staging token, validates matching
gateway identifiers, and creates a separate protected `cloud-staging.env`.
The imported bundle is not modified, uploads remain disabled, and the private
router token is not copied. The staging token goes only to cloud requests,
not loopback. The Pi will need the router and staging environment files loaded
by a separate uploader service. `cloud_uploader.py --once` provides an explicit
one-upload acknowledgement check. Do not remove Ngrok or switch consumer clients
until real Pi uploads and household-scoped reads have been verified.

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
