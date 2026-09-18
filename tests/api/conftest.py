from __future__ import annotations

import io
import json
import os
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path

import psycopg
import pytest
import requests
from PIL import Image

from helpers import ApiSession, Identity, JourneyRecorder, assert_status, safe_json


USER_BASE_URL = os.getenv(
    "TEST_USER_BASE_URL",
    "http://host.docker.internal:8080",
).rstrip("/")
ADMIN_BASE_URL = os.getenv(
    "TEST_ADMIN_BASE_URL",
    "http://host.docker.internal:8081",
).rstrip("/")
_raw_database_url = (
    os.getenv("TEST_DATABASE_URL")
    or os.getenv("KEDA_POSTGRES_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql://manhwa:manhwa@db:5432/manhwa"
)
DATABASE_URL = _raw_database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
SEAWEEDFS_FILER_URL = (
    os.getenv("TEST_SEAWEEDFS_FILER_URL")
    or os.getenv("SEAWEEDFS_FILER_URL")
    or ""
).rstrip("/")
RESULTS_DIR = Path(os.getenv("PYTEST_RESULTS_DIR", "/results"))
RUN_EXTERNAL = os.getenv("RUN_EXTERNAL_SCRAPER_TESTS", "false").lower() == "true"

RUN_ID = os.getenv("PYTEST_RUN_ID") or uuid.uuid4().hex[:10]
PREFIX = f"pytest_{RUN_ID}"
# API identity constraints are stricter than slugs/run labels. Keep a separate
# short alphanumeric token so generated usernames always satisfy Auth
# (letters/digits/underscores only, <=50 chars) and email local-parts stay <=64.
_ACCOUNT_RUN_TOKEN = re.sub(r"[^A-Za-z0-9]", "", RUN_ID).lower()[:18] or uuid.uuid4().hex[:10]
HTTP_EXCHANGE_LOG = RESULTS_DIR / "http_exchanges.jsonl"
JOURNEY_ACTION_LOG = RESULTS_DIR / "journey_actions.jsonl"

TEST_USER_USERNAME = os.getenv("MREADER_TEST_USER_USERNAME", "mreader_test_user")
TEST_USER_EMAIL = os.getenv("MREADER_TEST_USER_EMAIL", "mreader.diagnostics.user@gmail.com")
TEST_USER_PASSWORD = os.getenv("MREADER_TEST_USER_PASSWORD", "MReaderTest123!")
TEST_ADMIN_USERNAME = os.getenv("MREADER_TEST_ADMIN_USERNAME", "mreader_test_admin")
TEST_ADMIN_EMAIL = os.getenv("MREADER_TEST_ADMIN_EMAIL", "mreader.diagnostics.admin@gmail.com")
TEST_ADMIN_PASSWORD = os.getenv("MREADER_TEST_ADMIN_PASSWORD", TEST_USER_PASSWORD)
TEMP_EMAIL_DOMAIN = os.getenv("MREADER_TEST_TEMP_EMAIL_DOMAIN", "gmail.com")

_REPORTS: dict[str, list] = defaultdict(list)


def pytest_configure(config):
    config.addinivalue_line("markers", "permission: PostgreSQL runtime-role effective privilege oracle")
    config.addinivalue_line("markers", "boundary: gateway/CORS/routing boundary diagnostics")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if HTTP_EXCHANGE_LOG.exists():
        HTTP_EXCHANGE_LOG.unlink()
    if JOURNEY_ACTION_LOG.exists():
        JOURNEY_ACTION_LOG.unlink()
    # Keep the deterministic manual-test credentials in the diagnostic bundle.
    # These accounts are created only by the regression harness, never by normal
    # application startup.
    (RESULTS_DIR / "diagnostic_credentials.json").write_text(
        json.dumps(
            {
                "regular_user": {
                    "username": TEST_USER_USERNAME,
                    "email": TEST_USER_EMAIL,
                    "password": TEST_USER_PASSWORD,
                },
                "admin_user": {
                    "username": TEST_ADMIN_USERNAME,
                    "email": TEST_ADMIN_EMAIL,
                    "password": TEST_ADMIN_PASSWORD,
                },
                "scope": "diagnostics-only; seeded/reset when API regression runs",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def pytest_runtest_logreport(report):
    _REPORTS[report.nodeid].append(report)


def pytest_sessionfinish(session, exitstatus):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    final_records = []
    by_module: dict[str, list[dict]] = defaultdict(list)

    for nodeid, reports in sorted(_REPORTS.items()):
        call_report = next((r for r in reports if r.when == "call"), None)
        relevant = call_report

        if relevant is None:
            relevant = next(
                (r for r in reports if r.failed or r.skipped),
                reports[-1],
            )

        if relevant.passed:
            outcome = "passed"
        elif relevant.skipped:
            outcome = "skipped"
        else:
            outcome = "failed"

        duration = round(sum(r.duration for r in reports), 6)
        message = None
        if outcome != "passed":
            message = str(relevant.longrepr)[:10000]

        module = nodeid.split("::", 1)[0]

        record = {
            "nodeid": nodeid,
            "module": module,
            "outcome": outcome,
            "duration_seconds": duration,
            "message": message,
        }
        final_records.append(record)
        by_module[module].append(record)

    def summary(records):
        return {
            "total": len(records),
            "passed": sum(x["outcome"] == "passed" for x in records),
            "failed": sum(x["outcome"] == "failed" for x in records),
            "skipped": sum(x["outcome"] == "skipped" for x in records),
        }

    modules = {}
    for module, records in by_module.items():
        stem = Path(module).stem
        file_payload = {
            "run_id": RUN_ID,
            "module": module,
            "summary": summary(records),
            "tests": records,
        }
        report_path = RESULTS_DIR / f"{stem}.json"
        report_path.write_text(
            json.dumps(file_payload, indent=2, default=str),
            encoding="utf-8",
        )
        modules[module] = {
            "result_file": report_path.name,
            **summary(records),
        }

    payload = {
        "run_id": RUN_ID,
        "exitstatus": exitstatus,
        "summary": summary(final_records),
        "modules": modules,
        "tests": final_records,
        "http_exchange_log": HTTP_EXCHANGE_LOG.name,
    }
    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    print("MREADER_PYTEST_SUMMARY_JSON=" + json.dumps(payload["summary"], separators=(",", ":")))


@pytest.fixture(scope="session")
def db():
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def api():
    return ApiSession(USER_BASE_URL, HTTP_EXCHANGE_LOG)


@pytest.fixture
def anonymous():
    return ApiSession(USER_BASE_URL, HTTP_EXCHANGE_LOG)


@pytest.fixture
def admin_anonymous():
    return ApiSession(ADMIN_BASE_URL, HTTP_EXCHANGE_LOG)


@pytest.fixture
def journey(request):
    return JourneyRecorder(JOURNEY_ACTION_LOG, request.node.nodeid)


@pytest.fixture(scope="session")
def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (24, 32), (220, 220, 220)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="session")
def webp_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (24, 32), (220, 220, 220)).save(
        buffer,
        format="WEBP",
        quality=80,
    )
    return buffer.getvalue()


def _register_identity(username: str, email: str, password: str, *, base_url: str = USER_BASE_URL) -> Identity:
    session = ApiSession(base_url, HTTP_EXCHANGE_LOG)
    response = session.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "turnstile_token": "",
        },
        timeout=20,
    )
    assert_status(response, 201)
    body = response.json()
    # Reading commands bind their persisted account scope to the authenticated
    # cookie. Individual tests can override this to exercise the mismatch fence.
    session.headers.update({"X-MReader-Account-ID": body["id"]})
    return Identity(
        user_id=body["id"],
        username=body["username"],
        email=body["email"],
        password=password,
        session=session,
    )


