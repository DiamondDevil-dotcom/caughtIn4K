#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
MAC="${2:-}"
IFACE="${3:-wlan0}"

if [[ ! "${MAC}" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]]; then
  echo "Invalid MAC address" >&2
  exit 2
fi
if [[ ! "${IFACE}" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
  echo "Invalid interface" >&2
  exit 2
fi

case "${ACTION}" in
  block)
    if ! nft get element inet caughtin4k blocked_macs "{ ${MAC} }" >/dev/null 2>&1; then
      nft add element inet caughtin4k blocked_macs "{ ${MAC} }"
    fi
    iw dev "${IFACE}" station del "${MAC}" >/dev/null 2>&1 || true
    ;;
  disconnect)
    iw dev "${IFACE}" station del "${MAC}" >/dev/null 2>&1 || true
    ;;
  unblock)
    if nft get element inet caughtin4k blocked_macs "{ ${MAC} }" >/dev/null 2>&1; then
      nft delete element inet caughtin4k blocked_macs "{ ${MAC} }"
    fi
    ;;
  *)
    echo "Usage: caughtin4k-block block|disconnect|unblock MAC [INTERFACE]" >&2
    exit 2
    ;;
esac