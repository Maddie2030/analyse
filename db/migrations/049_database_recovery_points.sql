-- Rebuildable catalog projection for verified host-local PostgreSQL recovery bundles.
-- Backup bytes remain owned by MREADER_DB_PROTECTION_ROOT; no absolute host path
-- or storage endpoint is persisted in PostgreSQL or exposed to the browser.
CREATE TABLE IF NOT EXISTS database_recovery_points (
    recovery_id TEXT PRIMARY KEY
        CHECK (recovery_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
    public_id TEXT NOT NULL UNIQUE
        CHECK (public_id ~ '^bkp_[0-9a-f]{24}$'),
    kind TEXT NOT NULL
        CHECK (kind IN ('logical_dump','physical_snapshot')),
    purpose TEXT NOT NULL
        CHECK (purpose IN ('automatic','manual','pre-upgrade','pre-restore','snapshot')),
    relative_directory TEXT NOT NULL UNIQUE
        CHECK (
            relative_directory !~ '(^/|(^|/)\.\.(/|$))'
            AND relative_directory NOT LIKE '%..%'
            AND position(E'\\' in relative_directory) = 0
        ),
    artifact_name TEXT NOT NULL
        CHECK (artifact_name IN ('database.dump','snapshot.tar')),
    created_at TIMESTAMPTZ NOT NULL,
    postgres_major INTEGER NOT NULL CHECK (postgres_major BETWEEN 10 AND 99),
    mreader_version TEXT NOT NULL
        CHECK (mreader_version ~ '^[A-Za-z0-9._-]{1,128}$'),
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    verified BOOLEAN NOT NULL DEFAULT TRUE,
    available BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    unavailable_at TIMESTAMPTZ NULL,
    scan_token TEXT NOT NULL DEFAULT '',
    CHECK (
        (kind = 'logical_dump' AND purpose IN ('automatic','manual','pre-upgrade','pre-restore') AND artifact_name = 'database.dump')
        OR
        (kind = 'physical_snapshot' AND purpose = 'snapshot' AND artifact_name = 'snapshot.tar')
    )
);

CREATE INDEX IF NOT EXISTS idx_database_recovery_points_available_created
    ON database_recovery_points (created_at DESC)
    WHERE available AND verified;
