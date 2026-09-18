-- RC4.85 P07.5 canonical new-series operation status convergence.
-- Backfill one parent ingestion header for every durable series draft and link
-- already-created per-chapter publication operations to that parent.  This is
-- metadata-only: it does not restage, republish, delete, or rewrite media.

WITH chapter_counts AS (
    SELECT
        d.id AS draft_id,
        COUNT(c.id) FILTER (WHERE c.selected)::int AS selected_count,
        COUNT(c.id) FILTER (
            WHERE c.selected AND c.stage_status IN ('ready','published')
        )::int AS staged_count,
        COUNT(c.id) FILTER (
            WHERE c.publish_status='published' OR c.published_chapter_id IS NOT NULL
        )::int AS published_count,
        COUNT(c.id) FILTER (
            WHERE c.stage_status='error' OR c.publish_status IN ('failed','skipped')
        )::int AS failed_count
    FROM scraper_series_drafts d
    LEFT JOIN scraper_series_draft_chapters c ON c.draft_id=d.id
    GROUP BY d.id
)
INSERT INTO ingestion_operations (
    id, source_kind, requesting_actor_id, status, phase,
    source_revision, revision, lease_generation,
    selected_count, staged_count, published_count, failed_count,
    cancel_requested_at, acknowledged_at, error_code,
    created_at, updated_at
)
SELECT
    d.id,
    'new-series-scrape',
    d.created_by,
    CASE
        WHEN d.operation_cancel_requested_at IS NOT NULL AND d.workflow_status <> 'cancelled' THEN 'cancel_requested'
        WHEN d.workflow_status = 'queued_discovery' THEN 'queued'
        WHEN d.workflow_status = 'discovering' THEN 'running'
        WHEN d.workflow_status IN ('draft','ready') THEN 'needs_review'
        WHEN d.workflow_status = 'staging' THEN 'running'
        WHEN d.workflow_status = 'queued_publish' THEN 'queued'
        WHEN d.workflow_status = 'publishing' THEN 'running'
        WHEN d.workflow_status = 'published' THEN 'completed'
        WHEN d.workflow_status = 'published_partial' THEN 'completed_with_errors'
        WHEN d.workflow_status = 'cancel_requested' THEN 'cancel_requested'
        WHEN d.workflow_status = 'cancelled' THEN 'cancelled'
        WHEN d.workflow_status IN ('failed','duplicate') THEN 'failed'
        ELSE 'needs_review'
    END,
    CASE
        WHEN d.operation_cancel_requested_at IS NOT NULL AND d.workflow_status <> 'cancelled' THEN 'cancel_requested'
        WHEN d.workflow_status IN ('queued_discovery','discovering') THEN 'discovery'
        WHEN d.workflow_status IN ('draft','ready') THEN 'review'
        WHEN d.workflow_status = 'staging' THEN 'staging'
        WHEN d.workflow_status IN ('queued_publish','publishing') THEN 'publish'
        WHEN d.workflow_status IN ('published','published_partial') THEN 'completed'
        WHEN d.workflow_status = 'cancel_requested' THEN 'cancel_requested'
        WHEN d.workflow_status = 'cancelled' THEN 'cancelled'
        WHEN d.workflow_status = 'duplicate' THEN 'duplicate'
        WHEN d.workflow_status = 'failed' THEN 'failed'
        ELSE COALESCE(NULLIF(d.workflow_status,''),'review')
    END,
    1,
    1,
    1,
    COALESCE(cc.selected_count,0),
    COALESCE(cc.staged_count,0),
    COALESCE(cc.published_count,0),
    COALESCE(cc.failed_count,0),
    d.operation_cancel_requested_at,
    d.acknowledged_at,
    CASE
        WHEN d.workflow_status = 'published_partial' THEN 'partial_result'
        WHEN d.workflow_status IN ('failed','duplicate') THEN d.workflow_status
        ELSE NULL
    END,
    d.created_at,
    d.updated_at
FROM scraper_series_drafts d
JOIN chapter_counts cc ON cc.draft_id=d.id
ON CONFLICT (id) DO NOTHING;

UPDATE ingestion_operations io
SET parent_operation_id = c.draft_id,
    updated_at = NOW()
FROM scraper_series_draft_chapters c
WHERE io.id = c.id
  AND io.source_kind = 'new-series-scrape'
  AND io.parent_operation_id IS NULL
  AND EXISTS (
      SELECT 1
      FROM ingestion_operations parent
      WHERE parent.id = c.draft_id
        AND parent.source_kind = 'new-series-scrape'
  );

COMMENT ON COLUMN ingestion_operations.parent_operation_id IS
    'Optional canonical parent operation; new-series chapter publication operations point at the series-draft operation header.';
