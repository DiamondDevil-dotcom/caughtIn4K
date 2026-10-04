"""SQLite persistence for the router IDS agent: devices, classification
events (Activity feed), and user accounts (replaces phone-only storage).
"""

import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
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


@contextmanager
def _connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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
                blocked INTEGER,
                household_id INTEGER
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
                timestamp REAL,
                household_id INTEGER
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
                expires_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS hidden_devices (mac TEXT PRIMARY KEY, hidden_at REAL NOT NULL)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS households (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                owner_email TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS household_members (
                email TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
                joined_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS household_invites (
                token_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
                created_by TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )

        for table, column, definition in (
            ("devices", "household_id", "INTEGER"),
            ("events", "household_id", "INTEGER"),
            ("password_reset_tokens", "attempts", "INTEGER NOT NULL DEFAULT 0"),
        ):
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _normalize_email(email):
    return email.strip().lower()


def household_role(email):
    with _connect() as connection:
        row = connection.execute(
            "SELECT role FROM household_members WHERE email = ?",
            (_normalize_email(email),),
        ).fetchone()
    return row["role"] if row else None


def _has_household(connection):
    return connection.execute("SELECT 1 FROM households WHERE id = 1").fetchone() is not None


def _assign_existing_data(connection):
    connection.execute("UPDATE devices SET household_id = 1 WHERE household_id IS NULL")
    connection.execute("UPDATE events SET household_id = 1 WHERE household_id IS NULL")


def claim_gateway(email, pairing_code):
    email = _normalize_email(email)
    expected_code = os.getenv("GHOST_GATEWAY_PAIRING_CODE", "")
    if not expected_code:
        return False, "Gateway pairing is not configured on the Pi.", None
    if not secrets.compare_digest(pairing_code.strip(), expected_code):
        return False, "The gateway setup code is invalid.", None

    with _connect() as connection:
        account = connection.execute(
            "SELECT 1 FROM accounts WHERE email = ?", (email,)
        ).fetchone()
        if account is None:
            return False, "Sign in to an existing account before claiming the gateway.", None
        if _has_household(connection):
            return False, "This gateway has already been claimed.", None

        connection.execute(
            "INSERT INTO households (id, owner_email, created_at) VALUES (1, ?, ?)",
            (email, time.time()),
        )
        connection.execute(
            "INSERT INTO household_members (email, role, joined_at) VALUES (?, 'owner', ?)",
            (email, time.time()),
        )
        _assign_existing_data(connection)
    return True, None, "owner"


def create_invite(created_by, email, role):
    email = _normalize_email(email)
    created_by = _normalize_email(created_by)
    role = role.strip().lower()
    if role not in {"admin", "member"}:
        return False, "Invited role must be admin or member.", None
    if not email or "@" not in email:
        return False, "Enter a valid email address.", None

    code = secrets.token_urlsafe(32)
    with _connect() as connection:
        inviter = connection.execute(
            "SELECT role FROM household_members WHERE email = ?", (created_by,)
        ).fetchone()
        if inviter is None or inviter["role"] not in {"owner", "admin"}:
            return False, "Only a household owner or admin can invite members.", None
        if role == "admin" and inviter["role"] != "owner":
            return False, "Only the household owner can invite an admin.", None
        existing_account = connection.execute(
            "SELECT 1 FROM accounts WHERE email = ?", (email,)
        ).fetchone()
        if existing_account and connection.execute(
            "SELECT 1 FROM household_members WHERE email = ?", (email,)
        ).fetchone():
            return False, "This account is already a household member.", None
        connection.execute("DELETE FROM household_invites WHERE expires_at <= ?", (time.time(),))
        connection.execute(
            "INSERT INTO household_invites (token_hash, email, role, created_by, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                hashlib.sha256(code.encode("utf-8")).hexdigest(),
                email,
                role,
                created_by,
                time.time() + 24 * 60 * 60,
            ),
        )
    return True, None, {"email": email, "role": role, "invite_code": code}


def upsert_device(state):
    with _connect() as connection:
        household_id = 1 if _has_household(connection) else None
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
            INSERT INTO devices (mac, name, ip_address, first_seen, last_seen, status, attack_probability, blocked, household_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                blocked=excluded.blocked,
                household_id=coalesce(devices.household_id, excluded.household_id)
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
                household_id,
            ),
        )


def log_event(state):
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO events (mac, name, ip_address, status, attack_probability, timestamp, household_id)
            VALUES (?, ?, ?, ?, ?, ?, (SELECT id FROM households WHERE id = 1))
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
            "SELECT * FROM events WHERE household_id = 1 ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def all_devices():
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM devices WHERE household_id = 1 AND mac NOT IN (SELECT mac FROM hidden_devices)"
        ).fetchall()
        return [dict(row) for row in rows]


def is_household_device(mac):
    with _connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM devices WHERE mac = ? AND household_id = 1",
            (mac.strip().lower(),),
        ).fetchone()
    return row is not None


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


