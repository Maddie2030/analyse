"""Progress command ordering and the common Library read projection.

Run against disposable PostgreSQL and the actual services. In particular, these
tests must fail if delayed commands can steal resume or if retries create new
recency/outbox events; a source-string check is not a substitute.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from psycopg import sql

from helpers import ApiSession, assert_status


def opened(user, seed, chapter, revision, command_id=None):
    body = {"command_id": command_id or str(uuid4()), "expected_revision": revision}
    response = user.session.post(
        f"/api/progress/{seed['series_slug']}/{chapter}/open",
        json=body,
        headers={"X-MReader-Account-ID": user.user_id},
        timeout=15,
    )
    assert_status(response, 200)
    return response.json(), body


def committed(user, seed, chapter, generation, sequence, **changes):
    body = {
        "command_id": str(uuid4()),
        "session_generation": generation,
        "command_sequence": sequence,
        "last_page": 1,
        "scroll_position": 0.25,
        "completed": False,
        "completed_page": 0,
    }
    body.update(changes)
    response = user.session.post(
        f"/api/progress/{seed['series_slug']}/{chapter}/commit",
        json=body,
        headers={"X-MReader-Account-ID": user.user_id},
        timeout=15,
    )
    assert_status(response, 200)
    return response.json(), body


def test_open_retry_does_not_reset_checkpoint_or_create_recency(temp_user_factory, seed_content, db):
    user = temp_user_factory("open_retry")
    first, body = opened(user, seed_content, "ch-1", 0)
    assert first["accepted"] and first["revision"] == 1
    saved, _ = committed(
        user, seed_content, "ch-1", first["session_generation"], 1,
        last_page=2, scroll_position=0.75,
    )
    retry, _ = opened(user, seed_content, "ch-1", 0, body["command_id"])
    assert retry["accepted"] and retry["duplicate"]
    assert retry["revision"] == saved["revision"]
    assert retry["last_page"] == 2
    assert retry["scroll_position"] == 0.75
    assert retry["last_opened_at"] == first["last_opened_at"]


def test_reopening_earlier_chapter_changes_resume_not_furthest(temp_user_factory, seed_content):
    user = temp_user_factory("reopen_earlier")
    first, _ = opened(user, seed_content, "ch-2", 0)
    saved, _ = committed(user, seed_content, "ch-2", first["session_generation"], 1)
    earlier, _ = opened(user, seed_content, "ch-1", saved["revision"])
    assert earlier["accepted"]
    assert earlier["chapter_id"] == seed_content["chapter_ids"]["ch-1"]
    assert earlier["last_page"] == 1 and earlier["scroll_position"] == 0
    response = user.session.get(
        f"/api/progress/series/{seed_content['series_slug']}/state", timeout=15
    )
    assert_status(response, 200)
    state = response.json()
    assert state["resume_chapter_id"] == seed_content["chapter_ids"]["ch-1"]
    assert state["furthest_chapter_id"] == seed_content["chapter_ids"]["ch-2"]
    assert state["revision"] == earlier["revision"]


def test_old_device_cannot_steal_resume_but_exact_completion_survives(temp_user_factory, seed_content):
    user = temp_user_factory("old_session")
    old, _ = opened(user, seed_content, "ch-1", 0)
    current, _ = opened(user, seed_content, "ch-2", old["revision"])
    stale, _ = committed(
        user, seed_content, "ch-1", old["session_generation"], 1,
        last_page=1, completed=True, completed_page=2,
    )
    assert stale["accepted"] is False and stale["code"] == "stale_session"
    assert stale["chapter_id"] == current["chapter_id"]
    assert stale["last_opened_at"] == current["last_opened_at"]
    state = user.session.get(
        f"/api/progress/series/{seed_content['series_slug']}/state", timeout=15
    ).json()
    assert seed_content["chapter_ids"]["ch-1"] in state["completed_chapter_ids"]
    history = user.session.get("/api/progress/history", timeout=15).json()
    assert history[0]["chapter_id"] == current["chapter_id"]
    library_response = user.session.get("/api/social/library?scope=history", timeout=15)
    assert_status(library_response, 200)
    library = library_response.json()
    assert library["contract_version"] == 1
    assert library["summary"]["history"] == library["recently_opened"]["total"] == 1
    for item in (library["items"][0], library["recently_opened"]["items"][0]):
        assert item["resume_chapter_id"] == current["chapter_id"]
        assert item["reading_revision"] == stale["revision"]


def test_duplicate_commit_is_noop_and_changed_body_conflicts(temp_user_factory, seed_content, db):
    user = temp_user_factory("commit_retry")
    first, _ = opened(user, seed_content, "ch-1", 0)
    saved, body = committed(user, seed_content, "ch-1", first["session_generation"], 1)
    retry, _ = committed(user, seed_content, "ch-1", first["session_generation"], 1, **{
        k: v for k, v in body.items() if k not in ("session_generation", "command_sequence")
    })
    assert retry["accepted"] and retry["duplicate"]
    assert retry["revision"] == saved["revision"]
    assert retry["updated_at"] == saved["updated_at"]
    changed, _ = committed(
        user, seed_content, "ch-1", first["session_generation"], 1,
        command_id=body["command_id"], last_page=2,
    )
    assert not changed["accepted"] and changed["code"] == "command_conflict"
    assert changed["revision"] == saved["revision"]
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM event_outbox WHERE event_type='progress.updated' AND aggregate_id=%s",
            (f"{user.user_id}:{seed_content['series_id']}",),
        )
        assert cur.fetchone() == (2,)


def test_clamped_checkpoint_hashes_the_submitted_body(temp_user_factory, seed_content):
    user = temp_user_factory("clamped_command_hash")
    opened_state, _ = opened(user, seed_content, "ch-1", 0)
    accepted, body = committed(
        user,
        seed_content,
        "ch-1",
        opened_state["session_generation"],
        1,
        last_page=999,
    )
    assert accepted["accepted"] and accepted["last_page"] == 2

    exact_retry, _ = committed(
        user,
        seed_content,
        "ch-1",
        opened_state["session_generation"],
        1,
        **{
            key: value
            for key, value in body.items()
            if key not in ("session_generation", "command_sequence")
        },
    )
    assert exact_retry["accepted"] and exact_retry["duplicate"]

    changed_body, _ = committed(
        user,
        seed_content,
        "ch-1",
        opened_state["session_generation"],
        1,
        command_id=body["command_id"],
        last_page=2,
    )
    assert not changed_body["accepted"]
    assert changed_body["code"] == "command_conflict"
    assert changed_body["revision"] == accepted["revision"]


def test_checkpoint_pages_reject_values_above_javascript_safe_integer(
    temp_user_factory, seed_content
):
    user = temp_user_factory("safe_page_bounds")
    opened_state, _ = opened(user, seed_content, "ch-1", 0)
    body = {
        "command_id": str(uuid4()),
        "session_generation": opened_state["session_generation"],
        "command_sequence": 1,
        "last_page": 9007199254740992,
        "scroll_position": 0.25,
        "completed": False,
        "completed_page": 0,
    }
    response = user.session.post(
        f"/api/progress/{seed_content['series_slug']}/ch-1/commit",
        json=body,
        headers={"X-MReader-Account-ID": user.user_id},
        timeout=15,
    )
    assert_status(response, 422)


def test_retained_identity_duplicates_and_historical_retries_are_fenced(
    temp_user_factory, seed_content
):
    user = temp_user_factory("retained_identity")
    first, _ = opened(user, seed_content, "ch-1", 0)
    saved_one, body_one = committed(
        user, seed_content, "ch-1", first["session_generation"], 1
    )
    saved_two, body_two = committed(
        user,
        seed_content,
        "ch-1",
        first["session_generation"],
        2,
        last_page=2,
    )

    latest_retry, _ = committed(
        user,
        seed_content,
        "ch-1",
        first["session_generation"],
        2,
        **{
            key: value
            for key, value in body_two.items()
            if key not in ("session_generation", "command_sequence")
        },
    )
    assert latest_retry["accepted"] and latest_retry["duplicate"]
    assert latest_retry["revision"] == saved_two["revision"]

    historical_retry, _ = committed(
        user,
        seed_content,
        "ch-1",
        first["session_generation"],
        1,
        **{
            key: value
            for key, value in body_one.items()
            if key not in ("session_generation", "command_sequence")
        },
    )
    assert not historical_retry["accepted"]
    assert historical_retry["code"] == "stale_sequence"
    assert historical_retry["revision"] == saved_two["revision"]

    # Historical command IDs are not retained permanently. A client is required
    # to allocate a fresh UUID; reusing a superseded ID with a new sequence is
    # outside the server's bounded historical-uniqueness guarantee.
    reused_superseded_id, _ = committed(
        user,
        seed_content,
        "ch-1",
        first["session_generation"],
        3,
        command_id=body_one["command_id"],
        last_page=1,
    )
    assert reused_superseded_id["accepted"]
    assert reused_superseded_id["revision"] == saved_two["revision"] + 1


def test_account_header_mismatch_cannot_mutate_either_account(
    temp_user_factory, seed_content, db
):
    queued_account = temp_user_factory("queued_account")
    cookie_account = temp_user_factory("cookie_account")
    aggregate_ids = (queued_account.user_id, cookie_account.user_id)

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT user_id::text, count(*)
            FROM reading_progress
            WHERE user_id = ANY(%s::uuid[]) AND series_id=%s::uuid
            GROUP BY user_id
            ORDER BY user_id
            """,
            (list(aggregate_ids), seed_content["series_id"]),
        )
        before_progress = cur.fetchall()
        cur.execute(
            """
            SELECT user_id::text, count(*)
            FROM chapter_reads
            WHERE user_id = ANY(%s::uuid[]) AND series_id=%s::uuid
            GROUP BY user_id
            ORDER BY user_id
            """,
            (list(aggregate_ids), seed_content["series_id"]),
        )
        before_reads = cur.fetchall()

    path = f"/api/progress/{seed_content['series_slug']}/ch-1"
    direct_read = cookie_account.session.get(
        path, headers={"X-MReader-Account-ID": ""}, timeout=15
    )
    assert_status(direct_read, 200)
    mismatched_read = cookie_account.session.get(
        path,
        headers={"X-MReader-Account-ID": queued_account.user_id},
        timeout=15,
    )
    assert_status(mismatched_read, 403)
    assert mismatched_read.json()["code"] == "account_mismatch"

    open_response = cookie_account.session.post(
        f"{path}/open",
        json={"command_id": str(uuid4()), "expected_revision": 0},
        headers={"X-MReader-Account-ID": queued_account.user_id},
        timeout=15,
    )
    assert_status(open_response, 403)
    assert open_response.json()["code"] == "account_mismatch"
    commit_response = cookie_account.session.post(
        f"{path}/commit",
        json={
            "command_id": str(uuid4()),
            "session_generation": 1,
            "command_sequence": 1,
            "last_page": 1,
            "scroll_position": 0.25,
            "completed": False,
            "completed_page": 0,
        },
        headers={"X-MReader-Account-ID": queued_account.user_id},
        timeout=15,
    )
    assert_status(commit_response, 403)
    assert commit_response.json()["code"] == "account_mismatch"

    with db.cursor() as cur:
        cur.execute(
            """
            SELECT user_id::text, count(*)
            FROM reading_progress
            WHERE user_id = ANY(%s::uuid[]) AND series_id=%s::uuid
            GROUP BY user_id
            ORDER BY user_id
            """,
            (list(aggregate_ids), seed_content["series_id"]),
        )
        assert cur.fetchall() == before_progress
        cur.execute(
            """
            SELECT user_id::text, count(*)
            FROM chapter_reads
            WHERE user_id = ANY(%s::uuid[]) AND series_id=%s::uuid
            GROUP BY user_id
            ORDER BY user_id
            """,
            (list(aggregate_ids), seed_content["series_id"]),
        )
        assert cur.fetchall() == before_reads


