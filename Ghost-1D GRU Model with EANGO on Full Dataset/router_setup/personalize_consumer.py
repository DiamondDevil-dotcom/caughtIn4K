"""Manufacturer-only personalization of an offline, mounted Linux image."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from uuid import UUID


def personalize(root: Path, bundle: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        raise ValueError("Personalize a mounted, offline Linux image as root.")
    root = root.resolve(strict=True)
    if root == Path("/") or not (root / "opt/caughtin4k/consumer_setup_agent.py").is_file():
        raise ValueError("Use the mounted consumer image, not a running system.")
    target = root / "etc/caughtin4k/device.env"
    if target.exists():
        raise ValueError("Device identity already exists; never clone a personalized image.")
    if (bundle / "consumer-setup.txt").read_text(encoding="utf-8") != "enabled\n":
        raise ValueError("Provision this device explicitly for consumer setup.")
    allowed = {"GHOST_CLOUD_UPLOAD_ENABLED", "GHOST_CLOUD_API_URL",
               "GHOST_CLOUD_GATEWAY_ID", "GHOST_CLOUD_GATEWAY_CREDENTIAL"}
    settings = {}
    for line in (bundle / "gateway.env").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in allowed or key in settings:
            raise ValueError("Invalid manufacturer gateway bundle.")
        settings[key] = value
    if set(settings) != allowed:
        raise ValueError("Incomplete manufacturer gateway bundle.")
    UUID(settings["GHOST_CLOUD_GATEWAY_ID"])
    cloud = urlsplit(settings["GHOST_CLOUD_API_URL"])
    if (cloud.scheme != "https" or not cloud.hostname or cloud.username or cloud.password
            or cloud.path not in {"", "/"} or cloud.query or cloud.fragment):
        raise ValueError("Invalid cloud origin.")
    credential = settings["GHOST_CLOUD_GATEWAY_CREDENTIAL"]
    if not 32 <= len(credential) <= 256 or any(
        c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in credential
    ):
        raise ValueError("Invalid gateway credential.")
    # Restrict env-file syntax; URLs and credentials may never inject another setting.
    if any(any(c.isspace() or c in "\"'\\#" for c in value) for value in settings.values()):
        raise ValueError("Invalid device environment values.")
    # Reserve the bundle before writing identity. Ambiguous failures require
    # manufacturer reconciliation, not a second device with the same credential.
    reservation = os.open(bundle / "personalized.marker", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(reservation, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(settings["GHOST_CLOUD_GATEWAY_ID"] + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    settings["GHOST_CLOUD_UPLOAD_ENABLED"] = "true"
    settings["GHOST_ROUTER_TOKEN"] = secrets.token_urlsafe(32)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in settings.items()))
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(target, 0, 0)
    target.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    try:
        personalize(args.root, args.bundle)
    except (ValueError, OSError):
        parser.exit(1, "Personalization failed. Do not ship this device or print its label; inspect it privately.\n")
    print("Device personalized. Keep its matching pairing label private; never duplicate this image.")


if __name__ == "__main__":
    main()
