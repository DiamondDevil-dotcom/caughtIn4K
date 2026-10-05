"""Validation for provisioning an outbound HTTPS cloud origin."""

from urllib.parse import urlsplit


def validate_cloud_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path not in ("", "/")
        or any(character.isspace() for character in value)
    ):
        raise ValueError("Use an HTTPS origin without credentials, path, or query.")
    # Validate the port as well, including malformed/non-numeric ports.
    parsed.port
    return value.rstrip("/")
