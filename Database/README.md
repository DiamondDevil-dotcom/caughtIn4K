# caughtIn4K database

This folder is the shared runtime data boundary for the router agent and the
website backend. The SQLite file is created here as `router_ids.db`.

The website must connect through the router agent HTTP API, not directly to
SQLite. Available API groups include:

- `/auth/signup`, `/auth/login`, `/auth/change-password`, `/auth/request-password-reset`, `/auth/reset-password`
- `/devices` and `/devices/{mac}/block` or `/devices/{mac}/unblock`
- `/events`
- `/telemetry`

Do not commit `router_ids.db`, password hashes, reset tokens, or SMTP secrets.

Copy `email.env.example` to `email.env`, fill in the values, and restart the
router agent. `email.env` is ignored by version control.