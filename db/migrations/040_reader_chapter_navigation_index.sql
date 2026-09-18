-- RC4.43 upgrade-path guard for Reader prev/next chapter seeks.
-- Fresh installs already create this exact index in db/init.sql. Keeping the
-- same name here makes upgrades idempotent: existing databases pay no duplicate
-- index cost, while any legacy database missing it is repaired once.
CREATE INDEX IF NOT EXISTS idx_chapters_series_number
    ON chapters(series_id, chapter_number DESC)
    WHERE status = 'published';