def test_migration_checkpoint_survives_away_and_back_opens(
    temp_user_factory, seed_content, db
):
    ledger_only = temp_user_factory("migration_ledger_only")
    newer_ledger = temp_user_factory("migration_newer_ledger")
    series_id = seed_content["series_id"]
    chapter_one = seed_content["chapter_ids"]["ch-1"]
    chapter_two = seed_content["chapter_ids"]["ch-2"]
    relative = Path("db/migrations/051_progress_revision_ordering.sql")
    roots = [Path(__file__).resolve().parent.parent.parent, Path("/repo")]
    migration_path = next((root / relative for root in roots if (root / relative).is_file()), None)
    assert migration_path is not None, "Migration source is required by this real PostgreSQL test"
    migration = migration_path.read_text(encoding="utf-8")
    schema = "reading_migration_" + uuid4().hex

    # Run the actual migration against its old schema, isolated from the running
    # services. A failure rolls back all fixture DDL and test-account data.
    with db.transaction():
        with db.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute("SELECT set_config('search_path', %s, true)", (schema + ",public",))
            cur.execute("""
                CREATE TABLE chapters (
                    id UUID PRIMARY KEY, series_id UUID NOT NULL,
                    page_count INTEGER, chapter_number NUMERIC NOT NULL
                );
                CREATE TABLE reading_progress (
                    user_id UUID NOT NULL, series_id UUID NOT NULL,
                    chapter_id UUID REFERENCES chapters(id) ON DELETE CASCADE,
                    last_page INTEGER NOT NULL DEFAULT 1,
                    scroll_position DOUBLE PRECISION NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, series_id)
                );
                CREATE TABLE chapter_reads (
                    user_id UUID NOT NULL, series_id UUID NOT NULL, chapter_id UUID NOT NULL,
                    first_read_at TIMESTAMPTZ NOT NULL, last_read_at TIMESTAMPTZ NOT NULL,
                    last_page INTEGER NOT NULL DEFAULT 1,
                    completed BOOLEAN NOT NULL DEFAULT FALSE, completed_at TIMESTAMPTZ,
                    PRIMARY KEY (user_id, chapter_id)
                )
            """)
            cur.execute("""
                INSERT INTO chapters(id,series_id,page_count,chapter_number)
                SELECT id,series_id,page_count,chapter_number FROM public.chapters
                WHERE id=ANY(%s::uuid[])
            """, ([chapter_one, chapter_two],))
            cur.execute("""
                INSERT INTO chapter_reads(user_id,series_id,chapter_id,first_read_at,last_read_at,last_page)
                VALUES (%s,%s,%s,NOW()-INTERVAL '1 hour',NOW()-INTERVAL '1 hour',2),
                       (%s,%s,%s,NOW()-INTERVAL '1 hour',NOW()-INTERVAL '1 hour',2)
            """, (ledger_only.user_id, series_id, chapter_one,
                  newer_ledger.user_id, series_id, chapter_two))
            cur.execute("""
                INSERT INTO reading_progress(user_id,series_id,chapter_id,last_page,scroll_position,updated_at)
                VALUES (%s,%s,%s,1,0.125,NOW()-INTERVAL '2 hours')
            """, (newer_ledger.user_id, series_id, chapter_one))
            cur.execute(migration)
            cur.execute("SELECT user_id::text,chapter_id::text,last_page FROM reading_progress")
            assert {row[0]: row[1:] for row in cur.fetchall()} == {
                ledger_only.user_id: (chapter_one, 2), newer_ledger.user_id: (chapter_two, 2),
            }
            cur.execute("""
                SELECT cr.user_id::text,cr.chapter_id::text,cr.resume_page,cr.resume_scroll_position
                FROM chapter_reads cr JOIN reading_progress rp
                ON (rp.user_id,rp.series_id,rp.chapter_id)=(cr.user_id,cr.series_id,cr.chapter_id)
            """)
            assert {row[0]: row[1:] for row in cur.fetchall()} == {
                ledger_only.user_id: (chapter_one, 2, 0.0), newer_ledger.user_id: (chapter_two, 2, 0.0),
            }
            # Feed only these two temporary users' migrated rows to the actual
            # Progress API, so away/back opens exercise production command code.
            cur.execute("""
                INSERT INTO public.reading_progress
                    (user_id,series_id,chapter_id,last_page,scroll_position,updated_at,revision,last_opened_at,session_generation,command_sequence)
                SELECT user_id,series_id,chapter_id,last_page,scroll_position,updated_at,revision,last_opened_at,session_generation,command_sequence
                FROM reading_progress;
                INSERT INTO public.chapter_reads
                    (user_id,series_id,chapter_id,first_read_at,last_read_at,last_page,completed,completed_at,resume_page,resume_scroll_position,provenance)
                SELECT user_id,series_id,chapter_id,first_read_at,last_read_at,last_page,completed,completed_at,resume_page,resume_scroll_position,provenance
                FROM chapter_reads
            """)
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

    away, _ = opened(ledger_only, seed_content, "ch-2", 1)
    back, _ = opened(ledger_only, seed_content, "ch-1", away["revision"])
    assert back["accepted"] and back["last_page"] == 2
    assert back["scroll_position"] == 0.0
    away, _ = opened(newer_ledger, seed_content, "ch-1", 1)
    assert away["last_page"] == 1 and away["scroll_position"] == 0.125
    back, _ = opened(newer_ledger, seed_content, "ch-2", away["revision"])
    assert back["accepted"] and back["last_page"] == 2
    assert back["scroll_position"] == 0.0


