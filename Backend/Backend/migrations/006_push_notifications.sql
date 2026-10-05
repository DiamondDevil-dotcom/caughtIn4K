CREATE TABLE caughtin4k.push_installations (
    installation_id UUID PRIMARY KEY,
    secret_hash TEXT NOT NULL CHECK (secret_hash ~ '^[0-9a-f]{64}$'),
    account_id UUID NOT NULL REFERENCES caughtin4k.accounts(id) ON DELETE CASCADE,
    session_version BIGINT NOT NULL,
    token TEXT NOT NULL UNIQUE CHECK (length(token) BETWEEN 20 AND 4096),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE caughtin4k.push_deliveries (
    id BIGSERIAL PRIMARY KEY,
    installation_id UUID NOT NULL REFERENCES caughtin4k.push_installations(installation_id) ON DELETE CASCADE,
    gateway_id UUID NOT NULL REFERENCES caughtin4k.gateways(id) ON DELETE CASCADE,
    household_id UUID NOT NULL REFERENCES caughtin4k.households(id),
    account_id UUID NOT NULL REFERENCES caughtin4k.accounts(id) ON DELETE CASCADE,
    event_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('WARNING', 'ATTACK', 'ALERT', 'BLOCKED')),
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (installation_id, gateway_id, event_key)
);
CREATE INDEX pending_push_deliveries ON caughtin4k.push_deliveries(next_attempt_at)
    WHERE completed_at IS NULL;
ALTER TABLE caughtin4k.push_installations ENABLE ROW LEVEL SECURITY;
ALTER TABLE caughtin4k.push_deliveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON caughtin4k.push_installations, caughtin4k.push_deliveries FROM PUBLIC;