@pytest.fixture(scope="session")
def regular_user(db):
    # Deterministic account for both automated and manual post-run testing.
    # Reset it before every suite so a previous diagnostic run cannot leak
    # profile/subscription/progress state into the next regression run.
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM users WHERE username = %s OR email = %s",
            (TEST_USER_USERNAME, TEST_USER_EMAIL),
        )
    identity = _register_identity(
        TEST_USER_USERNAME,
        TEST_USER_EMAIL,
        TEST_USER_PASSWORD,
    )
    yield identity
    # Deliberately keep the diagnostic user after the suite for manual browser
    # testing. The next test run resets it before registration.


@pytest.fixture(scope="session")
def admin_user(db):
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM users WHERE username = %s OR email = %s",
            (TEST_ADMIN_USERNAME, TEST_ADMIN_EMAIL),
        )
    identity = _register_identity(
        TEST_ADMIN_USERNAME,
        TEST_ADMIN_EMAIL,
        TEST_ADMIN_PASSWORD,
        base_url=ADMIN_BASE_URL,
    )

    with db.cursor() as cur:
        cur.execute(
            "UPDATE users SET role = 'admin', updated_at = NOW() WHERE id = %s::uuid",
            (identity.user_id,),
        )

    # Refresh the Valkey-backed session so the session JSON carries role=admin.
    identity.session.post("/api/auth/logout", timeout=10)
    login = identity.session.post(
        "/api/auth/login",
        json={
            "username_or_email": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
            "turnstile_token": "",
        },
        timeout=20,
    )
    assert_status(login, 200)
    assert login.json()["role"] == "admin"

    yield identity
    # Keep the diagnostics admin as well; it is reset on the next suite.


