CREATE TABLE IF NOT EXISTS scraper_batch_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    total_items INTEGER NOT NULL DEFAULT 0,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scraper_batch_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES scraper_batch_uploads(id) ON DELETE CASCADE,
    target_series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    chapter_number NUMERIC NOT NULL,
    chapter_slug VARCHAR(255) NOT NULL,
    source_files JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    existing_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE SET NULL,
    published_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE SET NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_scraper_batch_uploads_series
    ON scraper_batch_uploads(target_series_id);

CREATE INDEX IF NOT EXISTS ix_scraper_batch_uploads_status
    ON scraper_batch_uploads(status);

CREATE INDEX IF NOT EXISTS ix_scraper_batch_items_batch
    ON scraper_batch_items(batch_id);

CREATE INDEX IF NOT EXISTS ix_scraper_batch_items_status
    ON scraper_batch_items(status);

CREATE INDEX IF NOT EXISTS ix_scraper_batch_items_series
    ON scraper_batch_items(target_series_id);
