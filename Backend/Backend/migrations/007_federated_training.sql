ALTER TABLE caughtin4k.gateway_commands DROP CONSTRAINT gateway_commands_action_check;
ALTER TABLE caughtin4k.gateway_commands ADD CONSTRAINT gateway_commands_action_check
    CHECK (action IN ('block', 'unblock', 'register', 'remove', 'train'));
ALTER TABLE caughtin4k.gateway_commands ALTER COLUMN mac DROP NOT NULL;
ALTER TABLE caughtin4k.gateway_commands ADD CONSTRAINT gateway_commands_target_check
    CHECK ((action = 'train' AND mac IS NULL) OR (action <> 'train' AND mac IS NOT NULL));
