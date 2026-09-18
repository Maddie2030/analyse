-- RC4.85 reading command ordering and one Progress-owned read projection.
-- Apply under the normal serialized maintenance-window migration runner.
-- No application clock or cache may arbitrate a command after this migration.

ALTER TABLE reading_progress
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS session_generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS command_sequence BIGINT NOT NULL DEFAULT 0;

ALTER TABLE chapter_reads
    ADD COLUMN IF NOT EXISTS resume_page INTEGER CHECK (resume_page >= 1),
    ADD COLUMN IF NOT EXISTS resume_scroll_position DOUBLE PRECISION CHECK (resume_scroll_position BETWEEN 0 AND 1),
    ADD COLUMN IF NOT EXISTS session_generation BIGINT NOT NULL DEFAULT 0 CHECK (session_generation >= 0),
    ADD COLUMN IF NOT EXISTS command_sequence BIGINT NOT NULL DEFAULT 0 CHECK (command_sequence >= 0),
    ADD COLUMN IF NOT EXISTS command_id UUID,
    ADD COLUMN IF NOT EXISTS command_hash TEXT,
    ADD COLUMN IF NOT EXISTS open_command_id UUID,
    ADD COLUMN IF NOT EXISTS open_expected_revision BIGINT,
    ADD COLUMN IF NOT EXISTS provenance TEXT NOT NULL DEFAULT 'legacy';

-- Preserve exact matching resume evidence. Never assign chapter A's checkpoint
-- to chapter B, and never manufacture markers for intervening chapters.
INSERT INTO chapter_reads (
    user_id, series_id, chapter_id, first_read_at, last_read_at, last_page,
    completed, completed_at, resume_page, resume_scroll_position, provenance
)
SELECT rp.user_id, rp.series_id, rp.chapter_id, rp.updated_at, rp.updated_at,
       GREATEST(1, LEAST(rp.last_page, GREATEST(c.page_count, 1))),
       c.page_count > 0 AND rp.last_page >= c.page_count,
       CASE WHEN c.page_count > 0 AND rp.last_page >= c.page_count THEN rp.updated_at END,
       GREATEST(1, LEAST(rp.last_page, GREATEST(c.page_count, 1))),
       GREATEST(0, LEAST(rp.scroll_position, 1)), 'legacy'
FROM reading_progress rp
JOIN chapters c ON c.id=rp.chapter_id AND c.series_id=rp.series_id
ON CONFLICT (user_id, chapter_id) DO NOTHING;

UPDATE chapter_reads cr
SET resume_page=GREATEST(1, LEAST(rp.last_page, GREATEST(c.page_count, 1))),
    resume_scroll_position=GREATEST(0, LEAST(rp.scroll_position, 1))
FROM reading_progress rp, chapters c
WHERE cr.user_id=rp.user_id AND cr.series_id=rp.series_id
  AND cr.chapter_id=rp.chapter_id AND c.id=cr.chapter_id
  AND cr.resume_page IS NULL AND cr.session_generation=0;

-- Earlier releases wrote opens to the ledger before resume persistence. Reconcile
-- that evidence exactly once, then last_opened_at is changed only by accepted open.
WITH latest AS (
    SELECT DISTINCT ON (cr.user_id, cr.series_id)
        cr.user_id, cr.series_id, cr.chapter_id, cr.last_read_at,
        COALESCE(cr.resume_page, GREATEST(1, LEAST(cr.last_page, GREATEST(c.page_count, 1)))) AS page,
        COALESCE(cr.resume_scroll_position, 0) AS scroll
    FROM chapter_reads cr
    JOIN chapters c ON c.id=cr.chapter_id AND c.series_id=cr.series_id
    ORDER BY cr.user_id, cr.series_id, cr.last_read_at DESC, c.chapter_number DESC, cr.chapter_id
)
UPDATE reading_progress rp
SET chapter_id=CASE WHEN l.last_read_at > rp.updated_at THEN l.chapter_id ELSE rp.chapter_id END,
    last_page=CASE WHEN l.last_read_at > rp.updated_at AND l.chapter_id IS DISTINCT FROM rp.chapter_id THEN l.page ELSE rp.last_page END,
    scroll_position=CASE WHEN l.last_read_at > rp.updated_at AND l.chapter_id IS DISTINCT FROM rp.chapter_id THEN l.scroll ELSE rp.scroll_position END,
    last_opened_at=GREATEST(l.last_read_at, rp.updated_at)
