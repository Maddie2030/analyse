-- v1.1.4 RC5: admin-managed Browse curation.
-- Editor Picks and announcements are PostgreSQL-owned product content so the
-- frontend never needs hard-coded promotional arrays.

CREATE TABLE IF NOT EXISTS editor_picks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    label VARCHAR(80) NULL,
    note VARCHAR(280) NULL,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    starts_at TIMESTAMPTZ NULL,
    ends_at TIMESTAMPTZ NULL,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT editor_picks_schedule_check CHECK (
        ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at
    ),
    CONSTRAINT editor_picks_series_unique UNIQUE (series_id)
);

CREATE INDEX IF NOT EXISTS idx_editor_picks_public
    ON editor_picks (position, created_at)
    WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS announcements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(120) NOT NULL,
    body VARCHAR(1000) NOT NULL,
    link_url VARCHAR(1000) NULL,
    link_label VARCHAR(80) NULL,
    tone VARCHAR(16) NOT NULL DEFAULT 'info'
        CHECK (tone IN ('info', 'success', 'warning', 'critical')),
    dismissible BOOLEAN NOT NULL DEFAULT TRUE,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    starts_at TIMESTAMPTZ NULL,
    ends_at TIMESTAMPTZ NULL,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT announcements_schedule_check CHECK (
        ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at
    )
);

CREATE INDEX IF NOT EXISTS idx_announcements_public
    ON announcements (position, created_at DESC)
    WHERE is_active = TRUE;

COMMENT ON TABLE editor_picks IS
    'Admin-managed ordered Browse recommendations. Public reads include only active entries inside their schedule window.';
COMMENT ON TABLE announcements IS
    'Admin-managed scheduled Browse banners. Public reads include only active entries inside their schedule window.';
