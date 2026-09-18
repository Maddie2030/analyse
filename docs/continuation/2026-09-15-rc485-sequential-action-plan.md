
### P12.6 no-host-Python Graphify reference repair — 2026-09-18

- Source `7bea1fc6817a6560b45bc30f8e76d3233dd76622` removes direct host-Python calls from the Graphify/development-reference shell path and uses the shared Docker-capable Python runtime.
- Package `mreader-rc485-p12.6-source-test-7bea1fc.zip`, SHA-256 `3ecaaa9753d2bec5e9cd66dbc85245c66eb001c45f4b43760d943323fa9dba5d`.
- Verification: no-host-Python PASS; development-reference 4/4 + static PASS; 139/139 route audit; release validator PASS; Ripwire gating=0; package 1,036/1,036 checksums and 1,003/1,003 Git files/modes exact.
- Real host must rerun `./scripts/bootstrap.sh`, `./hybrid-up.sh`, then `./diagnose-mreader.sh`.
- P11 runtime/independent-review gates remain open.

## P12.7 permissions-first deep diagnostics checkpoint — 2026-09-18

P12.7 source `a081944a335c899223d057dead9c0803c8887bf0` expands the live diagnostic gate to 832 PostgreSQL permission checks plus 272 gateway/routing/CORS checks before functional suites, and adds the end-to-end IndexedDB -> server progress -> Smart Library browser assertion. Use package `mreader-rc485-p12.7-source-test-a081944.zip` (SHA-256 `928de38d6fb2e3b033bfa3f2950682bc9b410e2dc38c415e10ffe1b54cafef46`) for the next real-host diagnostic run. Repair failures in layer order to avoid mistaking downstream 500/503 cascades for independent defects.
