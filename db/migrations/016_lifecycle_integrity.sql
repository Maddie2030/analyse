-- v1.1.3-rc9 lifecycle integrity
--
-- Relational rows are already mostly protected by ON DELETE CASCADE, but
-- external state (SeaweedFS, Valkey, image-edge/CDN caches, scraper staging)
-- needs durable cleanup after the business transaction commits.

CREATE TABLE IF NOT EXISTS lifecycle_cleanup_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(32) NOT NULL,
    entity_id UUID NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(payload) = 'object'),
    status VARCHAR(16) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'retry', 'completed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 20 CHECK (max_attempts BETWEEN 1 AND 100),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ NULL,
    locked_by VARCHAR(128) NULL,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_lifecycle_cleanup_pending
    ON lifecycle_cleanup_jobs(next_attempt_at, created_at, id)
    WHERE status IN ('queued', 'retry');

CREATE INDEX IF NOT EXISTS ix_lifecycle_cleanup_failed
    ON lifecycle_cleanup_jobs(updated_at DESC)
    WHERE status = 'failed';

CREATE INDEX IF NOT EXISTS ix_lifecycle_cleanup_entity
    ON lifecycle_cleanup_jobs(entity_type, entity_id, created_at DESC);

-- Notifications are derived from a series/chapter and should disappear with
-- that source entity rather than becoming detached, permanently unread rows.
DELETE FROM notifications WHERE series_id IS NULL OR chapter_id IS NULL;

ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_series_id_fkey;
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_chapter_id_fkey;
ALTER TABLE notifications
    ADD CONSTRAINT notifications_series_id_fkey
    FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE;
ALTER TABLE notifications
    ADD CONSTRAINT notifications_chapter_id_fkey
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE;

-- Published scraper metadata is lifecycle-bound to the entity it produced.
-- Source/history records that are not linked to an entity are intentionally
-- retained, but rows explicitly linked to a deleted entity are removed.
ALTER TABLE scraper_drafts DROP CONSTRAINT IF EXISTS scraper_drafts_published_chapter_id_fkey;
ALTER TABLE scraper_drafts
    ADD CONSTRAINT scraper_drafts_published_chapter_id_fkey
    FOREIGN KEY (published_chapter_id) REFERENCES chapters(id) ON DELETE CASCADE;

ALTER TABLE scraper_batch_items DROP CONSTRAINT IF EXISTS scraper_batch_items_existing_chapter_id_fkey;
ALTER TABLE scraper_batch_items DROP CONSTRAINT IF EXISTS scraper_batch_items_published_chapter_id_fkey;
ALTER TABLE scraper_batch_items
    ADD CONSTRAINT scraper_batch_items_existing_chapter_id_fkey
    FOREIGN KEY (existing_chapter_id) REFERENCES chapters(id) ON DELETE SET NULL;
ALTER TABLE scraper_batch_items
    ADD CONSTRAINT scraper_batch_items_published_chapter_id_fkey
    FOREIGN KEY (published_chapter_id) REFERENCES chapters(id) ON DELETE SET NULL;

ALTER TABLE scraper_series_drafts DROP CONSTRAINT IF EXISTS scraper_series_drafts_published_series_id_fkey;
ALTER TABLE scraper_series_drafts
    ADD CONSTRAINT scraper_series_drafts_published_series_id_fkey
    FOREIGN KEY (published_series_id) REFERENCES series(id) ON DELETE CASCADE;

ALTER TABLE scraper_series_draft_chapters DROP CONSTRAINT IF EXISTS scraper_series_draft_chapters_published_chapter_id_fkey;
ALTER TABLE scraper_series_draft_chapters
    ADD CONSTRAINT scraper_series_draft_chapters_published_chapter_id_fkey
    FOREIGN KEY (published_chapter_id) REFERENCES chapters(id) ON DELETE CASCADE;

COMMENT ON TABLE lifecycle_cleanup_jobs IS
    'Durable post-commit cleanup for SeaweedFS, Valkey, local image cache and optional CDN state.';
