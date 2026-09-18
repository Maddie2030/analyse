-- RC4.82: re-run the idempotent Smart Library / History repair after hardening the synchronous open path.
--
-- RC4.79 fixed the normal flow, but RC4.82 deliberately replays the safe backfill so accounts affected during the transition recover materialized reading_history rows from surviving canonical Progress state.
-- Recover every user/series pair that is still represented by reading_progress
-- or chapter_reads, preserving the latest opened chapter and the furthest
-- chapter number reached. Future opens/commits are written synchronously by
-- progress-go and therefore do not depend on this backfill.

WITH candidates AS (
    SELECT
        rp.user_id,
        rp.series_id,
        rp.chapter_id,
        rp.updated_at AS read_at
    FROM reading_progress rp
    WHERE rp.user_id IS NOT NULL
      AND rp.series_id IS NOT NULL
      AND rp.chapter_id IS NOT NULL

    UNION ALL

    SELECT
        cr.user_id,
        cr.series_id,
        cr.chapter_id,
        cr.last_read_at AS read_at
    FROM chapter_reads cr
),
latest AS (
    SELECT DISTINCT ON (c.user_id, c.series_id)
        c.user_id,
        c.series_id,
        c.chapter_id,
        c.read_at
    FROM candidates c
    JOIN chapters ch ON ch.id = c.chapter_id AND ch.series_id = c.series_id
    ORDER BY c.user_id, c.series_id, c.read_at DESC, ch.chapter_number DESC
),
furthest AS (
    SELECT DISTINCT ON (c.user_id, c.series_id)
        c.user_id,
        c.series_id,
        c.chapter_id AS furthest_chapter_id
    FROM candidates c
    JOIN chapters ch ON ch.id = c.chapter_id AND ch.series_id = c.series_id
    ORDER BY c.user_id, c.series_id, ch.chapter_number DESC, c.read_at DESC
)
INSERT INTO reading_history(
    user_id,
    series_id,
    chapter_id,
    furthest_chapter_id,
    read_at
)
SELECT
    l.user_id,
    l.series_id,
    l.chapter_id,
    f.furthest_chapter_id,
    l.read_at
FROM latest l
JOIN furthest f USING (user_id, series_id)
ON CONFLICT (user_id, series_id)
DO UPDATE SET
    chapter_id = CASE
        WHEN reading_history.read_at <= EXCLUDED.read_at THEN EXCLUDED.chapter_id
        ELSE reading_history.chapter_id
    END,
    read_at = GREATEST(reading_history.read_at, EXCLUDED.read_at),
    furthest_chapter_id = CASE
        WHEN reading_history.furthest_chapter_id IS NULL THEN EXCLUDED.furthest_chapter_id
        WHEN EXCLUDED.furthest_chapter_id IS NULL THEN reading_history.furthest_chapter_id
        WHEN COALESCE((SELECT chapter_number FROM chapters WHERE id = reading_history.furthest_chapter_id), -1)
             >= COALESCE((SELECT chapter_number FROM chapters WHERE id = EXCLUDED.furthest_chapter_id), -1)
        THEN reading_history.furthest_chapter_id
        ELSE EXCLUDED.furthest_chapter_id
    END;
