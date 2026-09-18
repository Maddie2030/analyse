-- RC4.38 pressure-path indexes.
-- Social metrics and Catalog popular sorting filter bookmarks by series_id.
-- The existing UNIQUE(user_id, series_id) cannot efficiently serve that
-- leading-column pattern when the user id is unknown.
CREATE INDEX IF NOT EXISTS idx_bookmarks_series_id
    ON bookmarks(series_id);

-- Keep notification unread-count scans index-only-friendly for realtime/user
-- hot paths while preserving the existing partial-index semantics.
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread_created
    ON notifications(user_id, created_at DESC)
    WHERE is_read = FALSE;

-- Resolve Reader/Progress chapter targets by series + slug + published status
-- without scanning all chapters in a large series.
CREATE INDEX IF NOT EXISTS idx_chapters_series_slug_published
    ON chapters(series_id, slug)
    WHERE status = 'published';
