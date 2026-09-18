from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
import uuid
import time
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import httpx

from app.config import settings


STAGING_PREFIX = "_scraper/"
SPOOL_MARKER = ".mreader-staging-spool-id"


class StagedObjectMissing(FileNotFoundError):
    pass


def is_staging_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    return normalized.startswith(STAGING_PREFIX)


def _safe_relative(path: str) -> Path:
    posix = PurePosixPath(str(path or "").replace("\\", "/").lstrip("/"))
    if not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"Invalid storage path: {path!r}")
    return Path(*posix.parts)


def local_staging_path(path: str) -> Path:
    if not is_staging_path(path):
        raise ValueError(f"Not a scraper staging path: {path!r}")
    root = staging_root()
    target = (root / _safe_relative(path)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Staging path escapes configured root: {path!r}") from exc
    return target


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)



def staging_root() -> Path:
    return Path(settings.scraper_staging_root).expanduser().resolve()


def _mountinfo_has_path(path: Path) -> bool:
    """Return True when Linux reports the staging root as an actual mountpoint.

    Docker volume mounts can live on the same device as their parent, so
    os.path.ismount() alone is not reliable. /proc/self/mountinfo exposes bind
    mounts explicitly and is available in the Linux containers used by MReader.
    """
    try:
        wanted = str(path)
        for line in Path("/proc/self/mountinfo").read_text(errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            mountpoint = parts[4].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
            if mountpoint == wanted:
                return True
    except OSError:
        pass
    return False


def _read_or_create_spool_id(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    marker = root / SPOOL_MARKER
    try:
        raw = marker.read_text(encoding="utf-8").strip()
        return str(uuid.UUID(raw))
    except FileNotFoundError:
        pass
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Invalid scraper staging spool marker at {marker}: {exc}") from exc

    candidate = str(uuid.uuid4())
    try:
        fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
    except FileExistsError:
        raw = marker.read_text(encoding="utf-8").strip()
        return str(uuid.UUID(raw))
    try:
        # os.open mode is subject to umask; force the shared marker mode so
        # scraper/lifecycle images can read the same volume marker reliably.
        os.fchmod(fd, 0o660)
        os.write(fd, (candidate + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(root)
    return candidate


def _permission_context(root: Path) -> str:
    try:
        st = root.stat()
        mode = oct(st.st_mode & 0o7777)
        owner = f"{st.st_uid}:{st.st_gid}"
    except OSError as exc:
        mode = "unknown"
        owner = f"unknown({exc})"
    try:
        proc = f"{os.geteuid()}:{os.getegid()}"
    except AttributeError:
        proc = "unknown"
    return f"root={root} owner={owner} mode={mode} process={proc}"


def _probe_writable(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    probe = root / f".write-probe-{uuid.uuid4().hex}"
    try:
        with open(probe, "wb") as handle:
            handle.write(b"mreader-staging-probe")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise RuntimeError(
            "Scraper staging Docker volume is not writable after startup ownership repair; "
            + _permission_context(root)
            + ". Rebuild/recreate the scraper and lifecycle containers so the RC4.13 "
              "privilege-drop entrypoint can repair the volume before the app starts."
        ) from exc
    finally:
        # A failed create/unlink inside a non-writable directory can itself raise
        # EACCES. Never let cleanup mask the original write failure.
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def staging_runtime_status() -> dict:
    root = staging_root()
    spool_id = None
    marker = root / SPOOL_MARKER
    try:
        spool_id = str(uuid.UUID(marker.read_text(encoding="utf-8").strip()))
    except Exception:
        pass
    try:
        usage = shutil.disk_usage(root if root.exists() else root.parent)
        free_bytes = int(usage.free)
    except OSError:
        free_bytes = None
    try:
        st = root.stat()
        root_uid = int(st.st_uid)
        root_gid = int(st.st_gid)
        root_mode = oct(st.st_mode & 0o7777)
    except OSError:
        root_uid = root_gid = None
        root_mode = None
    return {
        "root": str(root),
        "spool_id": spool_id,
        "exists": root.exists(),
        "writable": os.access(root, os.W_OK) if root.exists() else False,
        "mount_visible": _mountinfo_has_path(root),
        "free_bytes": free_bytes,
        "root_uid": root_uid,
        "root_gid": root_gid,
        "root_mode": root_mode,
        "process_uid": os.geteuid() if hasattr(os, "geteuid") else None,
        "process_gid": os.getegid() if hasattr(os, "getegid") else None,
        "storage_backend": os.getenv("SCRAPER_STAGING_BACKEND", "docker-volume").strip() or "docker-volume",
        "volume_name_hint": os.getenv("SCRAPER_STAGING_VOLUME_NAME", "mreader_scraper_staging").strip() or "mreader_scraper_staging",
    }


async def _staging_reference_sample(pool, *, limit: int = 200) -> list[str]:
    """Return logical staged paths PostgreSQL still considers live."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH refs AS (
                SELECT p->>'staging_path' AS path
                FROM scraper_series_draft_chapters c
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.pages,'[]'::jsonb)) p
                WHERE c.published_chapter_id IS NULL
                  AND COALESCE(p->>'staging_path','') LIKE '_scraper/%'
                UNION
                SELECT d.cover_staging_path AS path
                FROM scraper_series_drafts d
                WHERE d.published_series_id IS NULL
                  AND COALESCE(d.cover_staging_path,'') LIKE '_scraper/%'
                UNION
                SELECT p->>'staging_path' AS path
                FROM scraper_drafts d
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(d.pages,'[]'::jsonb)) p
                WHERE COALESCE(p->>'staging_path','') LIKE '_scraper/%'
                UNION
                SELECT p->>'staging_path' AS path
                FROM scraper_batch_items i
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(i.source_files,'[]'::jsonb)) p
                WHERE COALESCE(p->>'staging_path','') LIKE '_scraper/%'
                  AND i.status NOT IN ('completed','discarded')
            )
            SELECT path FROM refs WHERE path IS NOT NULL AND path <> '' ORDER BY path LIMIT $1
            """,
            max(1, min(1000, int(limit))),
        )
    return [str(row['path']) for row in rows]


async def staging_reference_status(pool) -> dict:
    refs = await _staging_reference_sample(pool)
    visible = 0
    missing: list[str] = []
    for logical_path in refs:
        try:
            exists = await asyncio.to_thread(local_staging_path(logical_path).is_file)
        except (ValueError, OSError):
            exists = False
        if exists:
            visible += 1
        else:
            missing.append(logical_path)
    return {
        'reference_sample': len(refs),
        'reference_visible': visible,
        'reference_missing': len(missing),
        'reference_missing_examples': missing[:5],
    }


async def ensure_staging_spool(pool, *, service_name: str) -> dict:
    """Require every scraper process to see the registered staging PVC/spool."""
    root = staging_root()
    await asyncio.to_thread(_probe_writable, root)
    spool_id = await asyncio.to_thread(_read_or_create_spool_id, root)
    mount_visible = _mountinfo_has_path(root)
    if settings.scraper_staging_require_shared_mount and not mount_visible:
        raise RuntimeError(
            'SCRAPER_STAGING_ROOT is not the shared Kubernetes staging mount. '
            f'current root={root}'
        )
    reference_status = await staging_reference_status(pool)
    if reference_status['reference_missing']:
        examples = ', '.join(reference_status['reference_missing_examples'][:3])
        raise RuntimeError(
            'PostgreSQL references staged files missing from the canonical scraper PVC. '
            f'Re-stage/re-upload them before starting. root={root} missing_examples=[{examples}]'
        )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext('mreader:scraper-staging-spool-registry'))"
            )
            row = await conn.fetchrow(
                'SELECT spool_id::text, logical_root FROM scraper_staging_spool_registry WHERE id=1 FOR UPDATE'
            )
            if row is None:
                await conn.execute(
                    'INSERT INTO scraper_staging_spool_registry(id,spool_id,logical_root,last_service,last_seen_at) '
                    'VALUES (1,$1::uuid,$2,$3,NOW())',
                    spool_id, str(root), service_name,
                )
            elif str(row['spool_id']) != spool_id:
                raise RuntimeError(
                    'Scraper staging spool mismatch. Current MReader does not auto-adopt a new PVC/spool. '
                    f"expected={row['spool_id']} actual={spool_id} root={root}. "
                    'Restore the registered PVC or explicitly clear/re-stage test drafts.'
                )
            else:
                await conn.execute(
                    'UPDATE scraper_staging_spool_registry SET logical_root=$1,last_service=$2,last_seen_at=NOW() WHERE id=1',
                    str(root), service_name,
                )
    return {**staging_runtime_status(), **reference_status, 'spool_id': spool_id, 'service': service_name}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_copy_stream(path: Path, source: BinaryIO, *, max_bytes: int, chunk_bytes: int = 1024 * 1024) -> int:
    """Durably copy one upload to the local spool without materializing it in RAM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    total = 0
    try:
        try:
            source.seek(0)
        except (AttributeError, OSError):
            pass
        with open(tmp, "wb") as handle:
            while True:
                chunk = source.read(max(64 * 1024, int(chunk_bytes)))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Upload exceeds maximum size of {max_bytes} bytes")
                handle.write(chunk)
            if total <= 0:
                raise ValueError("Upload is empty")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
        return total
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _read(path: Path) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError as exc:
        raise StagedObjectMissing(str(path)) from exc


def _delete_local(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except IsADirectoryError:
        shutil.rmtree(path, ignore_errors=True)


def _delete_local_prefix(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _cleanup_parts(root: Path) -> int:
    if not root.exists():
        return 0
    removed = 0
    cutoff = time.time() - max(60, settings.scraper_staging_incomplete_ttl_minutes * 60)
    for candidate in root.rglob("*.part"):
        try:
            if candidate.stat().st_mtime > cutoff:
                continue
            candidate.unlink()
            removed += 1
        except OSError:
            pass
    # Atomic writes use .<name>.<uuid>.part. rglob('*.part') catches those too.
    return removed


async def cleanup_incomplete_staging_files() -> int:
    root = staging_root()
    return await asyncio.to_thread(_cleanup_parts, root)


_REMOTE_WRITE_SEMAPHORE = asyncio.Semaphore(max(1, settings.scraper_storage_write_concurrency))
_REMOTE_NEXT_WRITE_AT = 0.0


async def _pace_remote_write() -> None:
    global _REMOTE_NEXT_WRITE_AT
    delay = _REMOTE_NEXT_WRITE_AT - asyncio.get_running_loop().time()
    if delay > 0:
        await asyncio.sleep(delay)


def _record_remote_write_latency(elapsed: float) -> None:
    global _REMOTE_NEXT_WRITE_AT
    if elapsed < max(0.1, settings.scraper_storage_slow_write_threshold_seconds):
        return
    cooldown = max(0.0, settings.scraper_storage_slow_write_cooldown_seconds)
    if cooldown <= 0:
        return
    loop = asyncio.get_running_loop()
    _REMOTE_NEXT_WRITE_AT = max(_REMOTE_NEXT_WRITE_AT, loop.time() + cooldown)


async def _remote_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    data: bytes | None = None,
    content_type: str | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """Bounded retry for the remote production/legacy SeaweedFS tier.

    Local scraper staging never comes through here. Deterministic filer paths
    make PUT/GET/DELETE safe to retry after a lost acknowledgement.
    """
    attempts = max(1, int(settings.scraper_storage_network_max_attempts))
    base = max(0.1, float(settings.scraper_storage_network_retry_base_seconds))
    cap = max(base, float(settings.scraper_storage_network_retry_max_delay_seconds))
    retry_status = {408, 425, 429, 500, 502, 503, 504}
    url = f"{settings.seaweedfs_filer_url.rstrip('/')}/{path.lstrip('/')}"
    last_error: Exception | None = None
    last_response: httpx.Response | None = None

    for attempt in range(1, attempts + 1):
        try:
            headers = {"Content-Type": content_type} if content_type else None
            response = await client.request(
                method,
                url,
                content=data,
                headers=headers,
                params=params,
            )
            last_response = response
            if response.status_code not in retry_status:
                return response
            last_error = httpx.HTTPStatusError(
                f"temporary SeaweedFS response {response.status_code}",
                request=response.request,
                response=response,
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_error = exc

        if attempt < attempts:
            await asyncio.sleep(min(cap, base * (2 ** (attempt - 1))))

    if last_error is not None:
        raise last_error
    assert last_response is not None
    return last_response


async def _remote_put(client: httpx.AsyncClient, path: str, data: bytes, content_type: str) -> None:
    async with _REMOTE_WRITE_SEMAPHORE:
        await _pace_remote_write()
        started = asyncio.get_running_loop().time()
        try:
            response = await _remote_request(
                client, "PUT", path, data=data, content_type=content_type
            )
            response.raise_for_status()
        finally:
            _record_remote_write_latency(asyncio.get_running_loop().time() - started)


async def _remote_get(client: httpx.AsyncClient, path: str) -> tuple[bytes, str]:
    response = await _remote_request(client, "GET", path)
    if response.status_code == 404:
        raise StagedObjectMissing(path)
    response.raise_for_status()
    return response.content, response.headers.get("content-type", "application/octet-stream")


async def _remote_delete(client: httpx.AsyncClient, path: str) -> None:
    try:
        response = await _remote_request(client, "DELETE", path)
        if response.status_code not in (200, 202, 204, 404):
            response.raise_for_status()
    except Exception:
        # Legacy/staging cleanup is deliberately best effort here. Production
        # cleanup is handled by the durable lifecycle worker.
        pass


async def _remote_delete_prefix(client: httpx.AsyncClient, prefix: str) -> None:
    try:
        response = await _remote_request(
            client, "DELETE", prefix, params={"recursive": "true"}
        )
        if response.status_code not in (200, 202, 204, 404):
            response.raise_for_status()
    except Exception:
        pass


async def put_object(
    client: httpx.AsyncClient,
    path: str,
    data: bytes,
    content_type: str,
) -> None:
    """Write scraper-private staging locally; production objects remain on SeaweedFS."""
    if is_staging_path(path):
        await asyncio.to_thread(_atomic_write, local_staging_path(path), data)
        return
    await _remote_put(client, path, data, content_type)


async def put_upload_object(
    path: str,
    source: BinaryIO,
    *,
    max_bytes: int,
) -> int:
    """Stream an already-spooled multipart upload into durable local staging."""
    if not is_staging_path(path):
        raise ValueError("Streaming upload helper is restricted to scraper staging paths.")
    return await asyncio.to_thread(
        _atomic_copy_stream,
        local_staging_path(path),
        source,
        max_bytes=max_bytes,
    )


async def get_object(client: httpx.AsyncClient, path: str) -> tuple[bytes, str]:
    """Read scraper-private staging locally; production objects remain on SeaweedFS."""
    if not is_staging_path(path):
        return await _remote_get(client, path)
    local_path = local_staging_path(path)
    data = await asyncio.to_thread(_read, local_path)
    guessed = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    return data, guessed


async def delete_object(client: httpx.AsyncClient, path: str) -> None:
    if is_staging_path(path):
        await asyncio.to_thread(_delete_local, local_staging_path(path))
        return
    await _remote_delete(client, path)


async def delete_prefix(client: httpx.AsyncClient, prefix: str) -> None:
    if is_staging_path(prefix):
        await asyncio.to_thread(_delete_local_prefix, local_staging_path(prefix))
        return
    await _remote_delete_prefix(client, prefix)


def _find_by_prefix(prefix: str) -> str | None:
    base = local_staging_path(prefix)
    parent = base.parent
    if not parent.exists():
        return None
    matches = sorted(parent.glob(base.name + ".*"))
    root = staging_root()
    for candidate in matches:
        if candidate.is_file() and not candidate.name.endswith(".part"):
            return candidate.resolve().relative_to(root).as_posix()
    return None


async def find_staging_by_prefix(prefix: str) -> str | None:
    if not is_staging_path(prefix):
        return None
    return await asyncio.to_thread(_find_by_prefix, prefix)


def content_type_for_path(path: str) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


async def staging_exists(path: str) -> bool:
    if not is_staging_path(path):
        return False
    return await asyncio.to_thread(local_staging_path(path).is_file)
