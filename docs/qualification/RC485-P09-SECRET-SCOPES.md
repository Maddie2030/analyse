# RC4.85 P09.1 — workload-scoped Kubernetes environment secrets

Status: **source implemented; live Docker Desktop/Kubernetes verification still open**.

## Boundary implemented

The hybrid deployment no longer copies the complete root `.env` into one `mreader-env` Secret per namespace. Each application Deployment now references `mreader-env-<workload>`, built from an exact key allowlist under `deploy/docker-desktop-hybrid/env-scopes/`.

This is deliberately a merge-isolated prerequisite for later private Catalog-command and recovery-bridge credentials. Those future credentials are **not** present in any current scope. Adding a new value to `.env` alone cannot expose it to a pod; the owning workload must explicitly opt in through its scope file and manifest.

The frontend, admin frontend and optional scraper-browser scopes do not receive database, broker, token-signing, CDN-management or database-protection credentials. KEDA `*FromEnv` keys remain only on the Deployments that KEDA scales. Namespace-qualified RabbitMQ URLs, KEDA PostgreSQL URLs and the external SeaweedFS filer URL are still derived by `scripts/hybrid/deploy.sh`, but are written only when the target scope declares the key.

After normal workload rollout and ScaledObject readiness, `deploy.sh` deletes the obsolete namespace-wide `mreader-env` Secret. Existing processes are not interrupted by Secret deletion because environment variables are already materialized in the running process; future pod starts resolve only their scoped Secret.

## Focused evidence

The change was developed test-first. Six boundary tests first failed against the milestone-1 source; two additional KEDA/legacy-retirement tests were then added and observed failing before their fixes. All eight pass after implementation.

```bash
python3 -m unittest tests.regression.test_hybrid_secret_scopes -v
bash -n scripts/hybrid/render-workload-env.sh
bash -n scripts/hybrid/deploy.sh
bash tests/regression/twin-plane-static.sh
bash tests/regression/hybrid-test-harness-static.sh
```

Focused result: 8/8 secret-scope tests pass. Existing twin-plane object references/resource budgets and Dockerized test-harness static regressions also pass.

## Remaining verification

No Docker Desktop cluster is available in this workspace. P09.1 therefore still needs one live isolated hybrid deployment proving that every pod starts with its scoped Secret, KEDA ScaledObjects become Ready, no workload depends on an omitted custom setting, and unrelated/public-plane pods cannot observe future private Catalog/recovery credentials. Those runtime checks must be recorded before P09.1 is marked fully **Verified**.
