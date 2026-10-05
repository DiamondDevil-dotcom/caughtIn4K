CREATE SCHEMA IF NOT EXISTS caughtin4k;

CREATE TABLE caughtin4k.accounts (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE CHECK (email = lower(btrim(email)) AND email <> ''),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_algorithm TEXT NOT NULL CHECK (password_algorithm = 'pbkdf2_sha256'),
    password_iterations INTEGER NOT NULL CHECK (password_iterations >= 100000),
    session_version BIGINT NOT NULL DEFAULT 0 CHECK (session_version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE caughtin4k.households (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    owner_account_id UUID NOT NULL REFERENCES caughtin4k.accounts(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE caughtin4k.household_members (
    household_id UUID NOT NULL REFERENCES caughtin4k.households(id),
    account_id UUID NOT NULL REFERENCES caughtin4k.accounts(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (household_id, account_id)
);
CREATE UNIQUE INDEX one_owner_per_household
    ON caughtin4k.household_members(household_id) WHERE role = 'owner';
CREATE INDEX memberships_by_account ON caughtin4k.household_members(account_id);

CREATE TABLE caughtin4k.gateways (
    id UUID PRIMARY KEY,
    household_id UUID REFERENCES caughtin4k.households(id),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    credential_hash TEXT NOT NULL UNIQUE CHECK (credential_hash ~ '^[0-9a-f]{64}$'),
    pairing_code_hash TEXT UNIQUE CHECK (pairing_code_hash ~ '^[0-9a-f]{64}$'),
    pairing_expires_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((pairing_code_hash IS NULL) = (pairing_expires_at IS NULL)),
    CHECK (household_id IS NULL OR pairing_code_hash IS NULL)
);
CREATE INDEX gateways_by_household ON caughtin4k.gateways(household_id);

CREATE TABLE caughtin4k.household_invites (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    household_id UUID NOT NULL REFERENCES caughtin4k.households(id),
    email TEXT NOT NULL CHECK (email = lower(btrim(email)) AND email <> ''),
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    created_by UUID NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (household_id, created_by)
        REFERENCES caughtin4k.household_members(household_id, account_id),
    CHECK (expires_at > created_at)
);

CREATE TABLE caughtin4k.password_reset_tokens (
    account_id UUID PRIMARY KEY REFERENCES caughtin4k.accounts(id),
    token_hash TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (expires_at > created_at)
);

-- This private schema has no client policies. Only the trusted backend connects.
REVOKE ALL ON SCHEMA caughtin4k FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA caughtin4k FROM PUBLIC;
ALTER TABLE caughtin4k.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE caughtin4k.households ENABLE ROW LEVEL SECURITY;
ALTER TABLE caughtin4k.household_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE caughtin4k.gateways ENABLE ROW LEVEL SECURITY;
ALTER TABLE caughtin4k.household_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE caughtin4k.password_reset_tokens ENABLE ROW LEVEL SECURITY;
