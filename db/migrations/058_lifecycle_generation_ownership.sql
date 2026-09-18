-- RC4.85 P07.4: generation-bound production object ownership for cleanup safety.
-- Existing rows are preserved. Where durable Media/Catalog evidence is available,
-- backfill the generation; otherwise 0 means legacy/unknown and Lifecycle remains
-- path-conservative before physical deletion.

ALTER TABLE pages
    ADD COLUMN IF NOT EXISTS media_generation BIGINT NOT NULL DEFAULT 0;
ALTER TABLE pages
    DROP CONSTRAINT IF EXISTS pages_media_generation_check,
    ADD CONSTRAINT pages_media_generation_check CHECK (media_generation >= 0);

ALTER TABLE series
    ADD COLUMN IF NOT EXISTS cover_media_generation BIGINT NOT NULL DEFAULT 0;
ALTER TABLE series
    DROP CONSTRAINT IF EXISTS series_cover_media_generation_check,
    ADD CONSTRAINT series_cover_media_generation_check CHECK (cover_media_generation >= 0);

WITH latest_receipt AS (
    SELECT DISTINCT ON (chapter_id)
           chapter_id, operation_id
    FROM catalog_mutation_receipts
    ORDER BY chapter_id, created_at DESC
), current_generation AS (
    SELECT r.chapter_id, e.media_generation
    FROM latest_receipt r
    JOIN media_completion_evidence_v1 e ON e.operation_id = r.operation_id
    WHERE e.media_generation > 0
)
UPDATE pages p
SET media_generation = g.media_generation
FROM current_generation g
WHERE p.chapter_id = g.chapter_id
  AND p.media_generation = 0;

WITH current_cover_generation AS (
    SELECT DISTINCT ON (m.series_id)
           m.series_id, m.media_generation
    FROM media_operations m
    JOIN series s ON s.id = m.series_id
    WHERE m.job_type = 'thumbnail-generation'
      AND m.status = 'completed'
      AND m.media_generation > 0
      AND s.cover_image_path IS NOT NULL
      AND m.output_paths ? s.cover_image_path
    ORDER BY m.series_id, m.completed_at DESC NULLS LAST, m.updated_at DESC
)
UPDATE series s
SET cover_media_generation = g.media_generation
FROM current_cover_generation g
WHERE s.id = g.series_id
  AND s.cover_media_generation = 0;

COMMENT ON COLUMN pages.media_generation IS
    'Media worker generation that produced the currently published primary/responsive page objects; 0 is legacy/unknown.';
COMMENT ON COLUMN series.cover_media_generation IS
    'Media worker generation that produced the currently attached cover object; 0 is legacy/unknown or no cover.';
