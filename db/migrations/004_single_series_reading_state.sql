-- Add the series key needed for one saved state per series.
ALTER TABLE reading_progress
    ADD COLUMN IF NOT EXISTS series_id UUID REFERENCES series(id) ON DELETE CASCADE;

UPDATE reading_progress rp
SET series_id = c.series_id
FROM chapters c
WHERE c.id = rp.chapter_id AND rp.series_id IS NULL;

-- Keep only the newest saved state for each user and series.
DELETE FROM reading_progress older
USING reading_progress newer
WHERE older.user_id = newer.user_id
  AND older.series_id = newer.series_id
  AND (older.updated_at < newer.updated_at OR (older.updated_at = newer.updated_at AND older.id < newer.id));

DELETE FROM reading_history older
USING reading_history newer
WHERE older.user_id = newer.user_id
  AND older.series_id = newer.series_id
  AND (older.read_at < newer.read_at OR (older.read_at = newer.read_at AND older.id < newer.id));

CREATE UNIQUE INDEX IF NOT EXISTS uq_reading_progress_user_series
    ON reading_progress(user_id, series_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_reading_history_user_series
    ON reading_history(user_id, series_id);
