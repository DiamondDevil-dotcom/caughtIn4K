CREATE TABLE caughtin4k.gateway_commands (
    id UUID PRIMARY KEY,
    gateway_id UUID NOT NULL REFERENCES caughtin4k.gateways(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES caughtin4k.accounts(id),
    action TEXT NOT NULL CHECK (action IN ('block', 'unblock')),
    mac TEXT NOT NULL CHECK (mac ~ '^[0-9a-f]{2}(:[0-9a-f]{2}){5}$'),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'delivered', 'succeeded', 'failed', 'expired', 'cancelled', 'unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '120 seconds',
    delivered_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result_code TEXT CHECK (result_code IN ('applied', 'enforcement_failed', 'local_rejected', 'local_unreachable', 'expired'))
);
CREATE UNIQUE INDEX gateway_commands_one_active
    ON caughtin4k.gateway_commands(gateway_id) WHERE status IN ('queued', 'delivered');
CREATE INDEX gateway_commands_expiry ON caughtin4k.gateway_commands(gateway_id, status, expires_at);
REVOKE ALL ON caughtin4k.gateway_commands FROM PUBLIC;
ALTER TABLE caughtin4k.gateway_commands ENABLE ROW LEVEL SECURITY;
