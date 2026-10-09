"""Customer account email proof, recovery and shared database-backed throttling."""

import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from uuid import UUID

import qrcode
from fastapi import HTTPException

import cloud_accounts as accounts
from cloud_database import connect
from cloud_gateways import secret_hash

logger = logging.getLogger(__name__)


def limit(key: str, secret: str, maximum: int, seconds: int) -> None:
    digest = hmac.new(secret.encode(), key.encode(), hashlib.sha256).hexdigest()
    with connect() as connection:
        row = connection.execute(
            "INSERT INTO caughtin4k.request_limits (key_hash) VALUES (%s) "
            "ON CONFLICT (key_hash) DO UPDATE SET "
            "attempts = CASE WHEN caughtin4k.request_limits.window_started_at "
            "< clock_timestamp() - %s * interval '1 second' THEN 1 "
            "ELSE caughtin4k.request_limits.attempts + 1 END, "
            "window_started_at = CASE WHEN caughtin4k.request_limits.window_started_at "
            "< clock_timestamp() - %s * interval '1 second' THEN clock_timestamp() "
            "ELSE caughtin4k.request_limits.window_started_at END RETURNING attempts",
            (digest, seconds, seconds),
        ).fetchone()
        connection.execute(
            "DELETE FROM caughtin4k.request_limits "
            "WHERE window_started_at < clock_timestamp() - interval '1 day'",
        )
    if row["attempts"] > maximum:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.",
                            headers={"Retry-After": str(seconds)})


def mail_settings() -> tuple[str, int, str, str, str]:
    host = os.getenv("GHOST_SMTP_HOST", "")
    username = os.getenv("GHOST_SMTP_USERNAME", "")
    password = os.getenv("GHOST_SMTP_PASSWORD", "")
    sender = os.getenv("GHOST_SMTP_FROM", username)
    try:
        port = int(os.getenv("GHOST_SMTP_PORT", "587"))
    except ValueError:
        raise ValueError("Configure the cloud SMTP TLS port.") from None
    if not host or not sender or port not in {465, 587} or bool(username) != bool(password):
        raise ValueError("Configure cloud SMTP with TLS and matching authentication settings.")
    if any("\n" in value or "\r" in value for value in (sender, username)):
        raise ValueError("Cloud SMTP settings are invalid.")
    return host, port, username, password, sender


def _send_message(message: EmailMessage) -> None:
    try:
        host, port, username, password, sender = mail_settings()
        message["From"] = sender
        context = ssl.create_default_context()
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=10, context=context)
        else:
            smtp = smtplib.SMTP(host, port, timeout=10)
        with smtp:
            if port == 587:
                smtp.starttls(context=context)
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except (ValueError, OSError, smtplib.SMTPException):
        logger.error("Cloud account email delivery failed.")
        raise HTTPException(status_code=503, detail="Account email could not be delivered. Try again later.") from None


def send_code(email: str, code: str, purpose: str) -> None:
    message = EmailMessage()
    message["Subject"] = f"caughtIn4K {purpose}"
    message["To"] = email
    message.set_content(
        f"Your caughtIn4K {purpose} code is {code}.\n"
        "It expires in 15 minutes. If you did not request it, ignore this email."
    )
    _send_message(message)


def email_setup_qr(account_id: UUID, gateway_id: UUID, pairing_code: str) -> dict:
    code = pairing_code.strip()
    if not 1 <= len(code) <= 256:
        raise HTTPException(status_code=400, detail="Gateway setup code is invalid or unavailable.")
    with connect() as connection:
        row = connection.execute(
            "SELECT a.email, g.pairing_expires_at FROM caughtin4k.gateways g "
            "JOIN caughtin4k.accounts a ON a.id = %s "
            "WHERE g.id = %s AND g.pairing_code_hash = %s "
            "AND g.pairing_expires_at > now() AND g.household_id IS NULL "
            "AND g.revoked_at IS NULL AND a.email_verified_at IS NOT NULL",
            (account_id, gateway_id, secret_hash(code)),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail="Gateway setup code is invalid or unavailable.")
    payload = json.dumps({
        "version": 1, "gateway_id": str(gateway_id), "pairing_code": code,
    }, separators=(",", ":"))
    image = qrcode.make(payload)
    with io.BytesIO() as buffer:
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
    message = EmailMessage()
    message["Subject"] = "caughtIn4K Pi setup QR"
    message["To"] = row["email"]
    message.set_content(
        "You requested a copy of your new Pi's setup label.\n"
        "Save the attached PNG and choose 'QR from gallery' in the app, "
        "or use its setup text on the website.\n"
        f"Expires: {row['pairing_expires_at'].isoformat()}.\n"
        "This one-time ownership label stops working after pairing. "
        "Keep it private and do not forward it. This email does not pair or reset a Pi.\n\n"
        f"Setup text:\n{payload}\n"
    )
    message.add_attachment(png, maintype="image", subtype="png", filename="caughtin4k-pi-setup.png")
    _send_message(message)
    return {"success": True, "message": "Setup QR sent to your verified account email. Check your inbox."}


