-- RC4.28 fresh-start baseline hardening.
-- There is no published content to preserve, so page delivery is v4-only.

ALTER TABLE scraper_series_drafts
    ADD COLUMN IF NOT EXISTS source_url_key TEXT;

UPDATE scraper_series_drafts
SET source_url_key = lower(regexp_replace(btrim(source_url), '/+$', ''))
WHERE source_url_key IS NULL OR btrim(source_url_key) = '';

CREATE INDEX IF NOT EXISTS ix_scraper_series_active_source
    ON scraper_series_drafts(source_url_key, workflow_status, acknowledged_at, created_at);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pages
        WHERE COALESCE(encoding_version, 0) <> 4
    ) THEN
        RAISE EXCEPTION 'RC4.28 fresh baseline requires all existing pages to use encoding v4. User declared no published data; remove/re-publish old content before upgrading.';
    END IF;
END $$;

ALTER TABLE pages
    ALTER COLUMN encoding_version SET DEFAULT 4;

ALTER TABLE pages
    DROP CONSTRAINT IF EXISTS ck_pages_encoding_metadata;

ALTER TABLE pages
    ADD CONSTRAINT ck_pages_encoding_metadata CHECK (
        encoding_version = 4
        AND encoding_rows BETWEEN 1 AND 32
        AND encoding_columns BETWEEN 1 AND 32
        AND encoding_seed IS NOT NULL
        AND length(encoding_seed) >= 16
    );
