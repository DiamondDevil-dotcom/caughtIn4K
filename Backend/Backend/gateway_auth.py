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


def issue_session(email):
    email = email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="An account email is required.")
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
        email = data["email"]
        if not isinstance(email, str) or not email.strip():
            raise ValueError("Session has no account identity")
        return email.strip().lower()
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.") from error
