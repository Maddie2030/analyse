"""Runtime PostgreSQL bind-inference regressions for raw worker SQL.

These statements are PREPAREd without parameter type declarations on purpose.
That asks PostgreSQL to infer the bind types exactly as asyncpg/pgx prepared
statements do, catching text/varchar and similar ambiguity before a worker job
hits the query in production.
"""


def _prepare(db, name: str, statement: str) -> None:
    with db.cursor() as cur:
        cur.execute(f"DEALLOCATE ALL")
        cur.execute(f"PREPARE {name} AS {statement}")
        cur.execute(f"DEALLOCATE {name}")


def test_scraper_stage_completion_status_bind_is_unambiguous(db):
    _prepare(
        db,
        "mreader_stage_status_bind",
        """
        UPDATE scraper_series_drafts
        SET
            workflow_status = $2::varchar(32),
            error_message = CASE
                WHEN $2::varchar(32) = 'failed'
                THEN 'One or more selected chapters failed staging.'
                ELSE NULL
            END,
            updated_at = NOW()
        WHERE id = $1::uuid
        """,
    )


def test_scraper_single_publish_status_bind_is_unambiguous(db):
    _prepare(
        db,
        "mreader_single_publish_status_bind",
        """
        UPDATE scraper_series_drafts
        SET
            workflow_status = $2::varchar(32),
            publish_progress = COALESCE(publish_progress, '{}'::jsonb) || $3::jsonb,
            error_message = CASE
                WHEN $2::varchar(32) = 'published_partial'
                THEN 'Some chapters are live while others still need staging or publish retry.'
                WHEN $2::varchar(32) = 'published' THEN NULL
                ELSE error_message
            END,
            updated_at = NOW()
        WHERE id = $1::uuid
        """,
    )


def test_scraper_full_publish_status_bind_is_unambiguous(db):
    _prepare(
        db,
        "mreader_full_publish_status_bind",
        """
        UPDATE scraper_series_drafts
        SET
            workflow_status = $2::varchar(32),
            publish_finished_at = NOW(),
            error_message = CASE
                WHEN $2::varchar(32) = 'published_partial'
                THEN 'One or more chapters were skipped or failed publish.'
                ELSE NULL
            END,
            publish_progress = publish_progress || $3::jsonb,
            updated_at = NOW()
        WHERE id = $1::uuid
        """,
    )


def test_social_retention_interval_bind_is_integer_compatible(db):
    _prepare(
        db,
        "mreader_retention_interval_bind",
        "SELECT NOW() - make_interval(days => $1::int)",
    )
