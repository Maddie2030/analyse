import asyncio
from pathlib import Path

from app.config import settings
from app.staging_store import (
    SPOOL_MARKER,
    _read_or_create_spool_id,
    _probe_writable,
    delete_prefix,
    find_staging_by_prefix,
    get_object,
    put_object,
)


class _NoRemoteClient:
    async def put(self, *args, **kwargs):
        raise AssertionError("staging unexpectedly used remote PUT")

    async def get(self, *args, **kwargs):
        raise AssertionError("staging unexpectedly used remote GET")

    async def delete(self, *args, **kwargs):
        class _Response:
            pass
        return _Response()


def test_staging_is_local_atomic_and_reusable(tmp_path: Path):
    async def run():
        old_root = settings.scraper_staging_root
        settings.scraper_staging_root = str(tmp_path)
        try:
            client = _NoRemoteClient()
            path = (
                "_scraper/series-drafts/11111111-1111-1111-1111-111111111111/"
                "chapters/22222222-2222-2222-2222-222222222222/pages/"
                "0001-33333333-3333-3333-3333-333333333333.webp"
            )
            await put_object(client, path, b"RIFFxxxxWEBPpayload", "image/webp")
            data, content_type = await get_object(client, path)
            assert data == b"RIFFxxxxWEBPpayload"
            assert content_type == "image/webp"
            assert not list(tmp_path.rglob("*.part"))

            prefix = path.rsplit(".", 1)[0]
            assert await find_staging_by_prefix(prefix) == path

            await delete_prefix(
                client,
                "_scraper/series-drafts/11111111-1111-1111-1111-111111111111/chapters/"
                "22222222-2222-2222-2222-222222222222",
            )
            assert not (tmp_path / path).exists()
        finally:
            settings.scraper_staging_root = old_root

    asyncio.run(run())


def test_spool_marker_is_shared_readable_and_stable(tmp_path: Path):
    spool_id = _read_or_create_spool_id(tmp_path)
    marker = tmp_path / SPOOL_MARKER
    assert marker.is_file()
    assert (marker.stat().st_mode & 0o777) == 0o660
    assert marker.read_text(encoding="utf-8").strip() == spool_id
    assert _read_or_create_spool_id(tmp_path) == spool_id


def test_write_probe_preserves_primary_permission_error(tmp_path: Path, monkeypatch):
    import builtins

    def deny_open(*args, **kwargs):
        raise PermissionError(13, "permission denied")

    def deny_unlink(self, *args, **kwargs):
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(builtins, "open", deny_open)
    monkeypatch.setattr(Path, "unlink", deny_unlink)

    try:
        _probe_writable(tmp_path)
    except RuntimeError as exc:
        message = str(exc)
        assert "not writable" in message
        assert "owner=" in message
        assert "mode=" in message
        assert "process=" in message
    else:
        raise AssertionError("permission failure was not surfaced")