def test_reordered_sequence_and_concurrent_open_are_rejected(temp_user_factory, seed_content):
    user = temp_user_factory("reading_reorder")
    first, _ = opened(user, seed_content, "ch-1", 0)
    saved, _ = committed(user, seed_content, "ch-1", first["session_generation"], 2, last_page=2)
    stale, _ = committed(user, seed_content, "ch-1", first["session_generation"], 1)
    assert not stale["accepted"] and stale["code"] == "stale_sequence"
    assert stale["last_page"] == 2 and stale["revision"] == saved["revision"]
    conflicting_open, _ = opened(user, seed_content, "ch-2", first["revision"])
    assert not conflicting_open["accepted"] and conflicting_open["code"] == "revision_conflict"
    assert conflicting_open["chapter_id"] == first["chapter_id"]


def test_two_initial_opens_have_one_winner(temp_user_factory, seed_content):
    user = temp_user_factory("concurrent_open")
    def open_from_device(chapter):
        # Each device owns its own client session; only authenticated identity is shared.
        with ApiSession(user.session.base_url, user.session.exchange_log) as session:
            session.cookies.update(user.session.cookies)
            return opened(replace(user, session=session), seed_content, chapter, 0)[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(open_from_device, ("ch-1", "ch-2")))
    accepted = [result for result in results if result["accepted"]]
    rejected = [result for result in results if not result["accepted"]]
    assert len(accepted) == len(rejected) == 1
    assert rejected[0]["code"] == "revision_conflict"
    assert accepted[0]["revision"] == rejected[0]["revision"] == 1
    assert accepted[0]["chapter_id"] == rejected[0]["chapter_id"]


