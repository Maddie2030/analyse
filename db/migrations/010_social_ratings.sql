CREATE TABLE IF NOT EXISTS series_ratings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_series_ratings_user_series UNIQUE (user_id, series_id)
);

CREATE INDEX IF NOT EXISTS ix_series_ratings_series_id
    ON series_ratings(series_id);
CREATE INDEX IF NOT EXISTS ix_series_ratings_user_id
    ON series_ratings(user_id);
