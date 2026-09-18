-- Persistent scraper operations dashboard + durable discovery queue state.
-- A series-draft row now exists from the moment discovery is queued, so
-- browser refreshes and worker restarts cannot erase progress visibility.

ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS discovery_options JSONB NOT NULL
        DEFAULT '{"recursive":true,"max_depth":1,"max_pages":20}'::jsonb,
    ADD COLUMN IF NOT EXISTS discovery_progress JSONB NOT NULL
        DEFAULT '{"phase":"not_started","percent":0,"message":"Discovery has not started."}'::jsonb,
    ADD COLUMN IF NOT EXISTS discovery_attempt INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS discovery_started_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS discovery_finished_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS discovery_worker_heartbeat_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS acknowledged_by UUID NULL REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_operations
    ON scraper_series_drafts(acknowledged_at, workflow_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_scraper_series_drafts_discovery_recovery
    ON scraper_series_drafts(workflow_status, discovery_worker_heartbeat_at)
    WHERE workflow_status IN ('queued_discovery', 'discovering');

-- Existing rows pre-date discovery progress. Mark their discovery phase as
-- complete so the operations dashboard does not imply that they are queued.
UPDATE scraper_series_drafts
SET discovery_progress = jsonb_build_object(
        'phase', 'completed',
        'percent', 100,
        'message', 'Discovery completed before persistent operation tracking was enabled.',
        'updated_at', NOW()
    ),
    discovery_finished_at = COALESCE(discovery_finished_at, created_at)
WHERE workflow_status NOT IN ('queued_discovery', 'discovering')
  AND COALESCE(discovery_progress->>'phase', 'not_started') = 'not_started';

ALTER TABLE scraper_series_draft_chapters
    ADD COLUMN IF NOT EXISTS stage_progress JSONB NOT NULL
        DEFAULT '{"phase":"not_started","percent":0,"message":"Chapter staging has not started.","pages_total":0,"pages_completed":0}'::jsonb,
    ADD COLUMN IF NOT EXISTS stage_started_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS stage_finished_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS stage_worker_heartbeat_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS ix_scraper_series_draft_chapters_stage_recovery
    ON scraper_series_draft_chapters(stage_status, stage_worker_heartbeat_at)
    WHERE stage_status IN ('queued','staging');

UPDATE scraper_series_draft_chapters
SET stage_progress = CASE
        WHEN stage_status IN ('ready','published') THEN
            jsonb_build_object('phase','completed','percent',100,'message','Staging completed before persistent operation tracking was enabled.','pages_total',jsonb_array_length(pages),'pages_completed',jsonb_array_length(pages),'updated_at',NOW())
        WHEN stage_status = 'error' THEN
            jsonb_build_object('phase','failed','percent',100,'message',COALESCE(error_message,'Staging failed.'),'pages_total',0,'pages_completed',0,'updated_at',NOW())
        ELSE stage_progress
    END
WHERE COALESCE(stage_progress->>'phase','not_started') = 'not_started';