FROM latest l
WHERE l.user_id=rp.user_id AND l.series_id=rp.series_id AND rp.last_opened_at IS NULL;

INSERT INTO reading_progress (
    user_id, series_id, chapter_id, last_page, scroll_position, updated_at, last_opened_at
)
SELECT DISTINCT ON (cr.user_id, cr.series_id)
    cr.user_id, cr.series_id, cr.chapter_id,
    COALESCE(cr.resume_page, GREATEST(1, LEAST(cr.last_page, GREATEST(c.page_count, 1)))),
    COALESCE(cr.resume_scroll_position, 0), cr.last_read_at, cr.last_read_at
FROM chapter_reads cr
JOIN chapters c ON c.id=cr.chapter_id AND c.series_id=cr.series_id
ORDER BY cr.user_id, cr.series_id, cr.last_read_at DESC, c.chapter_number DESC, cr.chapter_id
ON CONFLICT (user_id, series_id) DO NOTHING;

-- The final canonical target can come from ledger-only history or from a ledger
-- row newer than the old resume row. Preserve that selected checkpoint on the
-- chapter ledger so opening another chapter and returning does not reset it.
-- Do not overwrite checkpoint evidence already owned by a command session.
UPDATE chapter_reads cr
SET resume_page=GREATEST(1, LEAST(rp.last_page, GREATEST(c.page_count, 1))),
    resume_scroll_position=GREATEST(0, LEAST(rp.scroll_position, 1))
FROM reading_progress rp, chapters c
WHERE cr.user_id=rp.user_id AND cr.series_id=rp.series_id
  AND cr.chapter_id=rp.chapter_id AND c.id=cr.chapter_id
  AND cr.resume_page IS NULL AND cr.session_generation=0;

UPDATE reading_progress SET last_opened_at=updated_at WHERE last_opened_at IS NULL;
ALTER TABLE reading_progress ALTER COLUMN last_opened_at SET DEFAULT NOW();
ALTER TABLE reading_progress ALTER COLUMN last_opened_at SET NOT NULL;
ALTER TABLE reading_progress DROP CONSTRAINT IF EXISTS ck_reading_progress_revision_positive;
ALTER TABLE reading_progress ADD CONSTRAINT ck_reading_progress_revision_positive CHECK (revision BETWEEN 1 AND 9007199254740991);
ALTER TABLE reading_progress DROP CONSTRAINT IF EXISTS ck_reading_progress_ordering;
ALTER TABLE reading_progress ADD CONSTRAINT ck_reading_progress_ordering CHECK (
    session_generation BETWEEN 0 AND 9007199254740991 AND command_sequence BETWEEN 0 AND 9007199254740991
);

-- Deleting the current chapter invalidates its action target, not all of the
-- series' remaining reading evidence or its ordering fence.
ALTER TABLE reading_progress DROP CONSTRAINT IF EXISTS reading_progress_chapter_id_fkey;
ALTER TABLE reading_progress ADD CONSTRAINT reading_progress_chapter_id_fkey
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ix_chapter_reads_open_command
    ON chapter_reads(user_id, series_id, open_command_id) WHERE open_command_id IS NOT NULL;

CREATE OR REPLACE VIEW reading_state_v1 AS
SELECT rp.user_id, rp.series_id,
       EXISTS (SELECT 1 FROM chapter_reads cr WHERE cr.user_id=rp.user_id AND cr.series_id=rp.series_id) AS has_history,
       rp.chapter_id AS resume_chapter_id, rp.last_page, rp.scroll_position,
       rp.chapter_id AS last_opened_chapter_id, rp.last_opened_at,
       furthest.chapter_id AS furthest_chapter_id,
       furthest.chapter_number AS furthest_chapter_number,
       rp.updated_at, rp.revision, rp.session_generation, rp.command_sequence
FROM reading_progress rp
LEFT JOIN LATERAL (
    SELECT cr.chapter_id, c.chapter_number::float8
    FROM chapter_reads cr
    JOIN chapters c ON c.id=cr.chapter_id AND c.series_id=cr.series_id
    WHERE cr.user_id=rp.user_id AND cr.series_id=rp.series_id
    ORDER BY c.chapter_number DESC, cr.chapter_id
    LIMIT 1
) furthest ON TRUE;

COMMENT ON VIEW reading_state_v1 IS
    'Progress-owned live reading projection. Resume/last-open from accepted commands; furthest from exact ledger. Consumers must scope by user_id.';
