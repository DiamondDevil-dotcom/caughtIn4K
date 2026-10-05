ALTER TABLE caughtin4k.accounts ADD COLUMN email_verified_at TIMESTAMPTZ;
-- Preserve existing accounts without inventing email proof. They verify once
-- before accessing homes through the public customer entrypoint.

CREATE TABLE caughtin4k.email_verification_tokens (
    account_id UUID PRIMARY KEY REFERENCES caughtin4k.accounts(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5)
);
CREATE TABLE caughtin4k.request_limits (
    key_hash TEXT PRIMARY KEY,
    window_started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    attempts INTEGER NOT NULL DEFAULT 1
);
ALTER TABLE caughtin4k.email_verification_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE caughtin4k.request_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON caughtin4k.email_verification_tokens, caughtin4k.request_limits FROM PUBLIC;
