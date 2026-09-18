from __future__ import annotations

import io
import os
import sys

import psycopg
import requests
from PIL import Image

USER_BASE = os.getenv("TEST_USER_BASE_URL", "http://host.docker.internal:8080").rstrip("/")
DB_URL = (os.getenv("TEST_DATABASE_URL") or os.getenv("KEDA_POSTGRES_URL") or os.getenv("DATABASE_URL") or "").replace("postgresql+asyncpg://", "postgresql://", 1)
FILER = os.getenv("TEST_SEAWEEDFS_FILER_URL") or os.getenv("SEAWEEDFS_FILER_URL", "")
SLUG = os.getenv("K6_TEST_SERIES_SLUG", "mreader-k6-load-series")
USERNAME = os.getenv("K6_TEST_USERNAME", "mreader_k6_user")
EMAIL = os.getenv("K6_TEST_EMAIL", "mreader.k6.user@gmail.com")
PASSWORD = os.getenv("K6_TEST_PASSWORD", "MReaderK6Test123!")
ADMIN_USERNAME = os.getenv("K6_TEST_ADMIN_USERNAME", "mreader_k6_admin")
ADMIN_EMAIL = os.getenv("K6_TEST_ADMIN_EMAIL", "mreader.k6.admin@gmail.com")
ADMIN_PASSWORD = os.getenv("K6_TEST_ADMIN_PASSWORD", "MReaderK6Admin123!")
LOGIN_USERNAME = os.getenv("K6_TEST_LOGIN_USERNAME", "mreader_k6_login_user")
LOGIN_EMAIL = os.getenv("K6_TEST_LOGIN_EMAIL", "mreader.k6.login.user@gmail.com")
LOGIN_PASSWORD = os.getenv("K6_TEST_LOGIN_PASSWORD", "MReaderK6Login123!")


def image_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 120), (180, 180, 180)).save(buf, format="WEBP", quality=78)
    return buf.getvalue()



def ensure_user(conn, username: str, email: str, password: str, *, role: str = "user"):
    with conn.cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE username=%s OR email=%s LIMIT 1", (username, email))
        existing = cur.fetchone()
    if not existing:
        r = requests.post(
            f"{USER_BASE}/api/auth/register",
            json={"username": username, "email": email, "password": password, "turnstile_token": ""},
            timeout=20,
        )
        if r.status_code != 201:
            raise RuntimeError(f"test-user registration failed for {username}: {r.status_code} {r.text[:500]}")
        user_id = r.json()["id"]
    else:
        user_id = existing[0]
        r = requests.post(
            f"{USER_BASE}/api/auth/login",
            json={"username_or_email": username, "password": password, "turnstile_token": ""},
            timeout=20,
        )
        if r.status_code != 200:
            raise RuntimeError(f"reserved k6 test user {username} exists but does not accept the harness password")
    if role != "user":
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role=%s, updated_at=NOW() WHERE id=%s::uuid", (role, user_id))
    return user_id

def cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id::text FROM series WHERE slug=%s", (SLUG,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM series WHERE id=%s::uuid", (row[0],))
        # The auth-login breakpoint identity is unique per capacity run so an
        # intentional 429/rate-limit breakpoint cannot poison the next run.
        cur.execute(
            "DELETE FROM users WHERE username=%s OR email=%s",
            (LOGIN_USERNAME, LOGIN_EMAIL),
        )
    if FILER:
        try:
            requests.delete(f"{FILER.rstrip('/')}/{SLUG}", params={"recursive": "true"}, timeout=20)
        except Exception:
            pass


def create(conn):
    cleanup(conn)
    ensure_user(conn, USERNAME, EMAIL, PASSWORD, role="user")
    ensure_user(conn, LOGIN_USERNAME, LOGIN_EMAIL, LOGIN_PASSWORD, role="user")
    ensure_user(conn, ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD, role="admin")

    img = image_bytes()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO series(title, slug, description, status)
            VALUES (%s,%s,%s,'ongoing') RETURNING id::text
            """,
            ("MReader k6 Load Test Series", SLUG, "Owned by the automated k6 harness"),
        )
        series_id = cur.fetchone()[0]
        for chapter_num in range(1, 5):
            chapter_slug = f"ch-{chapter_num}"
            cur.execute(
                """
                INSERT INTO chapters(series_id,chapter_number,title,slug,status,page_count)
                VALUES (%s::uuid,%s,%s,%s,'published',4) RETURNING id::text
                """,
                (series_id, chapter_num, f"Chapter {chapter_num}", chapter_slug),
            )
            chapter_id = cur.fetchone()[0]
            for page in range(1, 5):
                path = f"{SLUG}/{chapter_slug}/{page:04d}.webp"
                rr = requests.put(
                    f"{FILER.rstrip('/')}/{path}", data=img,
                    headers={"Content-Type": "image/webp"}, timeout=20,
                )
                rr.raise_for_status()
                cur.execute(
                    """
                    INSERT INTO pages(
                        chapter_id,page_number,image_path,width,height,
                        encoding_version,encoding_rows,encoding_columns,encoding_seed
                    )
                    VALUES (%s::uuid,%s,%s,80,120,4,1,1,%s)
                    """,
                    (chapter_id, page, path, f"k6-v4-{SLUG}-{chapter_slug}-{page:04d}"),
                )
    print(f"K6_TEST_SERIES_SLUG={SLUG}")
    print(f"K6_TEST_USERNAME={USERNAME}")
    print(f"K6_TEST_LOGIN_USERNAME={LOGIN_USERNAME}")
    print(f"K6_TEST_ADMIN_USERNAME={ADMIN_USERNAME}")


def main():
    if not DB_URL:
        raise SystemExit("TEST_DATABASE_URL/KEDA_POSTGRES_URL/DATABASE_URL is required")
    if not FILER:
        raise SystemExit("TEST_SEAWEEDFS_FILER_URL/SEAWEEDFS_FILER_URL is required")
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        if action == "create":
            create(conn)
        elif action == "cleanup":
            cleanup(conn)
            print("k6 test data cleaned")
        else:
            raise SystemExit(f"unknown action: {action}")


if __name__ == "__main__":
    main()
