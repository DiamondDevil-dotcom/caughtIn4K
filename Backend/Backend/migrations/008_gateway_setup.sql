ALTER TABLE caughtin4k.gateways ADD COLUMN consumer_setup BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE caughtin4k.gateway_setup_requests (
    request_id UUID PRIMARY KEY,
    gateway_id UUID NOT NULL REFERENCES caughtin4k.gateways(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE caughtin4k.gateway_setup_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON caughtin4k.gateway_setup_requests FROM PUBLIC;
CREATE TABLE caughtin4k.gateway_setup (
    gateway_id UUID PRIMARY KEY REFERENCES caughtin4k.gateways(id) ON DELETE CASCADE,
    request_id UUID,
    fingerprint TEXT,
    encrypted_wifi TEXT,
    expires_at TIMESTAMPTZ,
    reported_request_id UUID,
    checks JSONB NOT NULL DEFAULT '{}',
    error_code TEXT,
    received_at TIMESTAMPTZ
);
ALTER TABLE caughtin4k.gateway_setup ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON caughtin4k.gateway_setup FROM PUBLIC;
