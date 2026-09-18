-- RC4.85 P08.8: mirror the host-owned restore generation inside PostgreSQL.
-- The host-local restore-control file remains authoritative while PostgreSQL is
-- offline/replaced; this singleton exists for runtime observability and later
-- service readiness/generation enforcement.

CREATE TABLE IF NOT EXISTS database_restore_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    installation_fingerprint VARCHAR(64) NOT NULL DEFAULT '',
    restore_generation BIGINT NOT NULL DEFAULT 0 CHECK (restore_generation >= 0),
    last_restore_operation_id UUID NULL,
    last_restore_source_public_id VARCHAR(32) NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO database_restore_state(singleton)
VALUES (TRUE)
ON CONFLICT (singleton) DO NOTHING;

COMMENT ON TABLE database_restore_state IS
    'Runtime mirror of host-owned database restore installation fingerprint/generation. Host-local restore control is authoritative during cutover.';