@pytest.fixture(scope="session")
def admin_regular_user(regular_user):
    """Regular-user session against the admin plane for RBAC tests."""
    session = ApiSession(ADMIN_BASE_URL, HTTP_EXCHANGE_LOG)
    login = session.post(
        "/api/auth/login",
        json={
            "username_or_email": regular_user.username,
            "password": regular_user.password,
            "turnstile_token": "",
        },
        timeout=20,
    )
    assert_status(login, 200)
    assert login.json()["role"] == "user"
    identity = Identity(
        user_id=regular_user.user_id,
        username=regular_user.username,
        email=regular_user.email,
        password=regular_user.password,
        session=session,
    )
    yield identity
    try:
        session.post("/api/auth/logout", timeout=5)
    except Exception:
        pass


@pytest.fixture
def temp_user_factory(db):
    created = []

    def factory(suffix: str | None = None) -> Identity:
        raw_suffix = suffix or uuid.uuid4().hex[:8]
        safe_suffix = re.sub(r"[^A-Za-z0-9_]", "_", raw_suffix).strip("_").lower()[:18] or "user"
        username = f"pt_{_ACCOUNT_RUN_TOKEN}_{safe_suffix}"[:50].rstrip("_")
        # Keep the local part comfortably below the RFC/validator 64-char limit.
        email = f"pt+{_ACCOUNT_RUN_TOKEN}.{safe_suffix}@{TEMP_EMAIL_DOMAIN}"
        password = "TestPassword123!"
        identity = _register_identity(username, email, password)
        created.append(identity)
        return identity

    yield factory

    for identity in created:
        try:
            identity.session.post("/api/auth/logout", timeout=5)
        except Exception:
            pass

    if created:
        ids = [identity.user_id for identity in created]
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM users WHERE id = ANY(%s::uuid[])",
                (ids,),
            )


