-- Manhwa Reader — initial schema (scaled for 10K concurrent users)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── Users ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(50) UNIQUE NOT NULL,
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20) NOT NULL DEFAULT 'user',
    avatar_key    VARCHAR(32) NOT NULL DEFAULT 'skull',
    CONSTRAINT ck_users_avatar_key CHECK (avatar_key IN ('skull','bard','cleric','fire_wielder','king','paladin','shadow_rogue','sorcerer','swordsman')),
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_username_lower ON users(LOWER(username));
CREATE INDEX IF NOT EXISTS idx_users_email_lower ON users(LOWER(email));

-- ── Genres ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS genres (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

-- ── Series ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS series (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title            VARCHAR(255) NOT NULL,
    slug             VARCHAR(255) UNIQUE NOT NULL,
    description      TEXT,
    cover_image_path VARCHAR(500),
    cover_media_generation BIGINT NOT NULL DEFAULT 0 CHECK (cover_media_generation >= 0),
    status           VARCHAR(20) NOT NULL DEFAULT 'ongoing',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_series_status ON series(status);
CREATE INDEX IF NOT EXISTS idx_series_updated_at ON series(updated_at DESC);

-- ── Series-Genres junction ─────────────────────────
CREATE TABLE IF NOT EXISTS series_genres (
    series_id UUID REFERENCES series(id) ON DELETE CASCADE,
    genre_id  INTEGER REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (series_id, genre_id)
);
CREATE INDEX IF NOT EXISTS idx_series_genres_genre_id ON series_genres(genre_id);

-- ── Series-Tags junction ────────────────────────────
CREATE TABLE IF NOT EXISTS tags (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS series_tags (
    series_id UUID REFERENCES series(id) ON DELETE CASCADE,
    tag_id    INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (series_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_series_tags_tag_id ON series_tags(tag_id);
INSERT INTO tags (name) VALUES
('Action'), ('Fantasy'), ('Romance'), ('Drama'), ('Slice of Life'), ('Comedy'), ('Thriller'), ('Horror'), ('Mystery'), ('Sci-Fi'), ('Historical'), ('School Life'), ('Sports'), ('Martial Arts'), ('Supernatural'), ('Isekai'), ('Regression'), ('Reincarnation'), ('Transmigration'), ('Villainess'), ('System'), ('Gate'), ('Hunter'), ('Tower'), ('Murim'), ('Cultivation'), ('Mecha'), ('Cyberpunk'), ('Post-Apocalyptic'), ('Survival'), ('Medical'), ('Cooking'), ('Showbiz'), ('Psychological'), ('Tragedy'), ('Harem'), ('Reverse Harem'), ('Boys'' Love'), ('Girls'' Love'), ('Office Romance'), ('Contract Marriage'), ('Enemies to Lovers'), ('Friends to Lovers'), ('Overpowered MC'), ('Revenge'), ('Kingdom Building'), ('Delinquent')
ON CONFLICT (name) DO NOTHING;

-- ── Chapters ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chapters (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id     UUID REFERENCES series(id) ON DELETE CASCADE,
    chapter_number NUMERIC(8,2) NOT NULL,
    title         VARCHAR(255),
    slug          VARCHAR(255) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'draft',
    page_count    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (series_id, chapter_number),
    UNIQUE (series_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_chapters_series_id ON chapters(series_id);
CREATE INDEX IF NOT EXISTS idx_chapters_series_status ON chapters(series_id, status);
CREATE INDEX IF NOT EXISTS idx_chapters_series_number ON chapters(series_id, chapter_number DESC) WHERE status = 'published';

-- ── Pages ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id  UUID REFERENCES chapters(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    image_path       VARCHAR(500) NOT NULL,
    width            INTEGER,
    height           INTEGER,
    responsive_image_path VARCHAR(500),
    responsive_width      INTEGER,
    responsive_height     INTEGER,
    media_generation      BIGINT NOT NULL DEFAULT 0 CHECK (media_generation >= 0),
    encoding_version SMALLINT NOT NULL DEFAULT 4,
    encoding_rows    SMALLINT,
    encoding_columns SMALLINT,
    encoding_seed    VARCHAR(128),
    CONSTRAINT ck_pages_responsive_variant CHECK (
        (responsive_image_path IS NULL AND responsive_width IS NULL AND responsive_height IS NULL)
        OR (
            responsive_image_path IS NOT NULL
            AND responsive_width IS NOT NULL AND responsive_width > 0
            AND responsive_height IS NOT NULL AND responsive_height > 0
        )
    ),
    CONSTRAINT ck_pages_encoding_metadata CHECK (
        encoding_version = 4
        AND encoding_rows BETWEEN 1 AND 32
        AND encoding_columns BETWEEN 1 AND 32
        AND encoding_seed IS NOT NULL
        AND length(encoding_seed) >= 16
    ),
    UNIQUE (chapter_id, page_number)
);
CREATE INDEX IF NOT EXISTS idx_pages_chapter_id ON pages(chapter_id);

-- ── Reading Progress ────────────────────────────────
CREATE TABLE IF NOT EXISTS reading_progress (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    series_id       UUID REFERENCES series(id) ON DELETE CASCADE,
    chapter_id      UUID REFERENCES chapters(id) ON DELETE SET NULL,
    last_page       INTEGER NOT NULL DEFAULT 1,
    scroll_position DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revision        BIGINT NOT NULL DEFAULT 1,
    last_opened_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_generation BIGINT NOT NULL DEFAULT 0,
    command_sequence BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT ck_reading_progress_revision_positive CHECK (revision >= 1),
    CONSTRAINT ck_reading_progress_ordering CHECK (session_generation >= 0 AND command_sequence >= 0),
    UNIQUE (user_id, series_id)
);
CREATE INDEX IF NOT EXISTS idx_reading_progress_user ON reading_progress(user_id);



-- ── Exact Chapter Read State ─────────────────────────
CREATE TABLE IF NOT EXISTS chapter_reads (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    first_read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_page INTEGER NOT NULL DEFAULT 1 CHECK (last_page >= 1),
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ NULL,
    resume_page INTEGER NULL CHECK (resume_page >= 1),
    resume_scroll_position DOUBLE PRECISION NULL CHECK (resume_scroll_position BETWEEN 0 AND 1),
    session_generation BIGINT NOT NULL DEFAULT 0 CHECK (session_generation >= 0),
    command_sequence BIGINT NOT NULL DEFAULT 0 CHECK (command_sequence >= 0),
    command_id UUID NULL,
    command_hash TEXT NULL,
    open_command_id UUID NULL,
    open_expected_revision BIGINT NULL,
    provenance TEXT NOT NULL DEFAULT 'legacy',
    PRIMARY KEY (user_id, chapter_id)
);
CREATE INDEX IF NOT EXISTS ix_chapter_reads_user_series ON chapter_reads(user_id, series_id, last_read_at DESC);
CREATE INDEX IF NOT EXISTS ix_chapter_reads_user_series_completed ON chapter_reads(user_id, series_id, completed) WHERE completed;
CREATE UNIQUE INDEX IF NOT EXISTS ix_chapter_reads_open_command ON chapter_reads(user_id, series_id, open_command_id) WHERE open_command_id IS NOT NULL;

-- ── Reader Trending Analytics ───────────────────────
-- Hourly aggregate only: no IP addresses or per-reader identities are stored.
CREATE TABLE IF NOT EXISTS series_trending_hourly (
    series_id     UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    bucket_start  TIMESTAMPTZ NOT NULL,
    open_count    BIGINT NOT NULL DEFAULT 0 CHECK (open_count >= 0),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (series_id, bucket_start)
);
CREATE INDEX IF NOT EXISTS idx_series_trending_hourly_bucket
    ON series_trending_hourly(bucket_start DESC, series_id);

-- ── Browse Curation ──────────────────────────────────
CREATE TABLE IF NOT EXISTS editor_picks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    label VARCHAR(80) NULL,
    note VARCHAR(280) NULL,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    starts_at TIMESTAMPTZ NULL,
    ends_at TIMESTAMPTZ NULL,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT editor_picks_schedule_check CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at),
    CONSTRAINT editor_picks_series_unique UNIQUE (series_id)
);
CREATE INDEX IF NOT EXISTS idx_editor_picks_public ON editor_picks(position, created_at) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS announcements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(120) NOT NULL,
    body VARCHAR(1000) NOT NULL,
    link_url VARCHAR(1000) NULL,
    link_label VARCHAR(80) NULL,
    tone VARCHAR(16) NOT NULL DEFAULT 'info' CHECK (tone IN ('info','success','warning','critical')),
    dismissible BOOLEAN NOT NULL DEFAULT TRUE,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    starts_at TIMESTAMPTZ NULL,
    ends_at TIMESTAMPTZ NULL,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT announcements_schedule_check CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS idx_announcements_public ON announcements(position, created_at DESC) WHERE is_active = TRUE;

-- ── Bookmarks ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bookmarks (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
    series_id  UUID REFERENCES series(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, series_id)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_id ON bookmarks(user_id);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_created ON bookmarks(user_id, created_at DESC);

-- ── Subscriptions ────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
    series_id  UUID REFERENCES series(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, series_id)
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_series_id ON subscriptions(series_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_created ON subscriptions(user_id, created_at DESC);

-- ── Notifications ────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
    series_id  UUID REFERENCES series(id) ON DELETE CASCADE,
    chapter_id UUID REFERENCES chapters(id) ON DELETE CASCADE,
    message    VARCHAR(500) NOT NULL,
    is_read    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_unread
    ON notifications(user_id) WHERE is_read = false;
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_notifications_retention
    ON notifications(is_read, created_at);

-- ── Comments ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS comments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    series_id  UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    chapter_id UUID REFERENCES chapters(id) ON DELETE CASCADE,
    parent_id  UUID REFERENCES comments(id) ON DELETE CASCADE,
    content    TEXT NOT NULL CHECK (char_length(btrim(content)) BETWEEN 1 AND 2000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_comments_context
    ON comments(series_id, chapter_id, created_at);
CREATE INDEX IF NOT EXISTS idx_comments_parent_id
    ON comments(parent_id);
CREATE INDEX IF NOT EXISTS idx_comments_user_id ON comments(user_id);

-- ── Trigram indexes for fuzzy search ────────────────
CREATE INDEX IF NOT EXISTS idx_series_title_trgm
    ON series USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_series_desc_trgm
    ON series USING GIN (description gin_trgm_ops);


-- Durable lifecycle cleanup queue. This must exist before scraper storage
-- attempts because the attempt ledger references cleanup_job_id. Migrations
-- use CREATE IF NOT EXISTS, so keeping the fresh schema current is safe.
CREATE TABLE IF NOT EXISTS lifecycle_cleanup_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(32) NOT NULL,
    entity_id UUID NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
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
    ON lifecycle_cleanup_jobs(updated_at DESC) WHERE status = 'failed';
CREATE INDEX IF NOT EXISTS ix_lifecycle_cleanup_entity
    ON lifecycle_cleanup_jobs(entity_type, entity_id, created_at DESC);


-- Scraper service history
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


-- Scraper editable drafts
CREATE TABLE IF NOT EXISTS scraper_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_type VARCHAR(50) NOT NULL,
    source_url TEXT NOT NULL,
    target_series_id UUID NULL REFERENCES series(id) ON DELETE CASCADE,
    series_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    chapter_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    pages JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    published_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE CASCADE,
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


-- Scraper batch uploads
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
    existing_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE CASCADE,
    published_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE CASCADE,
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


-- Full-series scraper drafts
CREATE TABLE IF NOT EXISTS scraper_series_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url TEXT NOT NULL,
    source_url_key TEXT NULL,
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
    operation_cancel_requested_at TIMESTAMPTZ NULL,
    operation_cancel_requested_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    duplicate_series_id UUID NULL REFERENCES series(id) ON DELETE SET NULL,
    duplicate_series_slug VARCHAR(255) NULL,
    duplicate_series_title VARCHAR(255) NULL,
    published_series_id UUID NULL REFERENCES series(id) ON DELETE CASCADE,
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
    published_chapter_id UUID NULL REFERENCES chapters(id) ON DELETE CASCADE,
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


-- Scraper cross-storage transaction ledger. Paths live here only while an
-- external-storage outcome is unresolved; terminal attempts clear them.

CREATE TABLE IF NOT EXISTS scraper_staging_spool_registry (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    spool_id UUID NOT NULL,
    logical_root TEXT NOT NULL,
    last_service VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scraper_storage_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_type VARCHAR(32) NOT NULL CHECK (
        operation_type IN ('series_cover','chapter_publish','batch_publish','batch_stage_create','existing_draft_publish','existing_draft_stage_create')
    ),
    draft_id UUID NULL REFERENCES scraper_series_drafts(id) ON DELETE SET NULL,
    draft_chapter_id UUID NULL REFERENCES scraper_series_draft_chapters(id) ON DELETE SET NULL,
    batch_item_id UUID NULL REFERENCES scraper_batch_items(id) ON DELETE SET NULL,
    batch_id UUID NULL REFERENCES scraper_batch_uploads(id) ON DELETE SET NULL,
    local_staging_prefix TEXT NULL,
    object_paths JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(object_paths) = 'array'),
    status VARCHAR(24) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','committed','cleanup_queued','cleanup_complete')),
    canonical_entity_id UUID NULL,
    cleanup_job_id UUID NULL REFERENCES lifecycle_cleanup_jobs(id) ON DELETE SET NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_scraper_storage_attempts_active
    ON scraper_storage_attempts(heartbeat_at, created_at, id) WHERE status='active';
CREATE INDEX IF NOT EXISTS ix_scraper_storage_attempts_cleanup
    ON scraper_storage_attempts(cleanup_job_id, updated_at) WHERE status='cleanup_queued';

-- RC4.38 pressure-path indexes (idempotent for fresh installs/migrations).
CREATE INDEX IF NOT EXISTS idx_bookmarks_series_id
    ON bookmarks(series_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread_created
    ON notifications(user_id, created_at DESC)
    WHERE is_read = FALSE;
CREATE INDEX IF NOT EXISTS idx_chapters_series_slug_published
    ON chapters(series_id, slug)
    WHERE status = 'published';

-- Current-baseline migration ledger. Fresh databases already contain the final
-- The consolidated reading-state schema, so retired transition migrations that require
-- reading_history must not be replayed. Existing databases do not rerun init.sql
-- and therefore still receive migration 048 normally.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO schema_migrations(version) VALUES
    ('004_single_series_reading_state.sql'),
    ('023_smart_library_furthest_read.sql'),
    ('039_progress_owns_reading_state.sql'),
    ('045_reading_history_repair_rc479.sql'),
    ('046_reading_history_repair_rc481.sql'),
    ('047_consolidate_reading_state_rc482.sql')
ON CONFLICT (version) DO NOTHING;
