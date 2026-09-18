-- v1.3.0 RC4.8: extend crash-recovery ledger to the legacy/existing-series draft workflow.

ALTER TABLE scraper_storage_attempts
    DROP CONSTRAINT IF EXISTS scraper_storage_attempts_operation_type_check;

ALTER TABLE scraper_storage_attempts
    ADD CONSTRAINT scraper_storage_attempts_operation_type_check CHECK (
        operation_type IN (
            'series_cover','chapter_publish','batch_publish','batch_stage_create',
            'existing_draft_publish','existing_draft_stage_create'
        )
    );
