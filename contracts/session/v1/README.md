# Redis session contract v1

All services that read `session:<session_id>` use this contract. New sessions are
written with `version: 1`. Readers temporarily accept a missing/zero version so a
rolling upgrade does not invalidate sessions created by pre-v1 builds; versions
newer than the reader understands are rejected rather than guessed.

Required authorization semantics:

- `user_id` must be non-empty.
- `username` must be non-empty.
- `role` is `user` or `admin`.
- `is_active` must be `true` for an authenticated request.
- unknown future session versions are rejected.
