# RC4.28 fresh baseline cleanup

The user confirmed there is no published content that needs compatibility with older page codecs.

RC4.28 therefore removes obsolete v2/v3 page-codec runtime paths and the old page-encoding backfill utility. New publication uses only the current v4 overlap tile-pack format. The database migration rejects unexpected non-v4 page rows instead of silently making old content unreadable.

The active scraper tables were audited rather than deleted by name. `scraper_drafts` and `scraper_batch_*` are still used by existing-series/manual batch workflows. `scraper_series_*` is used by full-series discovery/staging/publishing. `scraper_storage_attempts`, operation events, lifecycle jobs, media operations and the event outbox are active durability/idempotency components and remain required.

Historical codec-only migrations were removed where the current `db/init.sql` plus the RC4.28 migration provides the current page schema. Other migrations remain because they are still required to construct the complete active schema on a fresh database.

Old RC-specific upgrade/audit documents that no longer describe the fresh baseline were removed from the release package.
