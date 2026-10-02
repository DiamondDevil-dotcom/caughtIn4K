"""Signed gateway sessions; account passwords remain on the Pi."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException

SECRET = os.getenv("GHOST_SESSION_SECRET", "") or secrets.token_hex(32)


def check_owner(email):
    allowed = {value.strip().lower() for value in os.getenv("GHOST_ALLOWED_EMAILS", "").split(",") if value.strip()}
    if not allowed:
        raise HTTPException(status_code=503, detail="Configure GHOST_ALLOWED_EMAILS on the gateway first.")
    if email.strip().lower() not in allowed:
        raise HTTPException(status_code=403, detail="This account is not authorized for this gateway.")


def issue_session(email):
    check_owner(email)
    payload = base64.urlsafe_b64encode(json.dumps({
        "email": email, "expires": int(time.time()) + 43200,
    }).encode()).decode()
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session(header):
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to access this gateway.")
    try:
        payload, signature = header[7:].split(".", 1)
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        data = json.loads(base64.urlsafe_b64decode(payload))
        if data["expires"] <= time.time():
            raise ValueError("Expired session")
        check_owner(data["email"])
        return data["email"]
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.") from error
