CREATE TABLE IF NOT EXISTS scraper_series_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url TEXT NOT NULL,
    adapter VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    description TEXT NULL,
    series_status VARCHAR(20) NOT NULL DEFAULT 'ongoing',
    cover_source_url TEXT NULL,
    cover_staging_path TEXT NULL,
    genres JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    workflow_status VARCHAR(32) NOT NULL DEFAULT 'draft',
    error_message TEXT NULL,
    published_series_id UUID NULL REFERENCES series(id) ON DELETE SET NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scraper_series_draft_chapters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES scraper_series_drafts(id) ON DELETE CASCADE,
    chapter_number NUMERIC(8,2) NOT NULL,
    chapter_slug VARCHAR(255) NOT NULL,
    chapter_title VARCHAR(255) NULL,
    source_url TEXT NOT NULL,
    selected BOOLEAN NOT NULL DEFAULT TRUE,
    stage_status VARCHAR(32) NOT NULL DEFAULT 'discovered',
    pages JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message TEXT NULL,
    published_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (draft_id, chapter_number),
    UNIQUE (draft_id, chapter_slug)
);

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_status
    ON scraper_series_drafts(workflow_status);

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_created_by
    ON scraper_series_drafts(created_by);

CREATE INDEX IF NOT EXISTS ix_scraper_series_draft_chapters_draft
    ON scraper_series_draft_chapters(draft_id);

CREATE INDEX IF NOT EXISTS ix_scraper_series_draft_chapters_stage
    ON scraper_series_draft_chapters(stage_status);
