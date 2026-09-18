-- Durable, correlated scraper data-flow timeline.
-- Keeps the admin UI and diagnostics able to explain where an operation is
-- currently executing across API -> RabbitMQ -> worker -> storage/catalog/reader.

CREATE TABLE IF NOT EXISTS scraper_operation_events (
    id BIGSERIAL PRIMARY KEY,
    operation_id UUID NOT NULL REFERENCES scraper_series_drafts(id) ON DELETE CASCADE,
    chapter_id UUID NULL REFERENCES scraper_series_draft_chapters(id) ON DELETE SET NULL,
    request_id TEXT NULL,
    service VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    phase VARCHAR(96) NULL,
    status VARCHAR(32) NULL,
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraper_operation_events_operation_created
    ON scraper_operation_events(operation_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_scraper_operation_events_chapter_created
    ON scraper_operation_events(chapter_id, created_at DESC, id DESC)
    WHERE chapter_id IS NOT NULL;

COMMENT ON TABLE scraper_operation_events IS
    'Append-only scraper operation timeline used for end-to-end diagnostics and admin progress visibility.';
