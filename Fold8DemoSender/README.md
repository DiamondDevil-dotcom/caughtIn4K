# caughtIn4K demo sender

This app sends labeled sample feature vectors for a controlled demonstration.
These samples are not live packet captures and do not demonstrate real-traffic
detection accuracy or resolve the training/live feature mismatch.

## Local authenticated demo

Connect the laptop and sender phone to the Pi's `caughtIn4K-IoT` hotspot.
Leave the current Pi services, cloud pairing and private training coordinator
running unchanged.

In a **separate Windows PowerShell terminal**, from the repository root:

```powershell
& ".\Backend\Backend\start_demo_gateway.ps1"
```

Enter the existing Pi shared token privately at the prompt. The script runs a
gateway-mode API on `192.168.50.198:8002`, bound only to the private interface.
If the laptop address changed, pass `-ListenAddress "<current-private-IPv4>"`.
The default Pi upstream is `http://192.168.50.1:8001`.

In the sender, set **Shared gateway URL** to the printed address and sign in with
the existing **Pi-household** email/password. Customer-cloud account credentials
are separate. The phone MAC must match the actual Wi-Fi identity, including any
Android per-network randomized MAC.

- Port **8000** is the private coordinator, not the sender login service.
- Port **8001** is the private Pi API and requires the operator token; do not
  put that token in the sender.
- Port **8002** verifies the Pi-household login and signs a session. Protected
  telemetry is sent with that session, not the operator token.
- The old Render gateway timed out during troubleshooting. Do not point this
  sender at the separate customer API: it does not implement these telemetry
  routes.

This is an isolated Wi-Fi HTTP demonstration, not a public deployment. Do not
publicly tunnel this local API or Flower. If Windows Firewall blocks access,
authorize a rule for port 8002 only from the sender phone's actual IPv4 address
on this subnet. The launcher does not change firewall rules.

Building with a different address:

```powershell
flutter build apk --release --dart-define=ROUTER_API_URL=http://<laptop-private-IP>:8002
```

Sign-in starts normal sample streaming. Use the attack button only on your own
demo network: existing Pi enforcement can block the sender phone. Keep a
separate laptop connection available for restoration.
