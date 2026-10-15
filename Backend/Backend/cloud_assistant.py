"""Stateless, text-only OpenAI help; no household tools or device context."""

import http.client
import json
import logging
import os

from fastapi import HTTPException

logger = logging.getLogger(__name__)

INSTRUCTIONS = """You are caughtIn4K's setup and general security help assistant.
Give short, practical answers. You cannot see devices, alerts, accounts, live Pi
status or previous messages, and cannot perform actions. Never claim otherwise.
For setup: the customer signs in with a verified email and scans the one-time
Pi ownership QR to pair a home. Follow the setup instructions delivered with
that Pi; do not invent a Wi-Fi wizard or claim automatic network configuration.
The Pi needs power and network connectivity to contact the cloud. A used QR
cannot be reused. Email my setup QR sends a copy only when the customer still
has a valid unpaired label. For a lost label, contact support; do not promise
self-service order recovery. Already paired customers sign in again.
Do not request passwords, QR contents, tokens, packet captures or credentials.
Do not recommend disabling security or factory-resetting ownership. Distinguish
gateway connectivity from model availability; ask for non-sensitive visible error
text when uncertain. Do not invent product features or diagnoses. Security
alerts are evidence to investigate, not proof a device is compromised.
For unsupported account or hardware problems, direct the user to support.
"""


def answer(message: str) -> dict[str, str]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("GHOST_ASSISTANT_MODEL", "").strip()
    if os.getenv("GHOST_ASSISTANT_ENABLED") != "true" or not key or not model:
        raise HTTPException(503, "AI help is not configured yet.")
    payload = json.dumps({
        "model": model,
        "instructions": INSTRUCTIONS,
        "input": message.strip(),
        "max_output_tokens": 500,
        "store": False,
    }).encode("utf-8")
    connection = http.client.HTTPSConnection("api.openai.com", timeout=20)
    try:
        connection.request("POST", "/v1/responses", body=payload, headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        })
        response = connection.getresponse()
        if response.status != 200:
            logger.warning("Assistant provider returned HTTP %s.", response.status)
            raise HTTPException(503, "AI help is temporarily unavailable. Try again later.")
        raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError("Oversized assistant response")
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise ValueError("Incomplete assistant response")
        output = result.get("output")
        if not isinstance(output, list):
            raise ValueError("Invalid assistant output")
        parts = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                raise ValueError("Invalid assistant message")
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if not isinstance(text, str):
                        raise ValueError("Invalid assistant text")
                    parts.append(text)
        reply = "\n".join(parts).strip()
        if not reply or len(reply) > 8000:
            raise ValueError("Invalid assistant reply length")
        return {"reply": reply}
    except (OSError, http.client.HTTPException, ValueError):
        logger.warning("Assistant request failed or returned an invalid response.")
        raise HTTPException(503, "AI help is temporarily unavailable. Try again later.") from None
    finally:
        connection.close()
