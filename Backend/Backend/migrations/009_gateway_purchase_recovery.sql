CREATE TABLE caughtin4k.gateway_purchases (
    gateway_id UUID PRIMARY KEY REFERENCES caughtin4k.gateways(id),
    order_reference TEXT NOT NULL UNIQUE CHECK (length(order_reference) BETWEEN 1 AND 200),
    purchaser_email TEXT NOT NULL CHECK (length(purchaser_email) BETWEEN 1 AND 254),
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE caughtin4k.gateway_purchases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON caughtin4k.gateway_purchases FROM PUBLIC;
