#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo."
  exit 1
fi

TARGET_USER="${SUDO_USER:-pi}"
TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
PROJECT_DIR="${GHOST_PROJECT_DIR:-${TARGET_HOME}/Ghost-1D GRU Model with EANGO on Full Dataset}"
PYTHON_BIN="${GHOST_PYTHON:-${TARGET_HOME}/miniforge3/envs/ghostfl/bin/python3.12}"
AP_IFACE="${GHOST_ROUTER_IFACE:-wlan0}"
UPSTREAM_IFACE="${GHOST_ROUTER_UPSTREAM_IFACE:-eth0}"
IOT_SSID="${GHOST_IOT_SSID:-caughtIn4K-IoT}"
IOT_PSK="${GHOST_IOT_PSK:-}"

if [[ ${#IOT_PSK} -lt 8 ]]; then
  read -rsp "New caughtIn4K-IoT Wi-Fi password (8+ characters): " IOT_PSK
  echo
fi
if [[ ${#IOT_PSK} -lt 8 ]]; then
  echo "The Wi-Fi password must contain at least 8 characters."
  exit 1
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python environment not found: ${PYTHON_BIN}"
  echo "Set GHOST_PYTHON to the ghostfl Python executable."
  exit 1
fi
if [[ ! -f "${PROJECT_DIR}/router_ids_agent.py" ]]; then
  echo "Project not found: ${PROJECT_DIR}"
  exit 1
fi

apt-get update
apt-get install -y network-manager nftables iw

nmcli connection delete caughtIn4K-IoT >/dev/null 2>&1 || true
nmcli connection add type wifi ifname "${AP_IFACE}" con-name caughtIn4K-IoT ssid "${IOT_SSID}"
nmcli connection modify caughtIn4K-IoT \
  connection.autoconnect yes \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  ipv4.method shared \
  ipv4.addresses 192.168.50.1/24 \
  ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "${IOT_PSK}"

cat >/etc/sysctl.d/99-caughtin4k-router.conf <<EOF
net.ipv4.ip_forward=1
EOF
sysctl --system >/dev/null

install -d -m 0755 /etc/nftables.d
tr -d '\r' <"${PROJECT_DIR}/router_setup/caughtin4k.nft" \
  | sed "s/\"wlan0\"/\"${AP_IFACE}\"/g" \
  >/etc/nftables.d/caughtin4k.nft
if ! grep -qF 'include "/etc/nftables.d/*.nft"' /etc/nftables.conf; then
  printf '\ninclude "/etc/nftables.d/*.nft"\n' >>/etc/nftables.conf
fi
systemctl enable --now nftables
nft delete table inet caughtin4k 2>/dev/null || true
nft -f /etc/nftables.d/caughtin4k.nft

install -o root -g root -m 0755 \
  "${PROJECT_DIR}/router_setup/gateway_block_helper.sh" \
  /usr/local/sbin/caughtin4k-block
cat >/etc/sudoers.d/caughtin4k-router <<EOF
${TARGET_USER} ALL=(root) NOPASSWD: /usr/local/sbin/caughtin4k-block
EOF
chmod 0440 /etc/sudoers.d/caughtin4k-router
visudo -cf /etc/sudoers.d/caughtin4k-router

cat >/etc/systemd/system/caughtin4k-router.service <<EOF
[Unit]
Description=caughtIn4K IoT IDS and gateway controller
After=NetworkManager.service nftables.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${TARGET_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} router_ids_agent.py --iface ${AP_IFACE} --api-port 8001
Environment=GHOST_ROUTER_BLOCK_MODE=enforce
Environment=GHOST_ROUTER_BLOCK_METHOD=gateway
Environment=GHOST_ROUTER_IFACE=${AP_IFACE}
Environment=GHOST_ROUTER_DATA_DIR=${TARGET_HOME}/Database
Environment=GHOST_ROUTER_EXCLUDED_MACS=${GHOST_ROUTER_EXCLUDED_MACS:-}
EnvironmentFile=-/etc/caughtin4k/router.env
AmbientCapabilities=CAP_NET_RAW
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

install -d -o "${TARGET_USER}" -g "${TARGET_USER}" "${TARGET_HOME}/Database"
systemctl daemon-reload
systemctl enable caughtin4k-router.service
nmcli connection up "caughtIn4K-IoT"
systemctl restart caughtin4k-router.service

echo "Gateway ready. Connect IoT devices to '${IOT_SSID}'."
echo "Pi IoT gateway/API: http://192.168.50.1:8001"
echo "Upstream interface: ${UPSTREAM_IFACE}"
