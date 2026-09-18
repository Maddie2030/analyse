-- P07.3: make explicit scraper staging repair generation-safe.
-- `revision` changes when an administrator edits the logical draft/page set.
-- `stage_generation` changes whenever Stage/Retry work is (re)claimed, so a
-- delayed worker cannot commit bytes produced for an older repair attempt.

ALTER TABLE scraper_drafts
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS stage_generation BIGINT NOT NULL DEFAULT 1;

ALTER TABLE scraper_drafts
    DROP CONSTRAINT IF EXISTS scraper_drafts_revision_check,
    ADD CONSTRAINT scraper_drafts_revision_check CHECK (revision >= 1),
    DROP CONSTRAINT IF EXISTS scraper_drafts_stage_generation_check,
    ADD CONSTRAINT scraper_drafts_stage_generation_check CHECK (stage_generation >= 1);

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS stage_generation BIGINT NOT NULL DEFAULT 1;

ALTER TABLE scraper_series_draft_chapters
    DROP CONSTRAINT IF EXISTS scraper_series_draft_chapters_revision_check,
    ADD CONSTRAINT scraper_series_draft_chapters_revision_check CHECK (revision >= 1),
    DROP CONSTRAINT IF EXISTS scraper_series_draft_chapters_stage_generation_check,
    ADD CONSTRAINT scraper_series_draft_chapters_stage_generation_check CHECK (stage_generation >= 1);
