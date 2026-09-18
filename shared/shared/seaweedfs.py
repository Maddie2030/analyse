import asyncio
import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

_assign_lock = None


def _get_lock():
    global _assign_lock
    if _assign_lock is None:
        _assign_lock = asyncio.Lock()
    return _assign_lock


class SeaweedFSClient:
    """Async SeaweedFS client — assigns file IDs from the master and uploads/fetches via HTTP."""

    def __init__(self) -> None:
        self._master_url = settings.SEAWEEDFS_MASTER_URL.rstrip("/")
        self._filer_url = settings.SEAWEEDFS_FILER_URL.rstrip("/")
        self._replication = settings.SEAWEEDFS_REPLICATION
        self._timeout = httpx.Timeout(
            settings.SEAWEEDFS_CONNECT_TIMEOUT,
            read=settings.SEAWEEDFS_READ_TIMEOUT,
        )
        self._write_sem = asyncio.Semaphore(max(1, settings.SEAWEEDFS_WRITE_CONCURRENCY))
        self._slow_write_threshold = max(0.1, float(settings.SEAWEEDFS_SLOW_WRITE_THRESHOLD_SECONDS))
        self._slow_write_cooldown = max(0.0, float(settings.SEAWEEDFS_SLOW_WRITE_COOLDOWN_SECONDS))
        self._next_write_at = 0.0
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            limits=httpx.Limits(
                max_connections=max(8, settings.SEAWEEDFS_HTTP_MAX_CONNECTIONS),
                max_keepalive_connections=max(4, settings.SEAWEEDFS_HTTP_KEEPALIVE_CONNECTIONS),
            ),
        )

    @property
    def filer_url(self) -> str:
        """Expose filer URL safely for external references."""
        return self._filer_url

    @staticmethod
    def _retryable_response(resp: httpx.Response) -> bool:
        return resp.status_code in {408, 425, 429, 500, 502, 503, 504}

    async def _request_with_retries(self, operation: str, request_factory):
        """Retry transient SeaweedFS/network failures with bounded backoff.

        Filer paths are deterministic, so a request whose acknowledgement was
        lost can be repeated safely. Logic/4xx failures remain immediate.
        """
        attempts = max(1, int(settings.SEAWEEDFS_MAX_RETRIES))
        base = max(0.1, float(settings.SEAWEEDFS_RETRY_BASE_SECONDS))
        cap = max(base, float(settings.SEAWEEDFS_RETRY_MAX_DELAY_SECONDS))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await request_factory()
                if not self._retryable_response(response):
                    return response
                last_error = httpx.HTTPStatusError(
                    f"temporary SeaweedFS response {response.status_code}",
                    request=response.request,
                    response=response,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc

            if attempt < attempts:
                delay = min(cap, base * (2 ** (attempt - 1)))
                log.warning(
                    "SeaweedFS transient failure operation=%s attempt=%s/%s retry_in=%.1fs error=%s",
                    operation, attempt, attempts, delay, last_error,
                )
                await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    async def _write_with_backpressure(self, operation: str, request_factory):
        """Bound NAS writes and briefly pace writers when latency rises.

        Reader traffic reaches the filer through the image edge independently,
        so slowing background/admin writes here gives cold user reads room without
        adding RAM/CPU or introducing a separate scheduler.
        """
        async with self._write_sem:
            loop = asyncio.get_running_loop()
            delay = self._next_write_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            started = loop.time()
            try:
                return await self._request_with_retries(operation, request_factory)
            finally:
                elapsed = loop.time() - started
                if elapsed >= self._slow_write_threshold and self._slow_write_cooldown > 0:
                    self._next_write_at = max(
                        self._next_write_at, loop.time() + self._slow_write_cooldown
                    )

    async def assign_fid(self, count: int = 1) -> dict[str, Any]:
        """Request one or more file IDs from the master."""
        params = {"count": str(count), "replication": self._replication}
        resp = await self._request_with_retries(
            "assign_fid",
            lambda: self._client.get(f"{self._master_url}/dir/assign", params=params),
        )
        resp.raise_for_status()
        return resp.json()

    async def upload(self, data: bytes, fid: str, mime_type: str = "image/webp") -> dict[str, Any]:
        """Upload bytes to a volume server using an assigned fid."""
        assign = await self.assign_fid(1)
        fid = assign.get("fid", fid)
        url = assign["url"]
        resp = await self._client.post(
            f"http://{url}/{fid}",
            content=data,
            headers={"Content-Type": mime_type},
        )
        resp.raise_for_status()
        return {"fid": fid, "url": url, **resp.json()}

    async def upload_via_filer(
        self, path: str, content: bytes, content_type: str = "image/webp"
    ) -> httpx.Response:
        """Upload via the filer so files are addressable by path using multipart upload."""
        url = f"{self._filer_url}/{path.lstrip('/')}"
        files = {
            "file": ("file", content, content_type)
        }
        resp = await self._write_with_backpressure(
            "upload_via_filer",
            lambda: self._client.post(url, files=files),
        )
        resp.raise_for_status()
        return resp

    async def upload_file_via_filer(
        self,
        path: str,
        file_obj,
        content_type: str = "application/octet-stream",
        *,
        filename: str = "file",
    ) -> httpx.Response:
        """Stream a seekable file object to the filer without materializing it in RAM.

        FastAPI/Starlette ``UploadFile.file`` is a ``SpooledTemporaryFile``. Passing
        that object to HTTPX multipart encoding keeps memory bounded by HTTPX's
        multipart chunk size instead of copying a potentially hundreds-of-MB
        chapter archive into a Python ``bytes`` object.
        """
        url = f"{self._filer_url}/{path.lstrip('/')}"
        try:
            file_obj.seek(0)
        except (AttributeError, OSError):
            pass
        async def send():
            try:
                file_obj.seek(0)
            except (AttributeError, OSError):
                pass
            files = {"file": (filename or "file", file_obj, content_type)}
            return await self._client.post(url, files=files)

        resp = await self._write_with_backpressure("upload_file_via_filer", send)
        resp.raise_for_status()
        return resp

    async def download_via_filer_to_path(
        self,
        path: str,
        destination: str,
        *,
        max_bytes: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> tuple[str, int]:
        """Stream one filer object to disk and return ``(content_type, size)``.

        This is used by CPU-heavy media workers so a large archive lives on the
        worker's temporary filesystem rather than being duplicated in RAM before
        ZIP/PDF processing starts.
        """
        url = f"{self._filer_url}/{path.lstrip('/')}"
        total = 0
        content_type = "application/octet-stream"
        async with self._client.stream("GET", url) as resp:
            if resp.status_code == 404:
                raise FileNotFoundError(f"SeaweedFS: {path} not found")
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", content_type)
            with open(destination, "wb") as handle:
                async for chunk in resp.aiter_bytes(chunk_size=max(64 * 1024, int(chunk_size))):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if max_bytes is not None and total > int(max_bytes):
                        raise ValueError(f"SeaweedFS object exceeds {int(max_bytes)} bytes")
                    handle.write(chunk)
        return content_type, total

    async def fetch(self, fid_or_path: str) -> bytes:
        """Fetch file content. Accepts either a fid or a filer path."""
        if "/" in fid_or_path and not fid_or_path[0].isdigit():
            url = f"{self._filer_url}/{fid_or_path.lstrip('/')}"
        else:
            url = f"{self._filer_url}/{fid_or_path}"
        resp = await self._request_with_retries("fetch", lambda: self._client.get(url))
        resp.raise_for_status()
        return resp.content

    async def fetch_via_filer(self, path: str) -> tuple[bytes, str]:
        """Fetch via filer path, returning (content, content_type)."""
        url = f"{self._filer_url}/{path.lstrip('/')}"
        resp = await self._request_with_retries("fetch_via_filer", lambda: self._client.get(url))
        if resp.status_code == 404:
            raise FileNotFoundError(f"SeaweedFS: {path} not found")
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    async def delete_via_filer(self, path: str) -> None:
        url = f"{self._filer_url}/{path.lstrip('/')}"
        resp = await self._write_with_backpressure("delete_via_filer", lambda: self._client.delete(url))
        if resp.status_code not in (200, 202, 204, 404):
            resp.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()


_seaweedfs_client: SeaweedFSClient | None = None


def init_seaweedfs_client() -> SeaweedFSClient:
    global _seaweedfs_client
    if _seaweedfs_client is None:
        _seaweedfs_client = SeaweedFSClient()
    return _seaweedfs_client


async def close_seaweedfs_client() -> None:
    global _seaweedfs_client
    if _seaweedfs_client is not None:
        await _seaweedfs_client.close()
        _seaweedfs_client = None


def get_seaweedfs() -> SeaweedFSClient:
    if _seaweedfs_client is None:
        init_seaweedfs_client()
    return _seaweedfs_client