def create_account(name, email, password, access_code=""):
    email = _normalize_email(email)
    if not name.strip() or not email or len(password) < 8:
        return False, "Use your name, a valid email, and a password with at least 8 characters."

    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)
    access_code = access_code.strip()
    invite_hash = hashlib.sha256(access_code.encode("utf-8")).hexdigest()
    pairing_code = os.getenv("GHOST_GATEWAY_PAIRING_CODE", "")

    with _connect() as connection:
        if connection.execute(
            "SELECT 1 FROM accounts WHERE email = ?", (email,)
        ).fetchone():
            if _has_household(connection):
                return False, "This email already has an account. Sign in with the invitation code."
            return False, "An account with this email already exists."

        if _has_household(connection):
            invite = connection.execute(
                "SELECT email, role, expires_at FROM household_invites WHERE token_hash = ?",
                (invite_hash,),
            ).fetchone()
            if (
                invite is None
                or invite["expires_at"] <= time.time()
                or invite["email"] != email
            ):
                return False, "A valid household invitation is required to create an account."
            connection.execute(
                "INSERT INTO accounts (email, name, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (email, name.strip(), password_hash, salt.hex(), time.time()),
            )
            connection.execute(
                "INSERT INTO household_members (email, role, joined_at) VALUES (?, ?, ?)",
                (email, invite["role"], time.time()),
            )
            connection.execute(
                "DELETE FROM household_invites WHERE token_hash = ?", (invite_hash,)
            )
            return True, None

        if not pairing_code or not secrets.compare_digest(access_code, pairing_code):
            return False, "Use the one-time gateway setup code to create the owner account."
        connection.execute(
            "INSERT INTO accounts (email, name, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
            (email, name.strip(), password_hash, salt.hex(), time.time()),
        )
        connection.execute(
            "INSERT INTO households (id, owner_email, created_at) VALUES (1, ?, ?)",
            (email, time.time()),
        )
        connection.execute(
            "INSERT INTO household_members (email, role, joined_at) VALUES (?, 'owner', ?)",
            (email, time.time()),
        )
        _assign_existing_data(connection)
    return True, None


def accept_invite(email, access_code):
    email = _normalize_email(email)
    token_hash = hashlib.sha256(access_code.strip().encode("utf-8")).hexdigest()
    with _connect() as connection:
        if connection.execute(
            "SELECT 1 FROM accounts WHERE email = ?", (email,)
        ).fetchone() is None:
            return False, "Sign in to an existing account to accept this invitation.", None
        invite = connection.execute(
            "SELECT email, role, expires_at FROM household_invites WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if invite is None or invite["expires_at"] <= time.time() or invite["email"] != email:
            return False, "A valid household invitation is required.", None
        connection.execute(
            "INSERT INTO household_members (email, role, joined_at) VALUES (?, ?, ?)",
            (email, invite["role"], time.time()),
        )
        connection.execute(
            "DELETE FROM household_invites WHERE token_hash = ?", (token_hash,)
        )
    return True, None, invite["role"]


def verify_account(email, password):
    email = _normalize_email(email)
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM accounts WHERE email = ?", (email,)
        ).fetchone()

    if row is None:
        return False, "No account matches this email.", None

    salt = bytes.fromhex(row["salt"])
    if not secrets.compare_digest(_hash_password(password, salt), row["password_hash"]):
        return False, "Incorrect password.", None

    return True, None, {
        "name": row["name"],
        "email": row["email"],
        "household_role": household_role(email),
    }


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
            "INSERT INTO password_reset_tokens (email, token_hash, expires_at, attempts) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(email) DO UPDATE SET token_hash=excluded.token_hash, expires_at=excluded.expires_at, attempts=0",
            (email.strip().lower(), token_hash, expires_at),
        )
    return True


def delete_password_reset(email):
    with _connect() as connection:
        connection.execute(
            "DELETE FROM password_reset_tokens WHERE email = ?",
            (_normalize_email(email),),
        )


def reset_password(email, token, new_password):
    if len(new_password) < 8:
        return False, "The new password must contain at least 8 characters."
    email = email.strip().lower()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as connection:
        row = connection.execute(
            "SELECT token_hash, expires_at, attempts FROM password_reset_tokens WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None or row["expires_at"] < time.time() or row["attempts"] >= 5:
            return False, "The reset code is invalid or expired."
        if not secrets.compare_digest(row["token_hash"], token_hash):
            attempts = row["attempts"] + 1
            if attempts >= 5:
                connection.execute("DELETE FROM password_reset_tokens WHERE email = ?", (email,))
            else:
                connection.execute(
                    "UPDATE password_reset_tokens SET attempts = ? WHERE email = ?",
                    (attempts, email),
                )
            return False, "The reset code is invalid or expired."
        salt = secrets.token_bytes(16)
        connection.execute(
            "UPDATE accounts SET password_hash = ?, salt = ? WHERE email = ?",
            (_hash_password(new_password, salt), salt.hex(), email),
        )
        connection.execute("DELETE FROM password_reset_tokens WHERE email = ?", (email,))
    return True, None
