"""Opt-in command worker. Never imports capture/training or executes shell payloads."""

from __future__ import annotations

import json
import logging
import os
import re
from ipaddress import IPv4Address
import time
import urllib.request
from datetime import datetime, timezone
from uuid import UUID

from cloud_uploader import (
    NoRedirect, PermanentUploadError, UploadConfig, UploadError, endpoint_json,
    retry_delay,
)

logger = logging.getLogger(__name__)


def validate_command(command: object) -> dict:
    if not isinstance(command, dict):
        raise PermanentUploadError("Cloud command contract is invalid.")
    required = {"command_id", "action", "mac", "expires_at"}
    if command.get("action") == "register":
        required |= {"device_name", "ip_address"}
    if set(command) != required:
        raise PermanentUploadError("Cloud command contract is invalid.")
    try:
        UUID(command["command_id"])
        deadline = datetime.fromisoformat(command["expires_at"])
        if (
            command["action"] not in {"block", "unblock", "register", "remove", "train"}
            or (command["action"] == "train" and command["mac"] is not None)
            or (command["action"] != "train" and (
                not isinstance(command["mac"], str)
                or re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", command["mac"]) is None
            ))
            or deadline.tzinfo is None
        ):
            raise ValueError
        if command["action"] == "register":
            name, ip = command["device_name"], command["ip_address"]
            if not isinstance(name, str) or not 1 <= len(name) <= 200 or name != name.strip() or not isinstance(ip, str):
                raise ValueError
            if ip:
                IPv4Address(ip)
    except (ValueError, TypeError, AttributeError):
        raise PermanentUploadError("Cloud command contract is invalid.") from None
    return command


def apply_local(config: UploadConfig, opener, command: dict) -> dict:
    if datetime.fromisoformat(command["expires_at"]) <= datetime.now(timezone.utc):
        return {"success": False, "result_code": "expired"}
    try:
        result = endpoint_json(opener, urllib.request.Request(
            config.local_url.rstrip("/") + "/cloud-agent/control",
            data=json.dumps(command).encode("utf-8"),
            headers={"X-Gateway-Token": config.router_token, "Content-Type": "application/json"},
            method="POST",
        ), "Local Pi control")
    except PermanentUploadError as error:
        logger.error("%s", error)
        return {"success": False, "result_code": "local_rejected"}
    except UploadError as error:
        logger.error("%s; execution outcome is unconfirmed.", error)
        # A timeout can occur after firewall enforcement. Never retry the action.
        return {"success": False, "result_code": "local_unreachable"}
    if (
        type(result.get("success")) is not bool
        or result.get("result_code") not in {
            "applied", "enforcement_failed", "expired", "local_unreachable", "local_rejected",
        }
        or result["success"] != (result["result_code"] == "applied")
    ):
        raise PermanentUploadError("Local Pi control returned an invalid acknowledgement.")
    return {"success": result["success"], "result_code": result["result_code"]}


class ControlWorker:
    def __init__(self, config: UploadConfig, opener=None):
        self.config = config
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.pending_result: tuple[dict, dict] | None = None

    def poll(self) -> None:
        config = self.config
        headers = {"X-Gateway-Credential": config.credential, "Content-Type": "application/json"}
        if config.staging_token:
            headers["X-Cloud-Staging-Token"] = config.staging_token
        url = f"{config.cloud_url.rstrip('/')}/cloud/gateways/{config.gateway_id}/commands"
        if self.pending_result is None:
            response = endpoint_json(self.opener, urllib.request.Request(
                url + "/next", data=b"", headers=headers, method="POST",
            ), "Cloud command delivery")
            if "command" not in response:
                raise PermanentUploadError("Cloud command delivery returned an invalid response.")
            if response["command"] is None:
                return
            command = validate_command(response["command"])
            result = apply_local(config, self.opener, command)
            self.pending_result = (command, result)
        command, result = self.pending_result
        acknowledgement = endpoint_json(self.opener, urllib.request.Request(
            f"{url}/{command['command_id']}/result",
            data=json.dumps(result).encode("utf-8"), headers=headers, method="PUT",
        ), "Cloud command acknowledgement")
        if acknowledgement.get("success") is not True:
            raise PermanentUploadError("Cloud did not acknowledge the command result.")
        logger.info("Network command result recorded: %s.", result["result_code"])
        self.pending_result = None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if os.getenv("GHOST_CLOUD_CONTROL_ENABLED", "false").lower() != "true":
        raise SystemExit("Cloud network controls are disabled.")
    try:
        config = UploadConfig(
            cloud_url=os.getenv("GHOST_CLOUD_API_URL", ""),
            gateway_id=UUID(os.getenv("GHOST_CLOUD_GATEWAY_ID", "")),
            credential=os.getenv("GHOST_CLOUD_GATEWAY_CREDENTIAL", ""),
            router_token=os.getenv("GHOST_ROUTER_TOKEN", ""),
            staging_token=os.getenv("GHOST_CLOUD_STAGING_TOKEN", ""),
        )
    except ValueError:
        raise SystemExit("Invalid cloud command configuration. Check private gateway settings.") from None
    worker = ControlWorker(config)
    failures = 0
    try:
        while True:
            try:
                worker.poll()
            except PermanentUploadError:
                raise
            except UploadError as error:
                failures += 1
                logger.warning("%s", error)
                time.sleep(retry_delay(failures, 10))
            else:
                failures = 0
                time.sleep(10)
    except PermanentUploadError as error:
        raise SystemExit(str(error)) from None
    except KeyboardInterrupt:
        logger.info("Cloud command worker stopped.")


if __name__ == "__main__":
    main()
