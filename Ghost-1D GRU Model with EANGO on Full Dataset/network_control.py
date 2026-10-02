"""Enforces device isolation when the Pi is the IoT network gateway.

The supported production topology is Ethernet upstream plus a Pi-hosted Wi-Fi
access point. nftables drops blocked MAC addresses at both the input and
forward hooks. A best-effort Wi-Fi station deletion disconnects an associated
client immediately; nftables keeps it isolated if it reconnects.
"""

import os
import subprocess
import threading

BLOCK_MODE = os.getenv("GHOST_ROUTER_BLOCK_MODE", "enforce")
BLOCK_METHOD = os.getenv("GHOST_ROUTER_BLOCK_METHOD", "gateway")
HOSTAPD_INTERFACE = os.getenv("GHOST_ROUTER_IFACE", "wlan0")
GATEWAY_HELPER = os.getenv(
    "GHOST_ROUTER_HELPER",
    "/usr/local/sbin/caughtin4k-block",
)
_deauth_threads: dict[str, threading.Event] = {}


def _run(command):
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        return True, ""
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        return False, detail


def _interface_is_access_point():
    try:
        result = subprocess.run(
            ["iw", "dev", HOSTAPD_INTERFACE, "info"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return any(line.strip() == "type AP" for line in result.stdout.splitlines())


def _gateway_block(mac_address):
    if not _interface_is_access_point():
        return False, f"{HOSTAPD_INTERFACE} is not operating as a Wi-Fi access point."
    success, detail = _run(
        ["sudo", "-n", GATEWAY_HELPER, "block", mac_address, HOSTAPD_INTERFACE]
    )
    if success and mac_address not in _deauth_threads:
        stop_event = threading.Event()
        _deauth_threads[mac_address] = stop_event
        threading.Thread(
            target=_deauth_loop,
            args=(mac_address, stop_event),
            daemon=True,
        ).start()
    return success, detail or "gateway_firewall_enforced"


def _gateway_unblock(mac_address):
    stop_event = _deauth_threads.pop(mac_address, None)
    if stop_event is not None:
        stop_event.set()
    success, detail = _run(
        ["sudo", "-n", GATEWAY_HELPER, "unblock", mac_address, HOSTAPD_INTERFACE]
    )
    return success, detail or "gateway_firewall_removed"


def _deauth_loop(mac_address, stop_event):
    while not stop_event.wait(2.0):
        _run(
            [
                "sudo", "-n", GATEWAY_HELPER, "disconnect",
                mac_address, HOSTAPD_INTERFACE,
            ]
        )


def block_mac(mac_address, target_ip=None):
    mac_address = mac_address.strip().lower()

    if BLOCK_MODE != "enforce":
        print(f"[dry-run] would block {mac_address} via {BLOCK_METHOD}")
        return False, "dry_run_no_network_change"

    if BLOCK_METHOD != "gateway":
        return False, f"Unsupported block method: {BLOCK_METHOD}"
    return _gateway_block(mac_address)


def unblock_mac(mac_address):
    mac_address = mac_address.strip().lower()

    if BLOCK_MODE != "enforce":
        print(f"[dry-run] would unblock {mac_address} via {BLOCK_METHOD}")
        return False, "dry_run_no_network_change"

    if BLOCK_METHOD != "gateway":
        return False, f"Unsupported block method: {BLOCK_METHOD}"
    return _gateway_unblock(mac_address)
