-- RC4.40: Progress is the canonical writer for reading state.
CREATE TABLE IF NOT EXISTS chapter_reads (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    first_read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_page INTEGER NOT NULL DEFAULT 1 CHECK (last_page >= 1),
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ NULL,
    PRIMARY KEY (user_id, chapter_id)
);
CREATE INDEX IF NOT EXISTS ix_chapter_reads_user_series
    ON chapter_reads(user_id, series_id, last_read_at DESC);
CREATE INDEX IF NOT EXISTS ix_chapter_reads_user_series_completed
    ON chapter_reads(user_id, series_id, completed) WHERE completed;

-- Backfill the known resume/history chapter so existing users do not lose the
-- single exact chapter marker the previous schema could represent.
INSERT INTO chapter_reads(
    user_id, series_id, chapter_id, first_read_at, last_read_at, last_page, completed, completed_at
)
SELECT
    rh.user_id,
    rh.series_id,
    rh.chapter_id,
    rh.read_at,
    rh.read_at,
    GREATEST(COALESCE(rp.last_page, 1), 1),
    CASE
        WHEN c.page_count > 0 AND COALESCE(rp.last_page, 1) >= c.page_count THEN TRUE
        ELSE FALSE
    END,
    CASE
        WHEN c.page_count > 0 AND COALESCE(rp.last_page, 1) >= c.page_count THEN rh.read_at
        ELSE NULL
    END
FROM reading_history rh
JOIN chapters c ON c.id = rh.chapter_id AND c.series_id = rh.series_id
LEFT JOIN reading_progress rp ON rp.user_id=rh.user_id AND rp.series_id=rh.series_id
WHERE rh.chapter_id IS NOT NULL
ON CONFLICT (user_id, chapter_id) DO NOTHING;