def test_completion_stays_true_when_checkpoint_moves_back(temp_user_factory, seed_content):
    user = temp_user_factory("reread_completion")
    first, _ = opened(user, seed_content, "ch-1", 0)
    completed, _ = committed(
        user, seed_content, "ch-1", first["session_generation"], 1,
        last_page=1, completed=True, completed_page=2,
    )
    assert completed["accepted"] and completed["last_page"] == 1
    reread, _ = committed(user, seed_content, "ch-1", first["session_generation"], 2)
    assert reread["accepted"]
    state = user.session.get(
        f"/api/progress/series/{seed_content['series_slug']}/state", timeout=15
    ).json()
    assert seed_content["chapter_ids"]["ch-1"] in state["completed_chapter_ids"]


def test_inferred_reach_becomes_observed_only_on_real_open(temp_user_factory, seed_content, db):
    user = temp_user_factory("inferred_reach")
    chapter = seed_content["chapter_ids"]["ch-2"]
    with db.cursor() as cur:
        # Deliberately future-dated observation evidence cannot become an actual
        # first/last read timestamp when the user opens this chapter now.
        cur.execute("""
            INSERT INTO chapter_reads(user_id,series_id,chapter_id,first_read_at,last_read_at,provenance)
            VALUES(%s,%s,%s,NOW()+INTERVAL '1 day',NOW()+INTERVAL '1 day','migrated_reach');
        """, (user.user_id, seed_content["series_id"], chapter))
        cur.execute("""
            INSERT INTO reading_progress(user_id,series_id,chapter_id,last_page,scroll_position)
            VALUES(%s,%s,NULL,1,0)
        """, (user.user_id, seed_content["series_id"]))
    state_url = f"/api/progress/series/{seed_content['series_slug']}/state"
    state = user.session.get(state_url, timeout=15).json()
    assert state["furthest_chapter_id"] == chapter
    assert chapter not in state["read_chapter_ids"]
    assert chapter not in state["completed_chapter_ids"]
    library = user.session.get("/api/social/library?scope=history", timeout=15).json()
    assert library["summary"]["history"] == library["recently_opened"]["total"] == 0
    accepted, _ = opened(user, seed_content, "ch-2", 1)
    assert accepted["accepted"] and accepted["last_page"] == 1
    with db.cursor() as cur:
        cur.execute("""
            SELECT first_read_at,last_read_at,provenance,completed
            FROM chapter_reads WHERE user_id=%s AND chapter_id=%s
        """, (user.user_id, chapter))
        first, last, provenance, completed = cur.fetchone()
    actual_open = datetime.fromisoformat(accepted["last_opened_at"].replace("Z", "+00:00"))
    assert first == last == actual_open
    assert provenance == "observed" and completed is False
    state = user.session.get(state_url, timeout=15).json()
    assert chapter in state["read_chapter_ids"]
    assert chapter not in state["completed_chapter_ids"]
