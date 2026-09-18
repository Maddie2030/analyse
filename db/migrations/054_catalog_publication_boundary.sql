-- RC4.85: durable Media publication evidence and Catalog publication receipts.
-- Media keeps transformation evidence in its existing operation ledger; Catalog owns
-- the only new idempotency/result table. Existing rows intentionally remain without
-- publication evidence until a current Media workflow records it.

ALTER TABLE media_operations
    ADD COLUMN IF NOT EXISTS media_generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS publication_operation_id UUID NULL,
    ADD COLUMN IF NOT EXISTS publication_actor_id UUID NULL,
    ADD COLUMN IF NOT EXISTS source_revision BIGINT NULL,
    ADD COLUMN IF NOT EXISTS manifest_sha256 CHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS publication_page_count INTEGER NULL,
    ADD COLUMN IF NOT EXISTS completion_evidence JSONB NULL;

ALTER TABLE media_operations
    DROP CONSTRAINT IF EXISTS media_operations_media_generation_check,
    ADD CONSTRAINT media_operations_media_generation_check
        CHECK (media_generation >= 0),
    DROP CONSTRAINT IF EXISTS media_operations_publication_page_count_check,
    ADD CONSTRAINT media_operations_publication_page_count_check
        CHECK (publication_page_count IS NULL OR publication_page_count BETWEEN 1 AND 4096),
    DROP CONSTRAINT IF EXISTS media_operations_manifest_sha256_check,
    ADD CONSTRAINT media_operations_manifest_sha256_check
        CHECK (manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$'),
    DROP CONSTRAINT IF EXISTS media_operations_completion_evidence_check,
    ADD CONSTRAINT media_operations_completion_evidence_check
        CHECK (
            completion_evidence IS NULL
            OR (
                jsonb_typeof(completion_evidence) = 'object'
                AND
                status = 'completed'
                AND media_generation > 0
                AND publication_operation_id IS NOT NULL
                AND publication_actor_id IS NOT NULL
                AND source_revision IS NOT NULL AND source_revision >= 1
                AND manifest_sha256 IS NOT NULL
                AND publication_page_count IS NOT NULL
            )
        );

CREATE INDEX IF NOT EXISTS idx_media_operations_publication_operation
    ON media_operations(publication_operation_id)
    WHERE publication_operation_id IS NOT NULL;

CREATE OR REPLACE VIEW media_completion_evidence_v1 AS
SELECT
    operation_id AS media_operation_id,
    publication_operation_id AS operation_id,
    publication_actor_id AS actor_id,
    source_revision,
    media_generation,
    publication_page_count AS page_count,
    manifest_sha256,
    completion_evidence,
    completed_at,
    updated_at
FROM media_operations
WHERE status = 'completed'
  AND completion_evidence IS NOT NULL
  AND publication_operation_id IS NOT NULL
  AND publication_actor_id IS NOT NULL
  AND manifest_sha256 IS NOT NULL
  AND publication_page_count IS NOT NULL;

ALTER TABLE series
    ADD COLUMN IF NOT EXISTS catalog_revision BIGINT NOT NULL DEFAULT 1;
ALTER TABLE series
    DROP CONSTRAINT IF EXISTS series_catalog_revision_check,
    ADD CONSTRAINT series_catalog_revision_check CHECK (catalog_revision >= 1);

ALTER TABLE chapters
    ADD COLUMN IF NOT EXISTS catalog_revision BIGINT NOT NULL DEFAULT 1;
ALTER TABLE chapters
    DROP CONSTRAINT IF EXISTS chapters_catalog_revision_check,
    ADD CONSTRAINT chapters_catalog_revision_check CHECK (catalog_revision >= 1);

CREATE TABLE IF NOT EXISTS catalog_mutation_receipts (
    idempotency_key UUID PRIMARY KEY,
    operation_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    payload_sha256 CHAR(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    series_id UUID NOT NULL,
    chapter_id UUID NOT NULL,
    chapter_revision BIGINT NOT NULL CHECK (chapter_revision >= 1),
    series_revision BIGINT NOT NULL CHECK (series_revision >= 1),
    page_count INTEGER NOT NULL CHECK (page_count > 0),
    publication_event_id UUID NOT NULL,
    result JSONB NOT NULL CHECK (jsonb_typeof(result) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_catalog_mutation_receipts_operation
    ON catalog_mutation_receipts(operation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_catalog_mutation_receipts_chapter
    ON catalog_mutation_receipts(chapter_id, created_at DESC);

COMMENT ON VIEW media_completion_evidence_v1 IS
    'Read-only v1 Media completion evidence consumed by Catalog publication commands.';
COMMENT ON TABLE catalog_mutation_receipts IS
    'Catalog-owned durable idempotency outcomes for production catalog mutations.';
