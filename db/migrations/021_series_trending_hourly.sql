-- v1.1.4 RC4: durable hourly reader-trending aggregates.
-- Analytics is intentionally non-domain-critical: reader requests must not fail
-- if these counters cannot be recorded.

CREATE TABLE IF NOT EXISTS series_trending_hourly (
    series_id     UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    bucket_start  TIMESTAMPTZ NOT NULL,
    open_count    BIGINT NOT NULL DEFAULT 0 CHECK (open_count >= 0),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (series_id, bucket_start)
);

CREATE INDEX IF NOT EXISTS idx_series_trending_hourly_bucket
    ON series_trending_hourly(bucket_start DESC, series_id);
