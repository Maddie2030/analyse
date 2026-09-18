-- RC4.11: bind-mounted local scraper staging spool identity.
-- Prevents one scraper process from staging files into a different/missing
-- host directory while PostgreSQL records them as ready for another process.
CREATE TABLE IF NOT EXISTS scraper_staging_spool_registry (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    spool_id UUID NOT NULL,
    logical_root TEXT NOT NULL,
    last_service VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
