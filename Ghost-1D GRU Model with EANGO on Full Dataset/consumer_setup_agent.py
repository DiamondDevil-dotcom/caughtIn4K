"""Factory-installed setup worker. Customers never run this from a terminal."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from uuid import UUID

from cloud_uploader import (
    NoRedirect, PermanentUploadError, UploadConfig, UploadError, endpoint_json, retry_delay,
)

logger = logging.getLogger(__name__)
PROFILE = Path("/etc/NetworkManager/system-connections/caughtin4k-consumer.nmconnection")
STATE = Path("/var/lib/caughtin4k-setup/state.json")


class SetupError(RuntimeError):
    pass


def run_command(args: list[str], *, timeout: int = 30) -> str:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        # NetworkManager errors can contain credentials; expose only a safe code.
        raise SetupError("network_configuration_failed") from None


def atomic_private(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def validate_wifi(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"request_id", "ssid", "password"}:
        raise PermanentUploadError("Invalid Wi-Fi configuration contract.")
    try:
        UUID(value["request_id"])
        ssid, password = value["ssid"], value["password"]
        if (
            not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32
            or any(ord(c) < 32 or ord(c) == 127 for c in ssid)
            or not isinstance(password, str) or not 8 <= len(password) <= 63
            or any(not 32 <= ord(c) <= 126 for c in password)
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise PermanentUploadError("Invalid Wi-Fi configuration contract.") from None
    return value


def wifi_profile(configuration: dict) -> str:
    validate_wifi(configuration)
    ssid = "".join(f"{byte};" for byte in configuration["ssid"].encode("utf-8"))
    password = configuration["password"].replace("\\", "\\\\").replace(" ", "\\s")
    return (
        "[connection]\nid=caughtin4k-consumer\n"
        f"uuid={configuration['request_id']}\ntype=wifi\ninterface-name=wlan0\nautoconnect=true\n"
        f"[wifi]\nmode=ap\nband=bg\nssid={ssid}\n"
        f"[wifi-security]\nkey-mgmt=wpa-psk\npsk={password}\n"
        "[ipv4]\nmethod=shared\naddress1=192.168.50.1/24\n"
        "[ipv6]\nmethod=disabled\n"
    )


def apply_wifi(configuration: dict, profile: Path = PROFILE, state: Path = STATE) -> None:
    validate_wifi(configuration)
    old_profile = profile.read_text(encoding="utf-8") if profile.exists() else None
    atomic_private(profile, wifi_profile(configuration))
    try:
        run_command(["nmcli", "connection", "load", str(profile)])
        run_command(["nmcli", "--wait", "30", "connection", "up", "uuid", configuration["request_id"]], timeout=40)
    except SetupError:
        if old_profile is not None:
            atomic_private(profile, old_profile)
            try:
                run_command(["nmcli", "connection", "load", str(profile)])
                run_command(["nmcli", "--wait", "30", "connection", "up", "id", "caughtin4k-consumer"], timeout=40)
            except SetupError:
                logger.error("Previous Wi-Fi configuration could not be restored.")
        else:
            profile.unlink(missing_ok=True)
            try:
                run_command(["nmcli", "connection", "delete", "uuid", configuration["request_id"]])
            except SetupError:
                logger.error("Failed Wi-Fi profile could not be unloaded.")
        raise
    # Persist only an applied revision; the password stays in NetworkManager's root-only file.
    atomic_private(state, json.dumps({"request_id": configuration["request_id"]}))


def read_revision(state: Path = STATE) -> str | None:
    if not state.exists():
        return None
    try:
        value = json.loads(state.read_text(encoding="utf-8"))
        return str(UUID(value["request_id"]))
    except (ValueError, KeyError, TypeError):
        raise PermanentUploadError("Saved setup revision is invalid; factory repair is required.") from None


def local_checks(config: UploadConfig, opener, revision: str | None) -> dict[str, bool]:
    checks = dict.fromkeys(("ethernet", "wifi", "router", "model", "firewall"), False)
    try:
        routes = json.loads(run_command(["ip", "-j", "-4", "route", "show", "default"]))
        checks["ethernet"] = any(route.get("dev") == "eth0" for route in routes)
        active = run_command(["nmcli", "-g", "GENERAL.CON-UUID", "device", "show", "wlan0"])
        checks["wifi"] = revision is not None and active == revision and "type AP" in run_command(["iw", "dev", "wlan0", "info"])
        table = run_command(["nft", "-j", "list", "table", "inet", "caughtin4k"])
        objects = json.loads(table)["nftables"]
        sets = {item["set"]["name"] for item in objects if "set" in item}
        chains = {item["chain"]["name"] for item in objects if "chain" in item}
        checks["firewall"] = "blocked_macs" in sets and {"input_filter", "forward_filter"} <= chains
    except (SetupError, ValueError, KeyError, TypeError):
        logger.warning("One or more local network setup checks failed.")
    try:
        snapshot = endpoint_json(opener, urllib.request.Request(
            config.local_url + "/cloud-agent/snapshot", headers={"X-Gateway-Token": config.router_token},
        ), "Setup router check")
        checks["router"] = {"observed_at", "devices", "alerts", "model"} <= set(snapshot)
        checks["model"] = isinstance(snapshot.get("model"), dict) and snapshot["model"].get("available") is True
    except UploadError:
        logger.warning("Gateway model service is not ready.")
    return checks


class SetupWorker:
    def __init__(self, config: UploadConfig):
        self.config = config
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.error: str | None = None
        self.failed_revision: str | None = None

    def poll(self) -> None:
        revision = read_revision()
        checks = local_checks(self.config, self.opener, revision)
        response = endpoint_json(self.opener, urllib.request.Request(
            f"{self.config.cloud_url.rstrip('/')}/cloud/gateways/{self.config.gateway_id}/setup/exchange",
            data=json.dumps({"request_id": revision, "checks": checks, "error_code": self.error}).encode("utf-8"),
            headers={"X-Gateway-Credential": self.config.credential, "Content-Type": "application/json"},
            method="POST",
        ), "Consumer setup exchange")
        if type(response.get("paired")) is not bool or "configuration" not in response:
            raise PermanentUploadError("Invalid setup exchange response.")
        configuration = response["configuration"]
        if configuration is None:
            return
        if response["paired"] is not True:
            raise PermanentUploadError("Unpaired gateway received Wi-Fi settings.")
        configuration = validate_wifi(configuration)
        if configuration["request_id"] in {revision, self.failed_revision}:
            return
        try:
            apply_wifi(configuration)
        except SetupError as error:
            self.failed_revision = configuration["request_id"]
            self.error = "network_configuration_failed"
            logger.error("%s; customer must submit a new setup attempt.", error)
        else:
            self.failed_revision = None
            self.error = None
            logger.info("Consumer Wi-Fi configuration applied.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if os.geteuid() != 0:
        raise SystemExit("The factory setup service must run as root.")
    try:
        config = UploadConfig(
            cloud_url=os.environ["GHOST_CLOUD_API_URL"],
            gateway_id=UUID(os.environ["GHOST_CLOUD_GATEWAY_ID"]),
            credential=os.environ["GHOST_CLOUD_GATEWAY_CREDENTIAL"],
            router_token=os.environ["GHOST_ROUTER_TOKEN"],
        )
    except (KeyError, ValueError):
        raise SystemExit("Factory device configuration is missing or invalid.") from None
    worker = SetupWorker(config)
    failures = 0
    while True:
        try:
            worker.poll()
        except PermanentUploadError as error:
            raise SystemExit(str(error)) from None
        except UploadError as error:
            failures += 1
            logger.warning("%s", error)
            time.sleep(retry_delay(failures, 10))
        else:
            failures = 0
            time.sleep(5)


if __name__ == "__main__":
    main()
