# PostgreSQL Runtime Role Contract

`postgres-roles.v1.json` is the P09.3 least-privilege database contract. It is valid only on the **same source tree** where the P09.2 ownership audit passes; P09.2 remains the request-route write authority and the P01 table disposition remains the table inventory/ownership reference.

The contract separates reusable PostgreSQL capability roles (`NOLOGIN`) from one **workload login** role per deployed database consumer (`LOGIN`). Runtime identities are never migration, role-management, database-management, replication, or recovery authorities.

Request-driven grants are reconciled against P09.2. Non-route worker writes must be represented as an explicit **worker exception** with same-tree evidence and a reason. An exception is evidence for a narrow technical responsibility, not a second ownership registry.

The bootstrap PostgreSQL credential stays host-side for migrations, grant reconciliation, protected recovery, and diagnostics. Application workload scopes receive only the DSN named by their workload row. A new table or function receives no runtime access until both ownership/grant authorities are intentionally updated.

The maintenance flow is:

1. run `scripts/run-ownership-route-audit.sh`;
2. run the P09.3 role auditor;
3. reconcile capability/login roles after migrations;
4. render only workload-specific DSNs through P09.1 scope allowlists;
5. run the disposable PostgreSQL positive/negative permission matrix when an explicitly disposable database is available.

## Supported reconciliation and qualification entrypoints

After migrations complete, run `scripts/hybrid/reconcile-postgres-roles.sh` from the host/bootstrap authority before workload-specific secret rollout. The reconciler audits the same-tree contract, creates/updates capability and workload roles, revokes the current runtime surface, reapplies exact grants, and persists role-specific DSNs for the scoped-secret renderer. Application pods never receive the bootstrap PostgreSQL credential.

Static hybrid validation runs `scripts/run-postgres-role-audit.sh` before Docker/Kubernetes preflight. Runtime permission qualification is intentionally separate: `scripts/test/p09-3-postgres-grants-gate.sh` requires an explicitly disposable DSN or an ephemeral PostgreSQL 16 Docker target and reports PASS, FAIL, or BLOCKED. A BLOCKED result is not a pass.