@pytest.fixture(scope="session")
def seed_content(db, webp_bytes, admin_user):
    slug = f"{PREFIX}-series".replace("_", "-").lower()
    genre_name = f"Genre {RUN_ID}"
    tag_name = f"TAG_{RUN_ID}".upper()

    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO genres(name)
            VALUES (%s)
            ON CONFLICT(name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (genre_name,),
        )
        genre_id = cur.fetchone()[0]

    # Create the canonical series through Catalog rather than inserting it
    # behind Catalog's back. RC4.45 keeps taxonomy responses in a bounded cache;
    # direct DB fixture inserts therefore cannot be expected to invalidate the
    # running service. Using the real Admin API exercises and invalidates the
    # same cache path production writes use.
    created = admin_user.session.post(
        "/api/catalog/series",
        json={
            "title": f"Pytest Series {RUN_ID}",
            "slug": slug,
            "description": "Integration test series",
            "status": "ongoing",
            "genre_ids": [genre_id],
            "tag_names": [tag_name],
        },
        timeout=20,
    )
    assert_status(created, 201)
    series_id = created.json()["id"]

    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM tags WHERE upper(name)=upper(%s) LIMIT 1",
            (tag_name,),
        )
        tag_id = cur.fetchone()[0]

        chapter_ids = {}
        for number, chapter_slug in [(1, "ch-1"), (2, "ch-2")]:
            cur.execute(
                """
                INSERT INTO chapters(
                    series_id, chapter_number, title, slug, status, page_count
                )
                VALUES (%s::uuid, %s, %s, %s, 'published', 2)
                RETURNING id::text
                """,
                (
                    series_id,
                    number,
                    f"Chapter {number}",
                    chapter_slug,
                ),
            )
            chapter_id = cur.fetchone()[0]
            chapter_ids[chapter_slug] = chapter_id

            for page_number in (1, 2):
                path = f"{slug}/{chapter_slug}/{page_number:04d}.webp"
                response = requests.put(
                    f"{SEAWEEDFS_FILER_URL}/{path}",
                    data=webp_bytes,
                    headers={"Content-Type": "image/webp"},
                    timeout=20,
                )
                response.raise_for_status()

                cur.execute(
                    """
                    INSERT INTO pages(
                        chapter_id, page_number, image_path, width, height,
                        encoding_version, encoding_rows, encoding_columns, encoding_seed
                    )
                    VALUES (%s::uuid, %s, %s, 24, 32, 4, 1, 1, %s)
                    """,
                    (chapter_id, page_number, path, f"pytest-v4-{RUN_ID}-{chapter_slug}-{page_number:04d}"),
                )

    value = {
        "series_id": series_id,
        "series_slug": slug,
        "genre_id": genre_id,
        "tag_id": tag_id,
        "chapter_ids": chapter_ids,
        "chapter_slugs": ["ch-1", "ch-2"],
    }

    yield value

    try:
        requests.delete(
            f"{SEAWEEDFS_FILER_URL}/{slug}",
            params={"recursive": "true"},
            timeout=20,
        )
    except Exception:
        pass

    try:
        admin_user.session.delete(
            f"/api/catalog/series/{series_id}",
            timeout=20,
        )
    finally:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM genres WHERE id = %s AND NOT EXISTS "
                "(SELECT 1 FROM series_genres WHERE genre_id = %s)",
                (genre_id, genre_id),
            )
            cur.execute(
                "DELETE FROM tags WHERE id = %s AND NOT EXISTS "
                "(SELECT 1 FROM series_tags WHERE tag_id = %s)",
                (tag_id, tag_id),
            )


