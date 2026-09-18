# Current RC4.85 recovery handoff

- Branch: `sequential/p06.4-caller-cutover`
- Current source checkpoint: `a081944a335c899223d057dead9c0803c8887bf0`
- Current package: `mreader-rc485-p12.7-source-test-a081944.zip`
- Package SHA-256: `928de38d6fb2e3b033bfa3f2950682bc9b410e2dc38c415e10ffe1b54cafef46`
- Forensic stash to preserve: `ffbcfe842c0e7f0910eae8ccf4fe64f822c01af4`
- P12.7 diagnostic depth: 832 PostgreSQL permission cases + 272 gateway/routing/CORS boundary cases = 1,104 architecture checks before existing API/actor/browser suites.
- Resume: deploy P12.7 on Windows, run bootstrap/hybrid-up, then full diagnostics and use the layered report to fix upstream permission/boundary failures before downstream cascades. Do not waive remaining P11 runtime or independent-review gates.

## 2026-09-18 P12.8 — user-perspective 800-case qualification harness

P12.8 adds a portable `./test-mreader.sh --user-800` qualification path. It inventories all current React routes/clickable access points, runs static regressions, launches full Dockerized diagnostics with disposable admin credentials and a supplied real scraper series URL, and emits an exact `qualification-800.tsv` ledger while still gating on every additional executed runtime case.

A real diagnostics defect from the prior report was repaired: the core pytest command confused Python's `-m pytest` with pytest's `-m <markers>`, replacing the module name and executing zero functional API tests. `tests/diagnostics/test_runner_protocol.py` now locks this down. Admin database UI smoke also uses an exact `Local recovery storage` locator, and a real-series admin **Analyze** Playwright journey was added.

The supplied `20260918T114212Z-14381` report remains the baseline to re-test: 832/832 permission PASS, 266/272 boundary PASS, 0 functional API executed due to the harness defect, and 1/12 browser PASS. Runtime CrashLoops, PostgreSQL permission evidence, 404 upload paths, realtime timeout, scrape timeout and the user-journey 401 are not considered fixed until the new machine run proves them.

Sandbox verification: diagnostics runner protocol 12/12 PASS; qualification static regression PASS; UI audit inventories 19 routes / 211 clickable access points; report-builder replay produces exactly 800 ledger rows and correctly preserves the old diagnostic's FAIL. Live Docker Desktop/Kubernetes runtime qualification is BLOCKED in this sandbox and must be executed on the user's machine.

### P12.8 checkpoint detail

- Source/test commit: `9e8ca135e4aeedb8e0b6ee7f9f8aec60ba74e5be` (`test(qualification): add containerized user 800 suite`).
- Container model is enforced by regression: the qualification path builds `tests/api/Dockerfile`, builds the dedicated `tests/diagnostics/Dockerfile` image on top of it, launches the diagnostics suite in its own Docker container on the stateful network, and runs Playwright in a separate pinned browser container.
- Pytest layers now emit JUnit XML alongside per-test/per-module JSON, HTTP exchange logs, journey-action logs, stage logs, and the consolidated report. Diagnostics protocol is 12/12 PASS; qualification static regression PASS; the supplied failed diagnostic still replays to an exact 800-row canonical ledger with overall FAIL, as intended.

## 2026-09-18 P12.8.1 — qualification host-Python isolation hotfix

The user-machine `hybrid-no-host-python` regression correctly found direct host `python3` calls in the new P12.8 qualification runner. Source/test commit `dc456f1c61835d29d71223afdf30ecca5a1f3fde` removes all such calls from the qualification path. UI inventory and qualification report assembly now force `scripts/hybrid/python-runtime.sh` into Docker mode, while the static qualification regression is POSIX-shell-only.

Important execution model after this hotfix:

- API/functional/integration/admin/RBAC/external scraper tests: dedicated diagnostics Docker container built on the API-test image;
- browser journeys: separate Playwright Docker container;
- UI source inventory and report assembly: pinned Docker Python helper runtime, never host Python;
- host shell: orchestration/artifact collection only.

Fresh verification: qualification static regression PASS; hybrid no-host-Python regression PASS; diagnostics protocol 12/12 PASS; UI inventory remains 19 routes / 211 access points / 129 buttons; replay of `20260918T114212Z-14381` still emits exactly 800 canonical rows and preserves all 17 failures. The authoritative live `./test-mreader.sh --user-800` acceptance run must still be executed on the Docker Desktop MReader host.
