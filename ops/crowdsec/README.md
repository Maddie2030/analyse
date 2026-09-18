# CrowdSec mode

This optional mode analyzes Caddy and image-edge access logs with the open-source CrowdSec engine.
MReader's actual request blocking/rate limiting remains in Reader Go + Valkey/Redis-compatible storage, so the app does not depend on a paid CrowdSec bouncer.

For host-level automatic blocking, add a CrowdSec bouncer appropriate to the host OS/firewall separately. That is intentionally not enabled by default because firewall bouncers require elevated host privileges and are not portable across Docker Desktop/Linux hosts.
