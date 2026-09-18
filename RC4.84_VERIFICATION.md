# RC4.84 verification record

## Source/static verification

- Current-release validator reached: `MReader 1.3.0-rc4.84 current release validation PASSED` on the staged source tree. Docker Compose render was skipped because the execution environment has no Docker Engine/configured `.env`.
- Regression scripts: **48/48 PASS** on the corrected source code. No regression script failed. This includes the new `bootstrap-fresh-env.sh` regression that executes the real bootstrap flow in a clean temporary release tree with Docker mocked.
- API source-route coverage: **135/135 classified** (`functional=58`, `integration=53`, `validation=23`, `e2e=1`).
- Web/Android Reader contract audit: PASS.
- Android static integration audit: PASS.
- Python AST syntax parse: PASS.
- Shell `bash -n` gate: PASS.
- Fresh archive bootstrap ordering regression: PASS (`.env` is created before stateful-volume adoption).
- Hybrid stateful volume adoption runtime regression (mocked Docker): PASS for legacy-only adoption, dual-valid-PGDATA with exactly one populated catalog, ambiguous dual-catalog refusal, and explicit override preservation.
- Recovery source detection confirmed against the supplied artifacts: the logical backup has PostgreSQL custom `PGDMP` format; the physical snapshot contains `base.tar.gz`, `pg_wal.tar.gz`, and `backup_manifest`.
- `LibraryScreen.kt`, which previously produced a top-level Kotlin syntax error, has no parser-level syntax diagnostic in a direct compiler probe.

## Environment-limited gates

The source-repair environment has Go 1.23.2 while all six Go modules require Go 1.25.0; Node/npm are installed but frontend/Social dependency trees are not installed; the full Android Gradle dependency environment is not cached; and Docker Engine is unavailable.

Therefore full Go builds/tests, npm application builds, full Android Gradle build, Docker Compose render/deployment, isolated donor PostgreSQL boot, and live NAS recovery validation are **not claimed as passed here**. Those runtime gates must be executed on the target Docker Desktop + NAS host.

## Recovery safety claim

The shipped recovery implementation is read-only toward NAS, imports only `series`, `chapters`, `pages`, `genres`, `series_genres`, `tags`, and `series_tags`, requires an empty target catalog, creates a pre-import PostgreSQL safety dump, validates v4 encoding metadata, and blocks import when primary NAS page objects are missing.
