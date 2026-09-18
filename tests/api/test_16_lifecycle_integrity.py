import os
import time
import uuid

import requests

from helpers import assert_status, wait_until


FILER = os.getenv("TEST_SEAWEEDFS_FILER_URL", "http://seaweedfs-filer:8888").rstrip("/")


def test_series_delete_cascades_relational_and_external_state(
    admin_user, regular_user, db, webp_bytes
):
    token = uuid.uuid4().hex[:10]
    slug = f"lifecycle-{token}"
    page_path = f"{slug}/chapter-1/0001.webp"

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO series(title, slug, status) VALUES (%s,%s,'ongoing') RETURNING id::text",
            (f"Lifecycle {token}", slug),
        )
        series_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO chapters(series_id, chapter_number, title, slug, status, page_count)
            VALUES (%s::uuid,1,'Chapter 1','chapter-1','published',1)
            RETURNING id::text
            """,
            (series_id,),
        )
        chapter_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO pages(
                chapter_id,page_number,image_path,width,height,
                encoding_version,encoding_rows,encoding_columns,encoding_seed
            )
            VALUES (%s::uuid,1,%s,24,32,4,1,1,%s)
            """,
            (chapter_id, page_path, f"lifecycle-v4-{token}-0001"),
        )
        cur.execute(
            "INSERT INTO reading_progress(user_id,series_id,chapter_id,last_page) VALUES (%s::uuid,%s::uuid,%s::uuid,1)",
            (regular_user.user_id, series_id, chapter_id),
        )
        cur.execute(
            "INSERT INTO chapter_reads(user_id,series_id,chapter_id) VALUES (%s::uuid,%s::uuid,%s::uuid)",
            (regular_user.user_id, series_id, chapter_id),
        )
        cur.execute(
            "INSERT INTO bookmarks(user_id,series_id) VALUES (%s::uuid,%s::uuid)",
            (regular_user.user_id, series_id),
        )
        cur.execute(
            "INSERT INTO subscriptions(user_id,series_id) VALUES (%s::uuid,%s::uuid)",
            (regular_user.user_id, series_id),
        )
        cur.execute(
            "INSERT INTO comments(user_id,series_id,chapter_id,content) VALUES (%s::uuid,%s::uuid,%s::uuid,'lifecycle test')",
            (regular_user.user_id, series_id, chapter_id),
        )
        cur.execute(
            "INSERT INTO notifications(user_id,series_id,chapter_id,message) VALUES (%s::uuid,%s::uuid,%s::uuid,'lifecycle test')",
            (regular_user.user_id, series_id, chapter_id),
        )

    uploaded = requests.put(
        f"{FILER}/{page_path}", data=webp_bytes,
        headers={"Content-Type": "image/webp"}, timeout=20,
    )
    uploaded.raise_for_status()

    deleted = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=20)
    assert_status(deleted, 204)

    # A retry after the successful transaction must not enqueue duplicate cleanup
    # work or pretend the already-deleted aggregate still exists.
    repeated = admin_user.session.delete(f"/api/catalog/series/{series_id}", timeout=20)
    assert_status(repeated, 404)
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM lifecycle_cleanup_jobs WHERE entity_type='series' AND entity_id=%s::uuid",
            (series_id,),
        )
        assert cur.fetchone()[0] == 1

    # PostgreSQL cascades are part of the delete transaction and should be gone
    # before the API returns success.
    with db.cursor() as cur:
        for table, column, value in (
            ("series", "id", series_id),
            ("chapters", "series_id", series_id),
            ("reading_progress", "series_id", series_id),
            ("chapter_reads", "series_id", series_id),
            ("bookmarks", "series_id", series_id),
            ("subscriptions", "series_id", series_id),
            ("comments", "series_id", series_id),
            ("notifications", "series_id", series_id),
        ):
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=%s::uuid", (value,))
            assert cur.fetchone()[0] == 0, table
        cur.execute("SELECT COUNT(*) FROM pages WHERE chapter_id=%s::uuid", (chapter_id,))
        assert cur.fetchone()[0] == 0

    def cleanup_finished():
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT status FROM lifecycle_cleanup_jobs
                WHERE entity_type='series' AND entity_id=%s::uuid
                ORDER BY created_at DESC LIMIT 1
                """,
                (series_id,),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] in {"completed", "failed"} else None

    state = wait_until(cleanup_finished, timeout=90, interval=1, description="series lifecycle cleanup")
    assert state == "completed"

    # Filer storage is post-commit cleanup and therefore eventually consistent.
    response = requests.get(f"{FILER}/{page_path}", timeout=10)
    assert response.status_code == 404
