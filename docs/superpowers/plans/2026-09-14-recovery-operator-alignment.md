# Recovery operator alignment

Approved scope: one host-home PostgreSQL recovery owner, four-day dump and two-day snapshot defaults, preserved custom configuration, one restore engine. This follows the source-confirmed operator mismatches found while tracing the unfinished recovery download path.

1. Write and run focused behavioral tests for known-default retention migration, custom-value preservation, idempotent environment capture, and standalone backup CLI root resolution/failure before Docker.
2. Replace obsolete NAS-proof environment migration with a one-time backup of the original environment and migration of missing/known old retention defaults only. Preserve custom retention and legacy NAS settings as dormant import evidence. Do not add obsolete proof requirements.
3. Resolve the canonical root in standalone backup, restore and validation entry points. Make the old storage-doctor entry point delegate to the current backup-agent self-test through the same CLI rather than reconstructing NAS truth. Update validation's requested default checks.
4. Run focused available tests/syntax, update operator documentation, commit the source checkpoint and refresh the WIP patch. Docker/Desktop/PostgreSQL qualification remains blocked. Secure recovery download still needs an authenticated private transport from the host-local owner; do not enable a nonfunctional browser action or share the recovery mount with public services.

No new runtime service, host-Python dependency, resource limit, live configuration or deployment is introduced by this correction. These are source edits and isolated fixture executions only.

## Source execution and evidence

Implemented operator/environment changes with eight passing behavioral cases. The initial six tests all failed against the previous implementation. Added former-default-after-migration and selected-environment-through-replication checks; both pass. Updated the existing Bash storage-doctor and environment-migration regressions to exercise the local owner and failure propagation. Source storage contracts, shell syntax, Python compilation, diff hygiene and the no-host-Python guard pass.

The original environment is captured before the one-time retention migration, and all changes plus the version marker are written through a temporary file. Custom values survive. A conflicting saved/process root stops before Docker. The doctor uses `check-storage`, which invokes the existing owner self-test without starting dependencies, configuring roles or stopping the scheduler. Explicit setup commands still support those operations and now propagate a selected environment consistently.

The existing primary operator guide was rewritten around the current storage/queue/migration owner. Historical NAS media operations retain their own documentation; no inactive NAS backup proof is treated as current database health.

Full Docker Desktop validation and actual backup/restore remain blocked. Download investigation found two concrete dependencies: no private streaming transport from the host-local agent to the admin API, and `scripts/hybrid/deploy.sh` currently copies the general environment into both namespaces before overrides. An export credential must not be added to that shared secret flow. Downloads remain disabled pending a reviewed private transport and narrowed secret distribution. Existing Catalog publication/lifecycle/grant and restore-generation/pin work is still required by the full spec.
