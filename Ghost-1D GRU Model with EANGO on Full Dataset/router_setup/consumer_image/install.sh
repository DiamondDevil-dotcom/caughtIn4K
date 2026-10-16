#!/bin/bash
set -euo pipefail
[[ "${GHOST_FACTORY_IMAGE_BUILD:-}" == 1 && "$EUID" == 0 ]] || {
  echo "Image-build chroot only; not a customer or live-Pi installer." >&2; exit 1;
}
test "$(dpkg --print-architecture)" = arm64
test ! -e /etc/caughtin4k/device.env
: "${FIRST_USER_NAME:?Run with the pi-gen build environment}"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get purge -y cloud-init rpi-cloud-init-mods
apt-get install -y python3-venv python3-pip network-manager nftables iw sudo rfkill
test "$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')" = 3.13
useradd --system --home-dir /var/lib/caughtin4k --shell /usr/sbin/nologin caughtin4k
usermod --lock --shell /usr/sbin/nologin "${FIRST_USER_NAME}"
systemctl disable ssh
install -d -m 0700 /etc/caughtin4k
install -d -o caughtin4k -g caughtin4k -m 0700 /var/lib/caughtin4k
install -d -m 0700 /var/lib/caughtin4k-setup
install -d -m 0755 /var/cache/caughtin4k-pip
TMPDIR=/var/cache/caughtin4k-pip python3 -m venv /opt/caughtin4k/venv
TMPDIR=/var/cache/caughtin4k-pip /opt/caughtin4k/venv/bin/python -m pip install \
  --no-cache-dir --no-index --only-binary=:all: --find-links /var/cache/caughtin4k-wheels \
  -r /opt/caughtin4k/router_setup/requirements_consumer.txt
/opt/caughtin4k/venv/bin/python -c \
  'import torch; assert torch.__version__ == "2.13.0+cpu" and torch.version.cuda is None'
(
  cd /opt/caughtin4k
  GHOST_FL_PI_MODEL=/opt/caughtin4k/model.pth GHOST_ROUTER_DATA_DIR=/var/lib/caughtin4k \
    /opt/caughtin4k/venv/bin/python -c 'from router_ids_agent import load_model; load_model()'
)
install -d -m 0755 /etc/nftables.d
install -m 0644 /opt/caughtin4k/router_setup/caughtin4k.nft /etc/nftables.d/caughtin4k.nft
grep -qF 'include "/etc/nftables.d/*.nft"' /etc/nftables.conf || \
  printf '\ninclude "/etc/nftables.d/*.nft"\n' >>/etc/nftables.conf
install -m 0755 /opt/caughtin4k/router_setup/gateway_block_helper.sh /usr/local/sbin/caughtin4k-block
printf 'caughtin4k ALL=(root) NOPASSWD: /usr/local/sbin/caughtin4k-block\n' >/etc/sudoers.d/caughtin4k-router
chmod 0440 /etc/sudoers.d/caughtin4k-router
visudo -cf /etc/sudoers.d/caughtin4k-router
printf 'net.ipv4.ip_forward=1\n' >/etc/sysctl.d/99-caughtin4k-router.conf
cat >/etc/caughtin4k/router.env <<'ENV'
GHOST_FL_PI_MODEL=/opt/caughtin4k/model.pth
GHOST_ROUTER_DATA_DIR=/var/lib/caughtin4k
GHOST_ROUTER_IFACE=wlan0
GHOST_ROUTER_BLOCK_MODE=enforce
GHOST_ROUTER_BLOCK_METHOD=gateway
GHOST_CAPTURE_MODE=observe
GHOST_CLOUD_UPLOAD_ENABLED=true
GHOST_CLOUD_CONTROL_ENABLED=true
GHOST_CLOUD_DEVICE_MANAGEMENT_ENABLED=true
GHOST_CLOUD_TRAINING_ENABLED=false
OMP_NUM_THREADS=2
MKL_NUM_THREADS=2
ENV
chmod 0600 /etc/caughtin4k/router.env
for component in router uploader control setup; do
  prestart=''
  case "$component" in
    router)
      script='router_ids_agent.py --iface wlan0 --api-port 8001'; user=caughtin4k
      prestart="ExecStartPre=/bin/sh -c 'until /usr/sbin/iw dev wlan0 info 2>/dev/null | /usr/bin/grep -q \"type AP\"; do /usr/bin/sleep 2; done'"
      ;;
    uploader) script=cloud_uploader.py; user=caughtin4k ;;
    control) script=cloud_control_agent.py; user=caughtin4k ;;
    setup)
      script=consumer_setup_agent.py; user=root
      prestart='ExecStartPre=/usr/sbin/rfkill unblock wlan'
      ;;
  esac
  cat >"/etc/systemd/system/caughtin4k-${component}.service" <<UNIT
[Unit]
Description=caughtIn4K consumer ${component}
After=NetworkManager.service nftables.service network-online.target
Wants=network-online.target
ConditionPathExists=/etc/caughtin4k/device.env

[Service]
Type=simple
User=${user}
WorkingDirectory=/opt/caughtin4k
EnvironmentFile=/etc/caughtin4k/router.env
EnvironmentFile=/etc/caughtin4k/device.env
${prestart}
TimeoutStartSec=infinity
ExecStart=/opt/caughtin4k/venv/bin/python /opt/caughtin4k/${script}
Restart=on-failure
RestartSec=10
UMask=0077
AmbientCapabilities=CAP_NET_RAW

[Install]
WantedBy=multi-user.target
UNIT
  systemctl enable "caughtin4k-${component}.service"
done
systemctl enable NetworkManager nftables
echo "Generic image prepared without identity. Personalize each device before shipment."
