"""SQLite persistence for the router IDS agent: devices, classification
events (Activity feed), and user accounts (replaces phone-only storage).
"""

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = PROJECT_DIR.parent
DATA_DIR = Path(os.getenv("GHOST_ROUTER_DATA_DIR", WORKSPACE_DIR / "Database"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = os.getenv("GHOST_ROUTER_DB", str(DATA_DIR / "router_ids.db"))
LEGACY_DB_PATHS = (
    PROJECT_DIR / "router_ids.db",
    PROJECT_DIR / "data" / "router_ids.db",
)
if not os.getenv("GHOST_ROUTER_DB") and not Path(DB_PATH).exists():
    import shutil
    for legacy_path in LEGACY_DB_PATHS:
        if legacy_path.exists():
            shutil.copy2(legacy_path, DB_PATH)
            break


def _connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                mac TEXT PRIMARY KEY,
                name TEXT,
                ip_address TEXT,
                first_seen REAL,
                last_seen REAL,
                status TEXT,
                attack_probability REAL,
                blocked INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac TEXT,
                name TEXT,
                ip_address TEXT,
                status TEXT,
                attack_probability REAL,
                timestamp REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                email TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS hidden_devices (mac TEXT PRIMARY KEY, hidden_at REAL NOT NULL)"
        )


def upsert_device(state):
    with _connect() as connection:
        existing = connection.execute(
            "SELECT first_seen, name FROM devices WHERE mac = ?", (state.mac.lower(),)
        ).fetchone()
        first_seen = existing["first_seen"] if existing else state.last_seen
        device_name = state.name
        if (not device_name or device_name == "Unknown device") and existing and existing["name"] and existing["name"] != "Unknown device":
            device_name = existing["name"]
            state.name = device_name
        connection.execute(
            """
            INSERT INTO devices (mac, name, ip_address, first_seen, last_seen, status, attack_probability, blocked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                name=CASE
                    WHEN excluded.name IS NOT NULL AND excluded.name != '' AND excluded.name != 'Unknown device' THEN excluded.name
                    WHEN devices.name IS NOT NULL AND devices.name != '' AND devices.name != 'Unknown device' THEN devices.name
                    ELSE excluded.name
                END,
                ip_address=coalesce(excluded.ip_address, devices.ip_address),
                last_seen=excluded.last_seen,
                status=excluded.status,
                attack_probability=excluded.attack_probability,
                blocked=excluded.blocked
            """,
            (
                state.mac.lower(),
                device_name,
                state.ip_address,
                first_seen,
                state.last_seen,
                state.status,
                state.attack_probability,
                int(state.blocked),
            ),
        )


def log_event(state):
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO events (mac, name, ip_address, status, attack_probability, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                state.mac.lower(),
                state.name,
                state.ip_address,
                state.status,
                state.attack_probability,
                time.time(),
            ),
        )


def recent_events(limit=50):
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def all_devices():
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM devices WHERE mac NOT IN (SELECT mac FROM hidden_devices)"
        ).fetchall()
        return [dict(row) for row in rows]


def delete_device(mac):
    with _connect() as connection:
        connection.execute("DELETE FROM devices WHERE mac = ?", (mac.lower(),))
        connection.execute("DELETE FROM events WHERE mac = ?", (mac.lower(),))
        connection.execute(
            "INSERT INTO hidden_devices (mac, hidden_at) VALUES (?, ?) "
            "ON CONFLICT(mac) DO UPDATE SET hidden_at=excluded.hidden_at",
            (mac.lower(), time.time()),
        )
        return True


def is_device_hidden(mac):
    with _connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM hidden_devices WHERE mac = ?", (mac.lower(),)
        ).fetchone()
        return row is not None


def restore_device(mac):
    with _connect() as connection:
        connection.execute("DELETE FROM hidden_devices WHERE mac = ?", (mac.lower(),))


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def create_account(name, email, password):
    email = email.strip().lower()
    if not name.strip() or not email or len(password) < 8:
        return False, "Use your name, a valid email, and a password with at least 8 characters."

    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)

    try:
        with _connect() as connection:
            connection.execute(
                "INSERT INTO accounts (email, name, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (email, name.strip(), password_hash, salt.hex(), time.time()),
            )
        return True, None
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists."


def verify_account(email, password):
    email = email.strip().lower()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM accounts WHERE email = ?", (email,)
        ).fetchone()

    if row is None:
        return False, "No account matches this email.", None

    salt = bytes.fromhex(row["salt"])
    if _hash_password(password, salt) != row["password_hash"]:
        return False, "Incorrect password.", None

    return True, None, {"name": row["name"], "email": row["email"]}


def change_password(email, current_password, new_password):
    if len(new_password) < 8:
        return False, "The new password must contain at least 8 characters."
    valid, error, _ = verify_account(email, current_password)
    if not valid:
        return False, error
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(new_password, salt)
    with _connect() as connection:
        connection.execute(
            "UPDATE accounts SET password_hash = ?, salt = ? WHERE email = ?",
            (password_hash, salt.hex(), email.strip().lower()),
        )
    return True, None


def create_password_reset(email, token, expires_at):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM accounts WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        if exists is None:
            return False
        connection.execute(
            "INSERT INTO password_reset_tokens (email, token_hash, expires_at) VALUES (?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET token_hash=excluded.token_hash, expires_at=excluded.expires_at",
            (email.strip().lower(), token_hash, expires_at),
        )
    return True


def reset_password(email, token, new_password):
    if len(new_password) < 8:
        return False, "The new password must contain at least 8 characters."
    email = email.strip().lower()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as connection:
        row = connection.execute(
            "SELECT token_hash, expires_at FROM password_reset_tokens WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None or row["expires_at"] < time.time() or not secrets.compare_digest(row["token_hash"], token_hash):
            return False, "The reset code is invalid or expired."
        salt = secrets.token_bytes(16)
        connection.execute(
            "UPDATE accounts SET password_hash = ?, salt = ? WHERE email = ?",
            (_hash_password(new_password, salt), salt.hex(), email),
        )
        connection.execute("DELETE FROM password_reset_tokens WHERE email = ?", (email,))
    return True, None
