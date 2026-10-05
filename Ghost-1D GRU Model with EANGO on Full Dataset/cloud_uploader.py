"""Separate outbound metadata uploader. Does not import Torch or start training."""

from __future__ import annotations

import json
import argparse
import logging
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 1024 * 1024


class UploadError(RuntimeError):
    """Safe error without credentials or response body."""


class PermanentUploadError(UploadError):
    """Configuration or authorization needs operator intervention."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class UploadConfig:
    cloud_url: str
    gateway_id: UUID
    credential: str
    router_token: str
    local_url: str = "http://127.0.0.1:8001"
    interval: int = 30
    staging_token: str = ""

    def __post_init__(self):
        cloud = urlsplit(self.cloud_url)
        if (
            cloud.scheme != "https" or not cloud.hostname or cloud.username or cloud.password
            or cloud.query or cloud.fragment or cloud.path not in ("", "/")
        ):
            raise ValueError("Use an HTTPS cloud origin without credentials, path, or query.")
        local = urlsplit(self.local_url)
        if (
            local.scheme != "http" or local.hostname != "127.0.0.1"
            or local.username or local.password or local.query or local.fragment
            or local.path not in ("", "/")
        ):
            raise ValueError("Local router URL must use http://127.0.0.1 with a port.")
        if not 32 <= len(self.credential) <= 256 or not self.router_token:
            raise ValueError("Configure the unique cloud gateway credential and private router token.")
        if not 10 <= self.interval <= 60:
            raise ValueError("Upload interval must be between 10 and 60 seconds.")
        if self.staging_token and (
            not 32 <= len(self.staging_token) <= 256
            or any(character.isspace() for character in self.staging_token)
        ):
            raise ValueError("Use a valid private staging token without whitespace.")


def request_json(opener, request: urllib.request.Request) -> dict:
    try:
        with opener.open(request, timeout=60) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise PermanentUploadError("Metadata response exceeds the supported size.")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise PermanentUploadError("Metadata endpoint returned an invalid response.")
        return result
    except urllib.error.HTTPError as error:
        code = error.code
        reason = None
        if code == 401:
            try:
                payload = json.loads(error.read(MAX_RESPONSE_BYTES + 1))
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if detail == "Private cloud staging access required.":
                    reason = "Staging access token rejected; check GHOST_CLOUD_STAGING_TOKEN."
                elif detail == "Gateway credential is invalid.":
                    reason = "Gateway machine credential rejected; check gateway ID and credential."
            except (ValueError, OSError):
                pass
        error.close()
        if reason:
            raise PermanentUploadError(f"HTTP 401: {reason}") from None
        if code in {400, 401, 403, 404, 413, 422} or 300 <= code < 400:
            raise PermanentUploadError(f"Metadata endpoint returned HTTP {code}; check configuration.") from None
        raise UploadError(f"Metadata endpoint returned HTTP {code}; retrying.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UploadError("Metadata connection failed; retrying.") from None
    except (ValueError, UnicodeError):
        raise PermanentUploadError("Metadata endpoint returned invalid JSON.") from None


def endpoint_json(opener, request: urllib.request.Request, stage: str) -> dict:
    try:
        return request_json(opener, request)
    except PermanentUploadError as error:
        raise PermanentUploadError(f"{stage}: {error}") from None
    except UploadError as error:
        raise UploadError(f"{stage}: {error}") from None


def upload_once(config: UploadConfig, opener=None) -> None:
    if opener is None:
        # Neither local credentials nor cloud credentials may follow redirects/proxy env.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    snapshot = endpoint_json(opener, urllib.request.Request(
        config.local_url.rstrip("/") + "/cloud-agent/snapshot",
        headers={"X-Gateway-Token": config.router_token},
    ), "Local Pi snapshot")
    if set(snapshot) != {"observed_at", "devices", "alerts", "model"}:
        raise PermanentUploadError("Local snapshot does not match the metadata-only contract.")
    headers = {"X-Gateway-Credential": config.credential, "Content-Type": "application/json"}
    if config.staging_token:
        headers["X-Cloud-Staging-Token"] = config.staging_token
    response = endpoint_json(opener, urllib.request.Request(
        f"{config.cloud_url.rstrip('/')}/cloud/gateways/{config.gateway_id}/snapshot",
        data=json.dumps(snapshot, allow_nan=False).encode("utf-8"),
        headers=headers,
        method="PUT",
    ), "Cloud staging upload")
    if response.get("success") is not True or type(response.get("snapshot_updated")) is not bool:
        raise PermanentUploadError("Cloud endpoint did not acknowledge the metadata upload.")


def retry_delay(failures: int, interval: int) -> float:
    return min(300, interval * 2 ** min(max(failures - 1, 0), 5)) + random.uniform(0, 5)


def run(config: UploadConfig) -> None:
    failures = 0
    while True:
        try:
            upload_once(config)
        except PermanentUploadError:
            raise
        except UploadError as error:
            failures += 1
            logger.warning("%s", error)
            time.sleep(retry_delay(failures, config.interval))
        else:
            if failures:
                logger.info("Cloud metadata connection recovered.")
            failures = 0
            time.sleep(config.interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Outbound Pi metadata upload, separate from FL.")
    parser.add_argument("--once", action="store_true", help="Upload once and report acknowledgement.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if os.getenv("GHOST_CLOUD_UPLOAD_ENABLED", "false").lower() != "true":
        raise SystemExit("Cloud uploader is disabled; existing Pi operation is unchanged.")
    try:
        config = UploadConfig(
            cloud_url=os.getenv("GHOST_CLOUD_API_URL", ""),
            gateway_id=UUID(os.getenv("GHOST_CLOUD_GATEWAY_ID", "")),
            credential=os.getenv("GHOST_CLOUD_GATEWAY_CREDENTIAL", ""),
            router_token=os.getenv("GHOST_ROUTER_TOKEN", ""),
            staging_token=os.getenv("GHOST_CLOUD_STAGING_TOKEN", ""),
        )
    except ValueError:
        raise SystemExit("Invalid cloud uploader configuration. Check private gateway settings.") from None
    try:
        if args.once:
            upload_once(config)
            logger.info("Cloud acknowledged the metadata upload.")
        else:
            run(config)
    except PermanentUploadError as error:
        raise SystemExit(str(error)) from None
    except UploadError as error:
        raise SystemExit(str(error)) from None
    except KeyboardInterrupt:
        logger.info("Cloud uploader stopped.")


if __name__ == "__main__":
    main()
