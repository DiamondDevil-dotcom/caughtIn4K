"""Lets the Pi join any Wi-Fi network you choose at setup/runtime, instead of
being locked to one network. Uses NetworkManager's `nmcli`, the default on
current Raspberry Pi OS (Bookworm and newer).

If your Pi OS still uses dhcpcd/wpa_supplicant (older Bullseye images), this
will fail with "nmcli: command not found" — in that case edit
/etc/wpa_supplicant/wpa_supplicant.conf directly and run
`sudo wpa_cli -i wlan0 reconfigure` instead; that path is not automated here
since it was not testable without the physical device.
"""

import subprocess


def connect(ssid, password):
    """Joins the given Wi-Fi network. Returns (success, detail)."""
    try:
        result = subprocess.run(
            ["nmcli", "device", "wifi", "connect", ssid, "password", password],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True, result.stdout.strip()
    except FileNotFoundError:
        return False, "nmcli not found; this Pi OS may use wpa_supplicant instead."
    except subprocess.TimeoutExpired:
        return False, "Connection attempt timed out."
    except subprocess.CalledProcessError as error:
        return False, error.stderr.strip() or error.stdout.strip()


def current_status():
    """Returns the currently connected SSID, or None if not connected."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "device", "wifi"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
        return None
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
