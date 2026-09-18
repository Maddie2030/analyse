CREATE TABLE IF NOT EXISTS scraper_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL,
    mode VARCHAR(32) NOT NULL,
    adapter VARCHAR(100) NOT NULL,
    title TEXT NULL,
    summary TEXT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'success',
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    snapshot_path TEXT NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_scraper_history_created_at
    ON scraper_history(created_at DESC);

CREATE INDEX IF NOT EXISTS ix_scraper_history_url
    ON scraper_history(url);

CREATE INDEX IF NOT EXISTS ix_scraper_history_created_by
    ON scraper_history(created_by);
