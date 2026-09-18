-- Runtime heartbeat/capability registry for the database-protection operation engine.
-- Browser/API consumers only receive sanitized readiness flags; internal diagnostics stay server-side.
CREATE TABLE IF NOT EXISTS database_protection_runtime (
    component TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('ready','degraded','offline')),
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_database_protection_runtime_heartbeat
    ON database_protection_runtime (last_heartbeat_at DESC);
