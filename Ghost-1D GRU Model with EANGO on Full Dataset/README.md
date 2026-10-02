# Ghost 1D GRU model

## Runtime data and password email

The router agent stores its SQLite database in the workspace-level
`Database/router_ids.db`, outside this model folder. The first startup
migrates an existing model-folder `router_ids.db` or `data/router_ids.db` into
that folder so accounts, devices, and events are preserved. Set
`GHOST_ROUTER_DATA_DIR` or `GHOST_ROUTER_DB` to use another server-side
location.

A website should call the router agent's HTTP API (`/auth/*`, `/devices`,
`/events`, and `/telemetry`) rather than opening the SQLite file directly.
This keeps database credentials and password hashes on the backend machine.

Password changes work immediately through the authenticated endpoint. Email
password resets require SMTP configuration on the machine running the router
agent:

```text
GHOST_SMTP_HOST=smtp.example.com
GHOST_SMTP_PORT=587
GHOST_SMTP_USERNAME=sender@example.com
GHOST_SMTP_PASSWORD=<provider-app-password>
GHOST_SMTP_FROM=sender@example.com
```

The reset code expires after 15 minutes. Do not commit the database or SMTP
passwords.

## Real IoT blocking gateway

Reliable blocking requires the Raspberry Pi to route the IoT traffic:

```text
Internet router --Ethernet--> Raspberry Pi 3 --Wi-Fi--> IoT devices
```

Connect the Pi's `eth0` port to the internet router before changing `wlan0`
into an access point. On Raspberry Pi OS 64-bit with NetworkManager, run from
the project directory:

```bash
sudo GHOST_IOT_SSID='caughtIn4K-IoT' \
	GHOST_IOT_PSK='<choose-a-new-wifi-password>' \
	GHOST_ROUTER_EXCLUDED_MACS='<laptop-wifi-mac>' \
	bash router_setup/setup_gateway.sh
```

Use the laptop Wi-Fi MAC address that the Pi sees when connected to this access
point. The laptop still runs the Flower server and its separate local training
client, but the Pi excludes it from packet detection and the app/website device
list. Other associated devices remain visible and manageable.

The script creates `192.168.50.1/24` on the IoT Wi-Fi, enables DHCP/NAT,
loads the `caughtin4k` nftables firewall, and installs the IDS as a systemd
service. Connect the fan, AC, CCTV, DVR, printer, Alexa, smart plugs, and the
monitoring phone to `caughtIn4K-IoT`. The app router URL is then
`http://192.168.50.1:8001`.

Strict blocking adds the device MAC to an nftables set and repeatedly removes
its Wi-Fi station from the Pi access point. A disconnected device cannot use
the app to unblock itself; unblock it from the laptop website. Unblocking
removes the firewall entry and stops deauthentication so the device can join
again. The old ARP-spoofing method is not used.