def send_verification(account_id: UUID) -> dict:
    code = secrets.token_urlsafe(24)
    with connect() as connection:
        row = connection.execute(
            "SELECT email, email_verified_at FROM caughtin4k.accounts WHERE id = %s FOR UPDATE",
            (account_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Account is unavailable. Sign in again.")
        if row["email_verified_at"] is not None:
            return {"success": True, "message": "Email is already verified."}
        connection.execute(
            "INSERT INTO caughtin4k.email_verification_tokens (account_id, token_hash, expires_at) "
            "VALUES (%s, %s, now() + interval '15 minutes') ON CONFLICT (account_id) "
            "DO UPDATE SET token_hash = excluded.token_hash, expires_at = excluded.expires_at, attempts = 0",
            (account_id, secret_hash(code)),
        )
    try:
        send_code(row["email"], code, "email verification")
    except HTTPException:
        with connect() as connection:
            connection.execute(
                "DELETE FROM caughtin4k.email_verification_tokens WHERE account_id = %s AND token_hash = %s",
                (account_id, secret_hash(code)),
            )
        raise
    return {"success": True, "message": "Verification code sent. Check your email."}


def _consume(account_id: UUID, code: str, *, verification: bool, password: str = "") -> dict:
    if not verification:
        accounts.validate_password(password)
        salt = secrets.token_bytes(16)
        digest = accounts.password_hash(password, salt)
    table = "email_verification_tokens" if verification else "password_reset_tokens"
    valid = False
    with connect() as connection:
        # Account-first locking is shared with password changes and code issuance.
        connection.execute("SELECT id FROM caughtin4k.accounts WHERE id = %s FOR UPDATE", (account_id,))
        row = connection.execute(
            f"SELECT token_hash, attempts, expires_at > now() AS live "
            f"FROM caughtin4k.{table} WHERE account_id = %s FOR UPDATE",
            (account_id,),
        ).fetchone()
        if row and row["live"] and row["attempts"] < 5:
            valid = hmac.compare_digest(row["token_hash"], secret_hash(code))
            if valid:
                if verification:
                    connection.execute(
                        "UPDATE caughtin4k.accounts SET email_verified_at = now() WHERE id = %s",
                        (account_id,),
                    )
                else:
                    connection.execute(
                        "UPDATE caughtin4k.accounts SET password_hash = %s, password_salt = %s, "
                        "password_iterations = %s, session_version = session_version + 1 WHERE id = %s",
                        (digest, salt.hex(), accounts.PASSWORD_ITERATIONS, account_id),
                    )
                connection.execute(f"DELETE FROM caughtin4k.{table} WHERE account_id = %s", (account_id,))
            else:
                connection.execute(
                    f"UPDATE caughtin4k.{table} SET attempts = attempts + 1 WHERE account_id = %s",
                    (account_id,),
                )
    # Raise outside the transaction so failed-attempt counts commit.
    if not valid:
        raise HTTPException(status_code=400, detail="Code is invalid, expired, or unavailable.")
    return {"success": True}


def verify_email(account_id: UUID, code: str) -> dict:
    return _consume(account_id, code, verification=True)


def request_reset(email: str) -> dict:
    email = accounts.normalize_email(email)
    code = secrets.token_urlsafe(24)
    with connect() as connection:
        row = connection.execute(
            "SELECT id FROM caughtin4k.accounts WHERE email = %s FOR UPDATE", (email,),
        ).fetchone()
        if row:
            connection.execute(
                "INSERT INTO caughtin4k.password_reset_tokens (account_id, token_hash, expires_at) "
                "VALUES (%s, %s, now() + interval '15 minutes') ON CONFLICT (account_id) "
                "DO UPDATE SET token_hash = excluded.token_hash, expires_at = excluded.expires_at, "
                "attempts = 0, created_at = now()",
                (row["id"], secret_hash(code)),
            )
    # Same delivery behavior for missing accounts avoids an account-existence oracle.
    try:
        send_code(email, code, "password reset")
    except HTTPException:
        if row:
            with connect() as connection:
                connection.execute(
                    "DELETE FROM caughtin4k.password_reset_tokens WHERE account_id = %s AND token_hash = %s",
                    (row["id"], secret_hash(code)),
                )
        raise
    return {"success": True, "message": "If the account exists, a reset code was sent."}


def reset_password(email: str, code: str, password: str) -> dict:
    email = accounts.normalize_email(email)
    accounts.validate_password(password)
    with connect() as connection:
        row = connection.execute("SELECT id FROM caughtin4k.accounts WHERE email = %s", (email,)).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Code is invalid, expired, or unavailable.")
    return _consume(row["id"], code, verification=False, password=password)


def change_password(account_id: UUID, current: str, password: str) -> dict:
    accounts.validate_password(password)
    salt = secrets.token_bytes(16)
    digest = accounts.password_hash(password, salt)
    with connect() as connection:
        row = connection.execute(
            "SELECT password_hash, password_salt, password_iterations FROM caughtin4k.accounts "
            "WHERE id = %s FOR UPDATE", (account_id,),
        ).fetchone()
        if not row or not hmac.compare_digest(
            accounts.password_hash(current, bytes.fromhex(row["password_salt"]), row["password_iterations"]),
            row["password_hash"],
        ):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        connection.execute(
            "UPDATE caughtin4k.accounts SET password_hash = %s, password_salt = %s, "
            "password_iterations = %s, session_version = session_version + 1 WHERE id = %s",
            (digest, salt.hex(), accounts.PASSWORD_ITERATIONS, account_id),
        )
        connection.execute("DELETE FROM caughtin4k.password_reset_tokens WHERE account_id = %s", (account_id,))
    return {"success": True, "message": "Password changed. Sign in again."}
