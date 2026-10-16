#!/bin/bash -e
# pi-gen custom stage. Source and wheelhouse are manufacturer-only inputs.
set -euo pipefail
: "${ROOTFS_DIR:?Run this stage through pi-gen}"
[[ "$(readlink -f "$ROOTFS_DIR")" != / && -f "$ROOTFS_DIR/etc/os-release" ]] || exit 1
: "${GHOST_CONSUMER_SOURCE:?Set the trusted model source directory}"
: "${GHOST_CONSUMER_WHEELHOUSE:?Set the ARM64 CPython 3.13 wheelhouse directory}"
: "${GHOST_CONSUMER_MODEL:?Set the approved 14-feature checkpoint path}"
: "${GHOST_CONSUMER_MODEL_SHA256:?Set its approved SHA-256}"
: "${GHOST_CONSUMER_WIFI_COUNTRY:?Set the two-letter sales-region Wi-Fi country}"
[[ "$GHOST_CONSUMER_MODEL_SHA256" =~ ^[a-fA-F0-9]{64}$ ]] || exit 1
[[ "$GHOST_CONSUMER_WIFI_COUNTRY" =~ ^[A-Z]{2}$ ]] || exit 1
test "$(sha256sum "$GHOST_CONSUMER_MODEL" | cut -d ' ' -f 1)" = "${GHOST_CONSUMER_MODEL_SHA256,,}"
install -d "${ROOTFS_DIR}/opt/caughtin4k" "${ROOTFS_DIR}/var/cache/caughtin4k-wheels"
for source in model.py storage.py network_control.py wifi_client.py router_ids_agent.py \
  cloud_uploader.py cloud_control_agent.py consumer_setup_agent.py; do
  install -m 0644 "$GHOST_CONSUMER_SOURCE/$source" "${ROOTFS_DIR}/opt/caughtin4k/$source"
done
install -m 0644 "$GHOST_CONSUMER_MODEL" "${ROOTFS_DIR}/opt/caughtin4k/model.pth"
cp -a "$GHOST_CONSUMER_WHEELHOUSE/." "${ROOTFS_DIR}/var/cache/caughtin4k-wheels/"
install -d "${ROOTFS_DIR}/opt/caughtin4k/router_setup"
for source in caughtin4k.nft gateway_block_helper.sh requirements_consumer.txt; do
  install -m 0644 "$GHOST_CONSUMER_SOURCE/router_setup/$source" "${ROOTFS_DIR}/opt/caughtin4k/router_setup/$source"
done
install -m 0755 "$GHOST_CONSUMER_SOURCE/router_setup/consumer_image/install.sh" \
  "${ROOTFS_DIR}/opt/caughtin4k/router_setup/install-consumer.sh"
install -d "${ROOTFS_DIR}/etc/modprobe.d"
printf 'options cfg80211 ieee80211_regdom=%s\n' "$GHOST_CONSUMER_WIFI_COUNTRY" \
  >"${ROOTFS_DIR}/etc/modprobe.d/caughtin4k-wifi.conf"
on_chroot <<'CHROOT'
GHOST_FACTORY_IMAGE_BUILD=1 /opt/caughtin4k/router_setup/install-consumer.sh
CHROOT
# Remove only this stage's temporary wheel copies, never the caller's wheelhouse.
find "${ROOTFS_DIR}/var/cache/caughtin4k-wheels" -mindepth 1 -maxdepth 1 -type f -delete
