-- Injected by the common runner INSIDE the pending 047/048 transaction.
-- RC4.81 is the supported legacy source. No permanent history mirror survives.
DO $preserve$
BEGIN
    IF to_regclass('public.reading_history') IS NULL THEN
        -- 047 predates fresh installations without this table. Its original SQL
        -- still runs unchanged, over an empty transaction-local compatibility input.
        CREATE TEMP TABLE IF NOT EXISTS reading_history (
            user_id UUID, series_id UUID, chapter_id UUID,
            furthest_chapter_id UUID, read_at TIMESTAMPTZ
        ) ON COMMIT DROP;
        RETURN;
    END IF;

    -- Protect the snapshot/copy/validation interval. This is not a replacement
    -- for quiescing old application writers across the entire upgrade.
    LOCK TABLE public.users, public.series, public.chapters,
               public.reading_history, public.reading_progress, public.chapter_reads
        IN SHARE ROW EXCLUSIVE MODE;

    CREATE TEMP TABLE rc485_history_evidence ON COMMIT DROP AS
    SELECT rh.user_id, rh.series_id, rh.chapter_id,
           (to_jsonb(rh)->>'furthest_chapter_id')::uuid AS furthest_chapter_id,
           rh.read_at
    FROM public.reading_history rh;

    IF EXISTS (
        SELECT 1 FROM rc485_history_evidence h
        LEFT JOIN public.users u ON u.id=h.user_id
        LEFT JOIN public.series s ON s.id=h.series_id
        LEFT JOIN public.chapters opened ON opened.id=h.chapter_id AND opened.series_id=h.series_id
        LEFT JOIN public.chapters reached ON reached.id=h.furthest_chapter_id AND reached.series_id=h.series_id
        WHERE u.id IS NULL OR s.id IS NULL OR h.read_at IS NULL
           OR (h.chapter_id IS NOT NULL AND opened.id IS NULL)
           OR (h.furthest_chapter_id IS NOT NULL AND reached.id IS NULL)
    ) THEN
        RAISE EXCEPTION 'Reading history preservation blocked: invalid owner, chapter link or event timestamp';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.reading_progress rp
        LEFT JOIN public.users u ON u.id=rp.user_id
        LEFT JOIN public.series s ON s.id=rp.series_id
        LEFT JOIN public.chapters c ON c.id=rp.chapter_id AND c.series_id=rp.series_id
        WHERE u.id IS NULL OR s.id IS NULL OR rp.updated_at IS NULL
           OR (rp.chapter_id IS NOT NULL AND c.id IS NULL)
    ) OR EXISTS (
        SELECT 1 FROM public.chapter_reads cr
        LEFT JOIN public.chapters c ON c.id=cr.chapter_id AND c.series_id=cr.series_id
        WHERE c.id IS NULL OR cr.first_read_at IS NULL OR cr.last_read_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Reading history preservation blocked: invalid existing canonical evidence';
    END IF;

    ALTER TABLE public.chapter_reads
        ADD COLUMN IF NOT EXISTS provenance TEXT NOT NULL DEFAULT 'legacy',
        ADD COLUMN IF NOT EXISTS resume_page INTEGER CHECK (resume_page >= 1),
        ADD COLUMN IF NOT EXISTS resume_scroll_position DOUBLE PRECISION CHECK (resume_scroll_position BETWEEN 0 AND 1);
    ALTER TABLE public.reading_progress ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ;

    CREATE TEMP TABLE rc485_checkpoint_evidence ON COMMIT DROP AS
    SELECT rp.user_id, rp.series_id, rp.chapter_id, rp.updated_at,
           GREATEST(1, LEAST(rp.last_page, GREATEST(c.page_count, 1))) AS page,
           GREATEST(0, LEAST(rp.scroll_position, 1)) AS scroll,
           c.page_count > 0 AND rp.last_page >= c.page_count AS completed
    FROM public.reading_progress rp
    JOIN public.chapters c ON c.id=rp.chapter_id AND c.series_id=rp.series_id;

    -- A's checkpoint can supply evidence only for A, never for history chapter B.
    INSERT INTO public.chapter_reads (
        user_id, series_id, chapter_id, first_read_at, last_read_at, last_page,
        completed, completed_at, resume_page, resume_scroll_position, provenance
    )
    SELECT user_id, series_id, chapter_id, updated_at, updated_at, page,
           completed, CASE WHEN completed THEN updated_at END, page, scroll, 'legacy'
    FROM rc485_checkpoint_evidence
    ON CONFLICT (user_id, chapter_id) DO UPDATE SET
        first_read_at=CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.first_read_at
                           ELSE LEAST(chapter_reads.first_read_at, EXCLUDED.first_read_at) END,
        last_read_at=CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.last_read_at
                          ELSE GREATEST(chapter_reads.last_read_at, EXCLUDED.last_read_at) END,
        last_page=GREATEST(chapter_reads.last_page, EXCLUDED.last_page),
        completed=chapter_reads.completed OR EXCLUDED.completed,
        completed_at=COALESCE(chapter_reads.completed_at, EXCLUDED.completed_at),
        resume_page=EXCLUDED.resume_page, resume_scroll_position=EXCLUDED.resume_scroll_position,
        provenance=CASE WHEN chapter_reads.provenance='migrated_reach' THEN 'legacy' ELSE chapter_reads.provenance END
    WHERE COALESCE((to_jsonb(chapter_reads)->>'session_generation')::bigint, 0)=0;

    INSERT INTO public.chapter_reads (
        user_id, series_id, chapter_id, first_read_at, last_read_at, last_page,
        completed, completed_at, resume_page, resume_scroll_position, provenance
    )
    SELECT h.user_id, h.series_id, h.chapter_id, h.read_at, h.read_at, COALESCE(cp.page, 1),
           COALESCE(cp.completed, FALSE), CASE WHEN cp.completed THEN cp.updated_at END,
           cp.page, cp.scroll, 'legacy'
    FROM rc485_history_evidence h
    JOIN public.chapters c ON c.id=h.chapter_id AND c.series_id=h.series_id
    LEFT JOIN rc485_checkpoint_evidence cp
      ON cp.user_id=h.user_id AND cp.series_id=h.series_id AND cp.chapter_id=h.chapter_id
    ON CONFLICT (user_id, chapter_id) DO UPDATE SET
        first_read_at=CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.first_read_at
                           ELSE LEAST(chapter_reads.first_read_at, EXCLUDED.first_read_at) END,
        last_read_at=CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.last_read_at
                          ELSE GREATEST(chapter_reads.last_read_at, EXCLUDED.last_read_at) END,
        last_page=GREATEST(chapter_reads.last_page, EXCLUDED.last_page),
        completed=chapter_reads.completed OR EXCLUDED.completed,
        completed_at=COALESCE(chapter_reads.completed_at, EXCLUDED.completed_at),
        resume_page=COALESCE(chapter_reads.resume_page, EXCLUDED.resume_page),
        resume_scroll_position=COALESCE(chapter_reads.resume_scroll_position, EXCLUDED.resume_scroll_position),
        provenance=CASE WHEN chapter_reads.provenance='migrated_reach' THEN 'legacy' ELSE chapter_reads.provenance END
    WHERE COALESCE((to_jsonb(chapter_reads)->>'session_generation')::bigint, 0)=0;

    -- Independent reach is not an open, checkpoint or completion event. Its
    -- timestamp records when the legacy evidence was observed; 052 masks it from
    -- exact history/recency and a future real open replaces it with actual time.
    INSERT INTO public.chapter_reads (
        user_id, series_id, chapter_id, first_read_at, last_read_at, last_page,
        completed, completed_at, resume_page, resume_scroll_position, provenance
    )
    SELECT h.user_id, h.series_id, h.furthest_chapter_id, h.read_at, h.read_at, 1,
           FALSE, NULL, NULL, NULL, 'migrated_reach'
    FROM rc485_history_evidence h
    JOIN public.chapters c ON c.id=h.furthest_chapter_id AND c.series_id=h.series_id
    ON CONFLICT (user_id, chapter_id) DO NOTHING;

    CREATE TEMP TABLE rc485_latest_exact ON COMMIT DROP AS
    SELECT DISTINCT ON (cr.user_id, cr.series_id)
        cr.user_id, cr.series_id, cr.chapter_id, cr.last_read_at,
        GREATEST(1, LEAST(COALESCE(cr.resume_page, cr.last_page), GREATEST(c.page_count, 1))) AS page,
        COALESCE(cr.resume_scroll_position, 0) AS scroll
    FROM public.chapter_reads cr
    JOIN public.chapters c ON c.id=cr.chapter_id AND c.series_id=cr.series_id
    WHERE cr.provenance <> 'migrated_reach'
    ORDER BY cr.user_id, cr.series_id, cr.last_read_at DESC, c.chapter_number DESC NULLS LAST, cr.chapter_id;

    INSERT INTO public.reading_progress (
        user_id, series_id, chapter_id, last_page, scroll_position, updated_at, last_opened_at
    )
    SELECT user_id, series_id, chapter_id, page, scroll, last_read_at, last_read_at
    FROM rc485_latest_exact
    ON CONFLICT (user_id, series_id) DO UPDATE SET
        chapter_id=EXCLUDED.chapter_id, last_page=EXCLUDED.last_page, scroll_position=EXCLUDED.scroll_position,
        updated_at=GREATEST(reading_progress.updated_at, EXCLUDED.updated_at), last_opened_at=EXCLUDED.last_opened_at
    WHERE COALESCE((to_jsonb(reading_progress)->>'session_generation')::bigint, 0)=0;

    -- Keep a projection root for reach-only series without assigning that
    -- inferred chapter as resume. Non-null aggregate time prevents historical
    -- migration 051 from reselecting an inferred row; 052 masks this time.
    INSERT INTO public.reading_progress (
        user_id, series_id, chapter_id, last_page, scroll_position, updated_at, last_opened_at
    )
    SELECT cr.user_id, cr.series_id, NULL, 1, 0, MAX(cr.last_read_at), MAX(cr.last_read_at)
    FROM public.chapter_reads cr
    GROUP BY cr.user_id, cr.series_id
    ON CONFLICT (user_id, series_id) DO NOTHING;
    UPDATE public.reading_progress SET last_opened_at=updated_at WHERE last_opened_at IS NULL;

    IF EXISTS (
        SELECT 1 FROM rc485_history_evidence h
        WHERE (h.chapter_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.chapter_reads cr
            WHERE cr.user_id=h.user_id AND cr.series_id=h.series_id AND cr.chapter_id=h.chapter_id
              AND cr.provenance <> 'migrated_reach' AND cr.last_read_at >= h.read_at
        )) OR (h.furthest_chapter_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.chapter_reads cr
            WHERE cr.user_id=h.user_id AND cr.series_id=h.series_id AND cr.chapter_id=h.furthest_chapter_id
        ))
    ) OR EXISTS (
        SELECT 1 FROM rc485_checkpoint_evidence cp
        LEFT JOIN public.chapter_reads cr
          ON cr.user_id=cp.user_id AND cr.series_id=cp.series_id AND cr.chapter_id=cp.chapter_id
        WHERE cr.chapter_id IS NULL OR cr.provenance='migrated_reach'
           OR (COALESCE((to_jsonb(cr)->>'session_generation')::bigint, 0)=0 AND
               (cr.resume_page IS DISTINCT FROM cp.page OR cr.resume_scroll_position IS DISTINCT FROM cp.scroll
                OR (cp.completed AND NOT cr.completed)))
    ) THEN
        RAISE EXCEPTION 'Reading history preservation validation failed; source and migration ledger remain unchanged';
    END IF;

    -- The unchanged shipped migration must not see rows it would misassociate.
    -- Deletion, its subsequent DROP, canonical writes and both ledger entries
    -- all roll back together if any statement in this migration fails.
    DELETE FROM public.reading_history;
    INSERT INTO public.schema_migrations(version) VALUES ('rc485_reading_evidence_preserved_v1')
    ON CONFLICT (version) DO NOTHING;
END
$preserve$;
