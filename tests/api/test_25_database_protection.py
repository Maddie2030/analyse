import uuid

import pytest

from helpers import assert_status


OPAQUE_BACKUP = 'bkp_' + ('0' * 24)
FORBIDDEN_STORAGE_KEYS = {
    'logical_filer_root', 'filer_url', 'expected_physical_root', 'proof',
    'physical_volume_root', 'mount_source', 'mountpoint', 'filesystem',
    'runtime_filer_url', 'configured_filer_url', 'proof_url',
}


def test_database_protection_status_is_admin_only_and_browser_safe(admin_anonymous, admin_regular_user, admin_user):
    assert_status(admin_anonymous.get('/api/admin/database', timeout=10), 401)
    assert_status(admin_regular_user.session.get('/api/admin/database', timeout=10), 403)
    response = admin_user.session.get('/api/admin/database', timeout=15)
    assert_status(response, 200)
    body = response.json()
    assert set(('storage', 'runtime', 'policy', 'operations', 'backups')).issubset(body)
    assert not (FORBIDDEN_STORAGE_KEYS & set(body['storage']))
    assert isinstance(body['storage']['healthy'], bool)
    assert isinstance(body['storage']['local_storage_ready'], bool)
    assert isinstance(body['storage']['backup_count'], int)
    runtime = body['runtime']
    assert set(('available', 'status', 'last_heartbeat_at', 'capabilities', 'message')).issubset(runtime)
    assert runtime['status'] in {'ready', 'degraded', 'offline'}
    assert isinstance(runtime['available'], bool)
    assert set(runtime['capabilities']) == {'local_storage_ready', 'logical_backup', 'physical_snapshot', 'restore_drill', 'restore'}
    assert all(isinstance(value, bool) for value in runtime['capabilities'].values())
    assert not (FORBIDDEN_STORAGE_KEYS & set(runtime))
    assert body['policy']['automatic_window_start']
    assert body['policy']['automatic_window_end']
    for item in body['backups']:
        assert item['id'].startswith('bkp_')
        assert 'filename' not in item
        assert 'category' not in item
        assert 'remote_url' not in item
    for operation in body['operations']:
        assert 'backup_filename' not in operation
        assert 'category' not in operation
        assert 'metadata' not in operation
        assert 'result' not in operation
        assert 'error' not in operation


def test_database_backup_queue_is_admin_only_without_starting_backup(admin_regular_user):
    assert_status(admin_regular_user.session.post('/api/admin/database/backups', timeout=10), 403)
    assert_status(admin_regular_user.session.post('/api/admin/database/snapshots', timeout=10), 403)


def test_database_restore_drill_uses_opaque_identifier_and_is_admin_only(admin_regular_user, admin_user):
    assert_status(
        admin_regular_user.session.post(
            '/api/admin/database/restore-drills',
            json={'backup_id': OPAQUE_BACKUP},
            timeout=10,
        ),
        403,
    )
    invalid = admin_user.session.post(
        '/api/admin/database/restore-drills',
        json={'backup_id': '../../backups/mreader/postgres/daily/example.dump'},
        timeout=10,
    )
    assert_status(invalid, 400)


def test_database_restore_requires_exact_opaque_typed_confirmation(admin_user):
    status = admin_user.session.get('/api/admin/database', timeout=15)
    assert_status(status, 200)
    backups = status.json().get('backups') or []
    if not backups:
        pytest.skip('No verified recovery point is available for confirmation validation')
    backup_id = backups[0]['id']
    response = admin_user.session.post(
        '/api/admin/database/restores',
        json={'backup_id': backup_id, 'confirmation': 'RESTORE wrong-id'},
        timeout=10,
    )
    assert_status(response, 400)
    # Do not expose the internal filename/path in the validation error.
    text = str(response.json())
    assert '/backups/' not in text
    assert '/srv/' not in text
    assert '.dump' not in text and '.tar' not in text


def test_database_operation_cancel_missing_and_download_identifier_validation(admin_user):
    missing = admin_user.session.post(
        f'/api/admin/database/operations/{uuid.uuid4()}/cancel', timeout=10
    )
    assert_status(missing, 404)

    traversal = admin_user.session.get(
        '/api/admin/database/backups/not-a-backup/download',
        timeout=10,
    )
    assert_status(traversal, 400)


def test_database_status_limit_validation_and_download_rbac(admin_anonymous, admin_regular_user):
    assert_status(admin_anonymous.get('/api/admin/database?limit=101', timeout=10), 401)
    assert_status(admin_regular_user.session.get('/api/admin/database?limit=101', timeout=10), 403)
    assert_status(
        admin_anonymous.get(f'/api/admin/database/backups/{OPAQUE_BACKUP}/download', timeout=10),
        401,
    )
    assert_status(
        admin_regular_user.session.get(f'/api/admin/database/backups/{OPAQUE_BACKUP}/download', timeout=10),
        403,
    )


def test_database_restore_rejects_invalid_or_unknown_backup_identifier(admin_user):
    invalid = admin_user.session.post(
        '/api/admin/database/restores',
        json={'backup_id': 'daily/mreader-safe.dump', 'confirmation': 'RESTORE daily/mreader-safe.dump'},
        timeout=10,
    )
    assert_status(invalid, 400)

    unknown = admin_user.session.post(
        '/api/admin/database/restores',
        json={'backup_id': OPAQUE_BACKUP, 'confirmation': f'RESTORE {OPAQUE_BACKUP}'},
        timeout=10,
    )
    assert_status(unknown, 404)


def test_database_cancel_rejects_terminal_operation(admin_user, db):
    operation_id = str(uuid.uuid4())
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO database_operations(id, operation_type, status, phase, requested_by_username, completed_at)
            VALUES (%s::uuid, 'backup', 'completed', 'backup-complete', 'pytest', now())
            """,
            (operation_id,),
        )
    try:
        response = admin_user.session.post(
            f'/api/admin/database/operations/{operation_id}/cancel', timeout=10
        )
        assert_status(response, 409)
    finally:
        with db.cursor() as cursor:
            cursor.execute('DELETE FROM database_operations WHERE id=%s::uuid', (operation_id,))


def test_database_status_does_not_expose_internal_storage_configuration(admin_user):
    response = admin_user.session.get('/api/admin/database', timeout=15)
    assert_status(response, 200)
    text = response.text
    for marker in ('/srv/', '/backups/mreader/postgres', 'storage-location.json', 'physical_volume_root', 'mount_source', 'filer_url'):
        assert marker not in text
