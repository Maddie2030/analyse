-- RC4.82: consolidate reading state ownership.
-- reading_progress = one resume/checkpoint row per user+series.
-- chapter_reads = durable per-chapter reading/history/completion ledger.
-- reading_history was a transition-era materialized projection and is removed.

INSERT INTO chapter_reads(
    user_id, series_id, chapter_id, first_read_at, last_read_at, last_page, completed, completed_at
)
SELECT
    rh.user_id, rh.series_id, rh.chapter_id, rh.read_at, rh.read_at,
    GREATEST(COALESCE(rp.last_page, 1), 1),
    CASE WHEN COALESCE(c.page_count, 0) > 0 AND COALESCE(rp.last_page, 1) >= c.page_count THEN TRUE ELSE FALSE END,
    CASE WHEN COALESCE(c.page_count, 0) > 0 AND COALESCE(rp.last_page, 1) >= c.page_count THEN rh.read_at ELSE NULL END
FROM reading_history rh
JOIN chapters c ON c.id=rh.chapter_id AND c.series_id=rh.series_id
LEFT JOIN reading_progress rp ON rp.user_id=rh.user_id AND rp.series_id=rh.series_id
WHERE rh.chapter_id IS NOT NULL
ON CONFLICT (user_id, chapter_id) DO UPDATE SET
    first_read_at = LEAST(chapter_reads.first_read_at, EXCLUDED.first_read_at),
    last_read_at = GREATEST(chapter_reads.last_read_at, EXCLUDED.last_read_at),
    last_page = GREATEST(chapter_reads.last_page, EXCLUDED.last_page),
    completed = chapter_reads.completed OR EXCLUDED.completed,
    completed_at = COALESCE(chapter_reads.completed_at, EXCLUDED.completed_at);

DROP TABLE IF EXISTS reading_history;

CREATE INDEX IF NOT EXISTS ix_chapter_reads_user_last_read
    ON chapter_reads(user_id, last_read_at DESC);
CREATE INDEX IF NOT EXISTS ix_chapter_reads_user_series_chapter
    ON chapter_reads(user_id, series_id, chapter_id);
