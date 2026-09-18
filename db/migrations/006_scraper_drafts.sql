CREATE TABLE IF NOT EXISTS scraper_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_type VARCHAR(50) NOT NULL,
    source_url TEXT NOT NULL,
    target_series_id UUID NULL REFERENCES series(id) ON DELETE CASCADE,
    series_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    chapter_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    pages JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    published_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE SET NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_scraper_drafts_target_series
    ON scraper_drafts(target_series_id);

CREATE INDEX IF NOT EXISTS ix_scraper_drafts_status
    ON scraper_drafts(status);

CREATE INDEX IF NOT EXISTS ix_scraper_drafts_created_by
    ON scraper_drafts(created_by);
