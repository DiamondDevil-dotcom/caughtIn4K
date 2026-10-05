ALTER TABLE caughtin4k.gateway_commands DROP CONSTRAINT gateway_commands_action_check;
ALTER TABLE caughtin4k.gateway_commands ADD CONSTRAINT gateway_commands_action_check
    CHECK (action IN ('block', 'unblock', 'register', 'remove'));
ALTER TABLE caughtin4k.gateway_commands ADD COLUMN device_name TEXT;
ALTER TABLE caughtin4k.gateway_commands ADD COLUMN ip_address TEXT;
ALTER TABLE caughtin4k.gateway_commands ADD CONSTRAINT gateway_commands_device_details_check
    CHECK (
        (action = 'register' AND device_name IS NOT NULL AND length(device_name) BETWEEN 1 AND 200
            AND device_name = btrim(device_name) AND ip_address IS NOT NULL
            AND length(ip_address) <= 15)
        OR (action <> 'register' AND device_name IS NULL AND ip_address IS NULL)
    );