@pytest.fixture
def seeded_existing_draft(db, admin_user, seed_content):
    """Editable existing-series draft that avoids external scraper/network input.

    Manual page endpoints and existing-series publication can exercise the real
    staging/publish pipeline deterministically against the canonical pytest
    series without depending on a third-party source site.
    """
    draft_id = str(uuid.uuid4())
    chapter_slug = f"pytest-manual-{uuid.uuid4().hex[:8]}"
    chapter_number = 900000 + (int(uuid.uuid4().hex[:6], 16) % 90000)

    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scraper_drafts(
                id, draft_type, source_url, target_series_id,
                series_data, chapter_data, pages, status, created_by
            )
            VALUES(
                %s::uuid, 'existing_series_chapter',
                'https://example.invalid/pytest-existing-chapter', %s::uuid,
                '{}'::jsonb, %s::jsonb, '[]'::jsonb, 'draft', %s::uuid
            )
            """,
            (
                draft_id,
                seed_content["series_id"],
                json.dumps(
                    {
                        "chapter_url": "https://example.invalid/pytest-existing-chapter",
                        "chapter_number": str(chapter_number),
                        "chapter_slug": chapter_slug,
                        "chapter_title": "Pytest Manual Existing Draft",
                    }
                ),
                admin_user.user_id,
            ),
        )

    value = {
        "draft_id": draft_id,
        "chapter_slug": chapter_slug,
        "chapter_number": chapter_number,
        "series_id": seed_content["series_id"],
        "series_slug": seed_content["series_slug"],
    }

    yield value

    published_chapter_id = None
    with db.cursor() as cur:
        cur.execute(
            "SELECT published_chapter_id::text FROM scraper_drafts WHERE id=%s::uuid",
            (draft_id,),
        )
        row = cur.fetchone()
        if row:
            published_chapter_id = row[0]

    if published_chapter_id:
        try:
            admin_user.session.delete(
                f"/api/catalog/series/{seed_content['series_id']}/chapters/{published_chapter_id}",
                timeout=20,
            )
        except Exception:
            pass

    for remote_path in (
        f"_scraper/staging/{draft_id}",
        f"{seed_content['series_slug']}/{chapter_slug}",
    ):
        try:
            requests.delete(
                f"{SEAWEEDFS_FILER_URL}/{remote_path}",
                params={"recursive": "true"},
                timeout=10,
            )
        except Exception:
            pass

    with db.cursor() as cur:
        cur.execute("DELETE FROM event_outbox WHERE correlation_id=%s::uuid", (draft_id,))
        cur.execute("DELETE FROM scraper_drafts WHERE id=%s::uuid", (draft_id,))


@pytest.fixture
def notification_factory(db, regular_user, seed_content):
    created = []

    def factory(*, read: bool = False):
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notifications(
                    user_id, series_id, chapter_id, message, is_read
                )
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s)
                RETURNING id::text
                """,
                (
                    regular_user.user_id,
                    seed_content["series_id"],
                    seed_content["chapter_ids"]["ch-1"],
                    f"Pytest notification {uuid.uuid4().hex[:6]}",
                    read,
                ),
            )
            nid = cur.fetchone()[0]
            created.append(nid)
            return nid

    yield factory

    if created:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM notifications WHERE id = ANY(%s::uuid[])",
                (created,),
            )


@pytest.fixture
def seeded_series_draft(db, admin_user):
    draft_id = str(uuid.uuid4())
    chapter_id = str(uuid.uuid4())
    slug = f"{PREFIX}-new-series".replace("_", "-").lower()

    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scraper_series_drafts(
                id,
                source_url,
                adapter,
                title,
                slug,
                description,
                series_status,
                genres,
                tags,
                workflow_status,
                created_by
            )
            VALUES(
                %s::uuid,
                'https://example.invalid/pytest-series',
                'pytest-fixture',
                %s,
                %s,
                'Editable pytest draft',
                'ongoing',
                %s::jsonb,
                %s::jsonb,
                'draft',
                %s::uuid
            )
            """,
            (
                draft_id,
                f"Draft Series {RUN_ID}",
                slug,
                json.dumps([f"Draft Genre {RUN_ID}"]),
                json.dumps([f"DRAFT_{RUN_ID}".upper()]),
                admin_user.user_id,
            ),
        )

        cur.execute(
            """
            INSERT INTO scraper_series_draft_chapters(
                id,
                draft_id,
                chapter_number,
                chapter_slug,
                chapter_title,
                source_url,
                selected,
                stage_status,
                pages
            )
            VALUES(
                %s::uuid,
                %s::uuid,
                1,
                'ch-1',
                'Draft Chapter 1',
                'https://example.invalid/pytest-series/ch-1',
                TRUE,
                'ready',
                '[]'::jsonb
            )
            """,
            (chapter_id, draft_id),
        )

    value = {
        "draft_id": draft_id,
        "chapter_id": chapter_id,
        "slug": slug,
    }

    yield value

    try:
        requests.delete(
            f"{SEAWEEDFS_FILER_URL}/_scraper/series-drafts/{draft_id}",
            params={"recursive": "true"},
            timeout=10,
        )
        requests.delete(
            f"{SEAWEEDFS_FILER_URL}/{slug}",
            params={"recursive": "true"},
            timeout=10,
        )
    except Exception:
        pass

    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM event_outbox WHERE correlation_id = %s::uuid",
            (draft_id,),
        )
        cur.execute(
            "DELETE FROM series WHERE slug = %s",
            (slug,),
        )
        cur.execute(
            "DELETE FROM scraper_series_drafts WHERE id = %s::uuid",
            (draft_id,),
        )
