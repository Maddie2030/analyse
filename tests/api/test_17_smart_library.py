from helpers import assert_status
from reading_helpers import open_chapter, checkpoint_payload


def _library(session, **params):
    response = session.get('/api/social/library', params=params or None, timeout=15)
    assert_status(response, 200)
    return response.json()


def _series_item(payload, series_id):
    return next(item for item in payload['items'] if item['series_id'] == series_id)


def test_smart_library_requires_auth(anonymous):
    response = anonymous.get('/api/social/library', timeout=10)
    assert_status(response, 401)


def test_smart_library_monotonic_furthest_and_unread_state(
    db,
    temp_user_factory,
    seed_content,
):
    user = temp_user_factory('smart_library')
    series_id = seed_content['series_id']
    series_slug = seed_content['series_slug']

    saved = user.session.post(f'/api/social/bookmarks/{series_id}', timeout=10)
    assert_status(saved, 201)
    followed = user.session.post(f'/api/social/subscriptions/{series_id}', timeout=10)
    assert_status(followed, 201)

    initial = _library(user.session)
    item = _series_item(initial, series_id)
    assert item['bookmarked'] is True
    assert item['followed'] is True
    assert item['read_state'] == 'not_started'
    assert item['published_chapter_count'] == 2
    assert item['unread_chapter_count'] == 2
    assert item['first_chapter_number'] == 1
    assert item['latest_chapter_number'] == 2
    assert initial['summary']['not_started'] >= 1

    opened_latest = open_chapter(user.session, f'/api/progress/{series_slug}/ch-2', 0)
    read_latest = user.session.post(
        f'/api/progress/{series_slug}/ch-2/commit',
        json=checkpoint_payload(opened_latest, 2, 1.0, completed_page=2),
        timeout=15,
    )
    assert_status(read_latest, 200)

    caught_up = _library(user.session)
    assert caught_up['summary']['history'] >= 1
    item = _series_item(caught_up, series_id)
    assert item['read_state'] == 'caught_up'
    assert item['resume_chapter_number'] == 2
    assert item['furthest_chapter_number'] == 2
    assert item['unread_chapter_count'] == 0

    # Rereading an older chapter changes resume recency but must not move the
    # monotonic furthest marker backwards or manufacture fake unread chapters.
    opened_old = open_chapter(user.session, f'/api/progress/{series_slug}/ch-1', read_latest.json()['revision'])
    reread_old = user.session.post(
        f'/api/progress/{series_slug}/ch-1/commit',
        json=checkpoint_payload(opened_old, 1, 0.5),
        timeout=15,
    )
    assert_status(reread_old, 200)

    reread_state = _library(user.session)
    item = _series_item(reread_state, series_id)
    assert item['resume_chapter_number'] == 1
    assert item['furthest_chapter_number'] == 2
    assert item['read_state'] == 'caught_up'
    assert item['unread_chapter_count'] == 0

    with db.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO chapters(
                series_id, chapter_number, title, slug, status, page_count
            )
            VALUES (%s::uuid, 3, 'Chapter 3', 'ch-3', 'published', 0)
            RETURNING id::text
            ''',
            (series_id,),
        )
        chapter3_id = cur.fetchone()[0]

    updates = _library(user.session)
    item = _series_item(updates, series_id)
    assert item['read_state'] == 'updates'
    assert item['unread_chapter_count'] == 1
    assert item['latest_chapter_number'] == 3
    assert item['next_chapter_number'] == 3
    assert item['next_chapter_slug'] == 'ch-3'
    assert item['resume_chapter_number'] == 1
    assert item['furthest_chapter_number'] == 2

    updates_only = _library(user.session, state='updates')
    assert updates_only['total'] >= 1
    assert any(row['series_id'] == series_id for row in updates_only['items'])

    caught_up_only = _library(user.session, state='caught_up')
    assert not any(row['series_id'] == series_id for row in caught_up_only['items'])

    followed_only = _library(user.session, scope='following', sort='unread')
    assert any(row['series_id'] == series_id for row in followed_only['items'])

    history_only = _library(user.session, scope='history', sort='updated')
    assert any(row['series_id'] == series_id for row in history_only['items'])

    with db.cursor() as cur:
        cur.execute(
            '''
            SELECT rh.resume_chapter_id::text, rh.furthest_chapter_id::text
            FROM reading_state_v1 rh
            WHERE rh.user_id = %s::uuid AND rh.series_id = %s::uuid
            ''',
            (user.user_id, series_id),
        )
        resume_id, furthest_id = cur.fetchone()
    assert resume_id == seed_content['chapter_ids']['ch-1']
    assert furthest_id == seed_content['chapter_ids']['ch-2']

    with db.cursor() as cur:
        cur.execute('DELETE FROM chapters WHERE id = %s::uuid', (chapter3_id,))


def test_smart_library_rejects_invalid_filters(temp_user_factory):
    user = temp_user_factory('smart_library_invalid')
    for key, value in (
        ('scope', 'everything'),
        ('state', 'finished'),
        ('sort', 'random'),
    ):
        response = user.session.get('/api/social/library', params={key: value}, timeout=10)
        assert_status(response, 400)


def test_smart_library_does_not_fabricate_history_from_a_checkpoint_only(
    db,
    temp_user_factory,
    seed_content,
):
    user = temp_user_factory('smart_library_history_fallback')
    series_id = seed_content['series_id']
    chapter_id = seed_content['chapter_ids']['ch-1']

    # A deliberately incomplete row must not manufacture exact reading evidence.
    # An accepted open repairs it through the single command owner.
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM chapter_reads WHERE user_id=%s::uuid AND series_id=%s::uuid",
            (user.user_id, series_id),
        )
        cur.execute(
            """
            INSERT INTO reading_progress(
                user_id, series_id, chapter_id, last_page, scroll_position, updated_at
            ) VALUES (%s::uuid, %s::uuid, %s::uuid, 1, 0.25, NOW())
            ON CONFLICT (user_id, series_id) DO UPDATE SET
                chapter_id=EXCLUDED.chapter_id,
                last_page=EXCLUDED.last_page,
                scroll_position=EXCLUDED.scroll_position,
                updated_at=EXCLUDED.updated_at
            """,
            (user.user_id, series_id, chapter_id),
        )

    payload = _library(user.session, scope='history')
    assert payload['summary']['history'] == 0
    assert payload['items'] == []
    open_chapter(user.session, f"/api/progress/{seed_content['series_slug']}/ch-1")
    payload = _library(user.session, scope='history')
    assert payload['summary']['history'] == 1
    assert payload['total'] == 1
    item = _series_item(payload, series_id)
    assert item['has_history'] is True
    assert item['resume_chapter_number'] == 1
