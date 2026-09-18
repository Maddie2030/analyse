-- MReader v1.1.4 RC6 — Smart Library monotonic reading state
-- Keep the last-opened chapter for Resume while separately remembering the
-- furthest chapter number reached so rereading an older chapter does not make
-- already-read chapters appear unread again.

ALTER TABLE reading_history
    ADD COLUMN IF NOT EXISTS furthest_chapter_id UUID NULL
    REFERENCES chapters(id) ON DELETE SET NULL;

UPDATE reading_history
SET furthest_chapter_id = chapter_id
WHERE furthest_chapter_id IS NULL;

COMMENT ON COLUMN reading_history.chapter_id IS
'Last chapter opened for resume/recency behavior.';

COMMENT ON COLUMN reading_history.furthest_chapter_id IS
'Monotonic furthest chapter reached for Smart Library unread/caught-up state. Backfilled from chapter_id for pre-RC6 rows.';
