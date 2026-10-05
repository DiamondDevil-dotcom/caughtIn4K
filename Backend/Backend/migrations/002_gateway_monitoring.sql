CREATE TABLE caughtin4k.gateway_snapshots (
    gateway_id UUID PRIMARY KEY REFERENCES caughtin4k.gateways(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    devices JSONB NOT NULL CHECK (jsonb_typeof(devices) = 'array'),
    alerts JSONB NOT NULL CHECK (jsonb_typeof(alerts) = 'array'),
    model JSONB NOT NULL CHECK (jsonb_typeof(model) = 'object')
);
REVOKE ALL ON caughtin4k.gateway_snapshots FROM PUBLIC;
ALTER TABLE caughtin4k.gateway_snapshots ENABLE ROW LEVEL SECURITY;
