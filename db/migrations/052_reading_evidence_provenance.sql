-- 051 already repairs surviving exact checkpoints once. Do not add another
-- runtime history source or guess evidence destroyed by an earlier upgrade.
DO $notice$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version='rc485_reading_evidence_preserved_v1')
       AND EXISTS (SELECT 1 FROM schema_migrations WHERE version='047_consolidate_reading_state_rc482.sql')
       AND EXISTS (SELECT 1 FROM chapter_reads) THEN
        RAISE NOTICE 'Legacy history was already retired without the RC4.85 preservation marker. Only surviving exact evidence is available; missing furthest or original checkpoint evidence requires a verified pre-upgrade backup.';
    END IF;
END
$notice$;

ALTER TABLE chapter_reads ADD CONSTRAINT ck_chapter_reads_inferred_reach CHECK (
    provenance <> 'migrated_reach' OR (
        NOT completed AND completed_at IS NULL AND resume_page IS NULL AND resume_scroll_position IS NULL
        AND session_generation=0 AND command_sequence=0 AND command_id IS NULL AND command_hash IS NULL
        AND open_command_id IS NULL AND open_expected_revision IS NULL
    )
);

CREATE OR REPLACE VIEW reading_state_v1 AS
SELECT rp.user_id, rp.series_id, exact.has_history,
       CASE WHEN exact.has_history THEN rp.chapter_id END AS resume_chapter_id,
       rp.last_page, rp.scroll_position,
       CASE WHEN exact.has_history THEN rp.chapter_id END AS last_opened_chapter_id,
       CASE WHEN exact.has_history THEN rp.last_opened_at END AS last_opened_at,
       furthest.chapter_id AS furthest_chapter_id,
       furthest.chapter_number AS furthest_chapter_number,
       rp.updated_at, rp.revision, rp.session_generation, rp.command_sequence
FROM reading_progress rp
CROSS JOIN LATERAL (
    SELECT EXISTS (
        SELECT 1 FROM chapter_reads cr
        WHERE cr.user_id=rp.user_id AND cr.series_id=rp.series_id AND cr.provenance <> 'migrated_reach'
    ) AS has_history
) exact
LEFT JOIN LATERAL (
    SELECT cr.chapter_id, c.chapter_number::float8
    FROM chapter_reads cr
    JOIN chapters c ON c.id=cr.chapter_id AND c.series_id=cr.series_id
    WHERE cr.user_id=rp.user_id AND cr.series_id=rp.series_id
    ORDER BY c.chapter_number DESC NULLS LAST, cr.chapter_id
    LIMIT 1
) furthest ON TRUE;

COMMENT ON VIEW reading_state_v1 IS
    'Progress-owned live reading projection. Exact reads own history/resume/recency; explicit legacy furthest evidence may extend reach without inventing read/completion events. Scope by user_id.';
