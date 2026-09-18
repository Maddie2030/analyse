-- Progress Go stores browser scroll position as a fractional value in [0, 1].
-- Preserve every existing row while correcting the legacy INTEGER column type.

ALTER TABLE reading_progress
    ALTER COLUMN scroll_position TYPE DOUBLE PRECISION
        USING scroll_position::DOUBLE PRECISION,
    ALTER COLUMN scroll_position SET DEFAULT 0;
