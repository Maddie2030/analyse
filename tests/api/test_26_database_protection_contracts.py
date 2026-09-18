from pathlib import Path
import os
import sys

import pytest


ROOT = Path(os.getenv('MREADER_REPO_ROOT', '/repo'))
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parents[2]
service_root = Path('/repo/services/scraper_service')
if not service_root.exists():
    service_root = ROOT / 'services' / 'scraper_service'
sys.path.insert(0, str(service_root))

from app.database_protection import capability_ready, public_operation  # noqa: E402
from app.local_recovery_catalog import public_local_storage_status, public_recovery_point  # noqa: E402


def _recovery_row(**overrides):
    value = {
        'recovery_id': 'manual-internal-id',
        'public_id': 'bkp_0123456789abcdef01234567',
        'kind': 'logical_dump',
        'purpose': 'manual',
        'relative_directory': 'dumps/manual/manual-internal-id',
        'artifact_name': 'database.dump',
        'created_at': '2026-09-12T03:00:00+00:00',
        'postgres_major': 16,
        'mreader_version': 'v1.3.0-rc4.85',
        'size_bytes': 1234,
        'sha256': 'a' * 64,
        'verified': True,
        'available': True,
    }
    value.update(overrides)
    return value


def test_public_recovery_point_hides_host_local_storage_details():
    public = public_recovery_point(_recovery_row())
    assert public['id'] == 'bkp_0123456789abcdef01234567'
    assert public['kind'] == 'logical_dump'
    assert public['type'] == 'manual'
    for field in ('recovery_id', 'relative_directory', 'artifact_name', 'sha256'):
        assert field not in public
    assert 'dumps/manual' not in repr(public)


@pytest.mark.parametrize(
    ('available', 'capability', 'expected'),
    [(True, True, True), (True, False, False), (False, True, False)],
)
def test_capability_requires_live_agent_and_explicit_flag(available, capability, expected):
    runtime = {'available': available, 'capabilities': {'restore': capability}}
    assert capability_ready(runtime, 'restore') is expected


def test_public_local_status_comes_from_agent_and_catalog_without_paths():
    public = public_local_storage_status(
        {'available': True, 'capabilities': {'local_storage_ready': True}},
        [_recovery_row()],
    )
    assert public['healthy'] is True
    assert public['local_storage_ready'] is True
    assert public['backup_count'] == 1
    for marker in ('/srv/', '/backups/', 'dumps/manual', 'filer_url', 'mount_source'):
        assert marker not in repr(public)


def test_public_operation_uses_catalog_id_and_hides_internal_result():
    public = public_operation({
        'id': '11111111-1111-1111-1111-111111111111',
        'operation_type': 'restore',
        'status': 'failed',
        'phase': 'atomic-cutover',
        'category': 'manual',
        'backup_filename': 'manual-internal-id',
        'requested_by_username': 'admin',
        'requested_at': '2026-09-12T03:00:00Z',
        'started_at': None,
        'completed_at': None,
        'error': 'failed at /private/recovery/root',
        'metadata': {'recovery_public_id': 'bkp_0123456789abcdef01234567'},
        'result': {'recovery_id': 'manual-internal-id'},
    })
    assert public['backup_id'] == 'bkp_0123456789abcdef01234567'
    for field in ('backup_filename', 'category', 'metadata', 'result', 'error'):
        assert field not in public
    assert 'manual-internal-id' not in repr(public)
    assert '/private/' not in repr(public)


def test_public_operation_rejects_untrusted_public_id_in_internal_metadata():
    public = public_operation({
        'id': '11111111-1111-1111-1111-111111111111',
        'operation_type': 'restore_drill',
        'status': 'queued',
        'phase': 'queued',
        'metadata': {'recovery_public_id': '../../database.dump'},
        'result': {},
    })
    assert public['backup_id'] is None
