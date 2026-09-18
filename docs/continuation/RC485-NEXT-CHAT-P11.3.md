# RC4.85 next chat — resume P11.3 performance/resource qualification

## Resume authority

- branch: `sequential/p06.4-caller-cutover`
- canonical workspace: `/mnt/data/mreader-rc485-working`
- P10.2 durable tracker: `65f0c2ebada66a653700e76025d2a5ba1a051f69`
- P11.1 evidence tracker: `75df6a840c44acf2c409e846419ed8c7a062c796`
- P10.2 behavior/source: `b15b417f8a28fed6b5e2e0c762adf628a8a4b4f0`
- P10.2 quality evidence: `cad882604331631497b0039bfd6d6635d6b4a7df`
- forensic stash: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4` — never apply/pop normally

## Current state

P11.1 and P11.2 remain **BLOCKED for release acceptance** because this sandbox lacks the required build/runtime and destructive restore topology. The user explicitly authorized continuing past those blockers for sequencing only.

P11.2 dependency-light/source-version evidence is complete and recorded in:

1. `docs/qualification/2026-09-17-rc485-p11.2-upgrade-restore-rehearsal.md`
2. `docs/qualification/2026-09-17-rc485-p11.2-rehearsal-matrix.tsv`

Key P11.2 evidence: 123 migration/recovery tests / 10 explicit real-PostgreSQL skips / 0 failures; recovery shell contracts green except two inherited fixture hangs; real restore/backup entrypoints fail closed before mutation because Docker/PostgreSQL/Kubernetes runtime is absent.

## Next action — P11.3

Inspect Library query plans and exercise resource/queue/cache bounds, concurrent reading/publishing and existing KEDA/HPA behavior without increasing limits. Execute every dependency-light/source/static gate available here. Record real PostgreSQL/Docker/Kubernetes/load gates as BLOCKED when unavailable; do not replace them with static checks. Preserve all P09 ownership/security/readiness fences and P10 truthfulness/race guards.

Do not start P11.4 release review until P11.3 evidence is recorded and checkpointed.
