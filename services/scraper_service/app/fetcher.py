from __future__ import annotations

import asyncio
import base64
import html as html_lib
import json
import re
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException

from app.config import settings
from app.security import resolve_public_addresses, validate_public_url


log = logging.getLogger("scraper.fetcher")

REDIRECT_CODES = {301, 302, 303, 307, 308}
RETRY_CODES = {408, 425, 429, 500, 502, 503, 504}

# One Chromium fallback at a time per scraper process by default. This is
# intentionally independent from worker concurrency so four staging workers do
# not accidentally launch four browsers and exhaust container memory.
_BROWSER_SEMAPHORE = asyncio.Semaphore(max(1, settings.scraper_browser_concurrency))
# hostname -> (lightweight engine, monotonic_expiry). Chromium is deliberately
# never remembered host-wide: one JS-heavy/gated URL must not force every
# later request on that domain into a browser.
_ENGINE_AFFINITY: OrderedDict[str, tuple[str, float]] = OrderedDict()
_ENGINE_AFFINITY_LOCK = asyncio.Lock()


def browser_fallback_available() -> bool:
    """Return whether a usable browser renderer is configured for this process.

    Normal scraper containers intentionally ship without Chromium. They can use
    the optional internal browser worker through SCRAPER_BROWSER_REMOTE_URL.
    The dedicated browser worker sets MREADER_BROWSER_LOCAL_RUNTIME=1 and calls
    the local renderer directly.
    """
    if not settings.scraper_browser_fallback_enabled:
        return False
    if settings.scraper_browser_remote_url.strip():
        return True
    return os.getenv("MREADER_BROWSER_LOCAL_RUNTIME", "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    content: bytes
    redirects: list[str]
    resolved_addresses: list[str]
    elapsed_ms: float
    engine: str = "httpx"


def browser_headers(
    *,
    accept: str,
    referer: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "User-Agent": settings.scraper_user_agent,
        "Accept": accept,
        "Accept-Language": settings.scraper_accept_language,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    if referer:
        headers["Referer"] = referer
    if extra_headers:
        # Source adapters may need harmless browser request metadata (for
        # example Naver's same-origin JSON endpoint). Keep transport/security
        # headers owned by the fetcher itself.
        blocked = {"host", "content-length", "connection", "transfer-encoding"}
        for key, value in extra_headers.items():
            if str(key).lower() not in blocked and value is not None:
                headers[str(key)] = str(value)

    return headers


def _looks_like_html(content: bytes) -> bool:
    head = content[:4096].lstrip().lower()
    return (
        head.startswith(b"<!doctype html")
        or b"<html" in head
        or b"<body" in head
        or b"<head" in head
    )


def _looks_like_cloudflare_challenge(content: bytes) -> bool:
    head = content[:256 * 1024].lower()
    markers = (
        b"challenges.cloudflare.com",
        b"cf-chl-",
        b"just a moment",
        b"checking your browser",
        b"cloudflare ray id",
    )
    return sum(marker in head for marker in markers) >= 2


def _looks_like_browser_gate(content: bytes) -> bool:
    """Detect common anti-bot/JS gate shells without classifying normal pages.

    The parser-failure fallback handles plain JS applications, so this detector
    stays conservative and is only used to escalate obviously blocked HTML.
    """
    head = content[:512 * 1024].lower()
    if _looks_like_cloudflare_challenge(content):
        return True

    strong_markers = (
        b"verify you are human",
        b"enable javascript and cookies to continue",
        b"checking if the site connection is secure",
        b"attention required! | cloudflare",
        b"captcha-delivery.com",
        b"g-recaptcha",
        b"hcaptcha-container",
    )
    if any(marker in head for marker in strong_markers):
        return True

    weak_markers = (
        b"access denied",
        b"automated access",
        b"bot detection",
        b"unusual traffic",
        b"security check",
    )
    return sum(marker in head for marker in weak_markers) >= 2


def _looks_like_js_shell(content: bytes) -> bool:
    """Conservatively identify HTML shells whose useful DOM appears after JS."""
    sample = content[:1024 * 1024]
    lower = sample.lower()
    app_markers = (
        b'id="__next"', b"id='__next'", b"__next_data__",
        b'id="__nuxt"', b"id='__nuxt'", b"__nuxt__",
        b'id="root"', b"id='root'", b'id="app"', b"id='app'",
        b"/_next/static/", b"/_nuxt/", b"data-reactroot",
    )
    if not any(marker in lower for marker in app_markers):
        return False
    if lower.count(b"<a ") >= 6 or lower.count(b"<img") >= 4:
        return False
    try:
        text = lower
        for tag in (b"script", b"style", b"noscript"):
            while True:
                start = text.find(b"<" + tag)
                if start < 0:
                    break
                end = text.find(b"</" + tag + b">", start)
                if end < 0:
                    text = text[:start]
                    break
                text = text[:start] + b" " + text[end + len(tag) + 3:]
        text = __import__("re").sub(br"<[^>]+>", b" ", text)
        text = __import__("re").sub(br"\s+", b" ", text).strip()
        return len(text) < 600
    except Exception:
        return False


async def _get_engine_affinity(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    now = time.monotonic()
    async with _ENGINE_AFFINITY_LOCK:
        item = _ENGINE_AFFINITY.get(host)
        if item is None:
            return None
        engine, expires = item
        if engine == "scrapling-browser":
            _ENGINE_AFFINITY.pop(host, None)
            return None
        if expires <= now:
            _ENGINE_AFFINITY.pop(host, None)
            return None
        _ENGINE_AFFINITY.move_to_end(host)
        return engine


async def _remember_engine(url: str, engine: str) -> None:
    # Host-level affinity is useful for curl/TLS compatibility but dangerous
    # for Chromium: a single dynamic chapter would otherwise make an entire
    # site browser-first for the TTL, multiplying CPU/RAM and duplicate image
    # traffic. Browser fallback is intentionally re-evaluated per request.
    if engine in {"httpx", "scrapling-browser"}:
        return
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return
    ttl = max(0, int(settings.scraper_engine_affinity_ttl_seconds))
    if ttl <= 0:
        return
    async with _ENGINE_AFFINITY_LOCK:
        _ENGINE_AFFINITY[host] = (engine, time.monotonic() + ttl)
        _ENGINE_AFFINITY.move_to_end(host)
        limit = max(16, int(settings.scraper_engine_affinity_max_hosts))
        while len(_ENGINE_AFFINITY) > limit:
            _ENGINE_AFFINITY.popitem(last=False)


def sniff_image_content_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"BM"):
        return "image/bmp"
    if len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    if content[:4] in {b"II*\x00", b"MM\x00*"}:
        return "image/tiff"
    if content.lstrip().startswith(b"<svg"):
        return "image/svg+xml"
    return None


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                return min(float(raw), 15.0)
            except ValueError:
                try:
                    dt = parsedate_to_datetime(raw)
                    seconds = dt.timestamp() - time.time()
                    if seconds > 0:
                        return min(seconds, 15.0)
                except Exception:
                    pass

    return min(
        settings.scraper_retry_base_seconds * (2 ** max(0, attempt - 1)),
        6.0,
    )


async def _read_bounded(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    413,
                    f"Source response exceeds {max_bytes} bytes.",
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0

    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413,
                f"Source response exceeds {max_bytes} bytes.",
            )
        chunks.append(chunk)

    return b"".join(chunks)


def _normalize_content_type(headers: object) -> str:
    try:
        raw = headers.get("content-type") or "application/octet-stream"  # type: ignore[attr-defined]
    except Exception:
        raw = "application/octet-stream"
    return str(raw).split(";", 1)[0].strip().lower()


def _validate_payload(
    *,
    content: bytes,
    content_type: str,
    expected: str,
    max_bytes: int,
) -> str:
    if len(content) > max_bytes:
        raise HTTPException(413, f"Source response exceeds {max_bytes} bytes.")

    if expected == "html":
        if (
            content_type not in {"text/html", "application/xhtml+xml"}
            and not _looks_like_html(content)
        ):
            raise HTTPException(415, f"Source returned non-HTML content: {content_type}.")

    if not content:
        raise HTTPException(502, "Source returned an empty response body.")

    if expected == "json":
        sample = content.lstrip()[:1]
        # API endpoints sometimes answer a blocked request with HTTP 200 and an
        # HTML challenge/login shell. Classify that as a transport failure so
        # fetch_external can retry through Scrapling/curl_cffi rather than
        # failing later in json.loads after the escalation boundary is gone.
        if _looks_like_html(content) or _looks_like_browser_gate(content):
            raise HTTPException(502, "Source returned HTML/challenge content instead of JSON.")
        json_mime = (
            content_type == "application/json"
            or content_type.endswith("+json")
            or content_type in {"text/json", "text/plain", "application/octet-stream"}
        )
        if not json_mime and sample not in {b"{", b"["}:
            raise HTTPException(502, f"Source returned non-JSON content: {content_type}.")
        if sample not in {b"{", b"["}:
            raise HTTPException(502, "Source returned a non-JSON response body.")

    if expected == "image":
        sniffed = sniff_image_content_type(content)
        # Some CDNs/WAFs return an HTML challenge/error while retaining an
        # image Content-Type. Never let that poison staged chapter archives.
        if _looks_like_html(content) or _looks_like_browser_gate(content):
            raise HTTPException(502, "Source returned HTML/challenge content instead of an image.")
        if not content_type.startswith("image/"):
            if sniffed:
                content_type = sniffed
            else:
                raise HTTPException(
                    415,
                    f"Source returned non-image content: {content_type}.",
                )
        elif sniffed:
            content_type = sniffed

    return content_type


async def _fetch_external_httpx(
    client: httpx.AsyncClient,
    *,
    normalized: str,
    addresses: list[str],
    accept: str,
    max_bytes: int,
    referer: str | None,
    expected: str,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    last_error: Exception | None = None

    for attempt in range(1, settings.scraper_fetch_attempts + 1):
        current = normalized
        redirects: list[str] = []
        started = time.perf_counter()
        retry_response: httpx.Response | None = None
        current_referer = referer

        try:
            for redirect_index in range(settings.scraper_max_redirects + 1):
                # Important: validate every hop before connecting to it.
                current = await validate_public_url(current)

                async with client.stream(
                    "GET",
                    current,
                    headers=browser_headers(
                        accept=accept,
                        referer=current_referer,
                        extra_headers=extra_headers,
                    ),
                    follow_redirects=False,
                ) as response:
                    if response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(
                                502,
                                "Source returned a redirect without Location.",
                            )

                        if redirect_index >= settings.scraper_max_redirects:
                            raise HTTPException(
                                502,
                                "Source exceeded redirect limit.",
                            )

                        next_url = urljoin(current, location)
                        # Validate the redirect BEFORE a network connection.
                        await validate_public_url(next_url)
                        redirects.append(next_url)
                        # Correct browser semantics: Referer is the page we came
                        # from, not the destination URL.
                        current_referer = current
                        current = next_url
                        continue

                    if response.status_code in RETRY_CODES:
                        retry_response = response
                        last_error = HTTPException(
                            502,
                            f"Source returned HTTP {response.status_code}.",
                        )
                        break

                    if response.status_code >= 400:
                        body = await _read_bounded(
                            response,
                            max_bytes=min(max_bytes, 256 * 1024),
                        )
                        if response.status_code in {403, 429} and _looks_like_browser_gate(body):
                            raise HTTPException(
                                502,
                                (
                                    "Source is presenting a browser/anti-bot challenge. "
                                    "A stronger fetch engine may be required."
                                ),
                            )
                        detail = body.decode(
                            response.encoding or "utf-8",
                            errors="replace",
                        )[:240]
                        raise HTTPException(
                            502,
                            (
                                f"Source returned HTTP {response.status_code}"
                                + (f": {detail}" if detail else ".")
                            ),
                        )

                    content = await _read_bounded(
                        response,
                        max_bytes=max_bytes,
                    )

                    content_type = _normalize_content_type(response.headers)
                    content_type = _validate_payload(
                        content=content,
                        content_type=content_type,
                        expected=expected,
                        max_bytes=max_bytes,
                    )

                    if expected == "html" and _looks_like_browser_gate(content):
                        raise HTTPException(
                            502,
                            "Source returned a browser/anti-bot gate instead of the page.",
                        )
                    if expected == "html" and _looks_like_js_shell(content):
                        raise HTTPException(
                            502,
                            "Source returned a JavaScript application shell without usable rendered content.",
                        )

                    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

                    log.info(
                        (
                            "fetch_ok engine=httpx url=%s final_url=%s status=%s bytes=%s "
                            "redirects=%s attempt=%s duration_ms=%s"
                        ),
                        normalized,
                        current,
                        response.status_code,
                        len(content),
                        len(redirects),
                        attempt,
                        elapsed_ms,
                    )

                    return FetchResult(
                        requested_url=normalized,
                        final_url=current,
                        status_code=response.status_code,
                        content_type=content_type,
                        content=content,
                        redirects=redirects,
                        resolved_addresses=addresses,
                        elapsed_ms=elapsed_ms,
                        engine="httpx",
                    )

            if attempt < settings.scraper_fetch_attempts:
                await asyncio.sleep(_retry_delay(retry_response, attempt))
                continue

        except HTTPException:
            raise
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
        ) as exc:
            last_error = exc

            if attempt < settings.scraper_fetch_attempts:
                delay = _retry_delay(None, attempt)
                log.warning(
                    "fetch_retry engine=httpx url=%s attempt=%s error=%s delay=%s",
                    normalized,
                    attempt,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

        break

    if isinstance(last_error, HTTPException):
        raise last_error

    if last_error is not None:
        raise HTTPException(
            502,
            (
                "Unable to connect to source after retries: "
                f"{type(last_error).__name__}."
            ),
        )

    raise HTTPException(502, "Unable to fetch source.")


def _httpx_cookie_dict(client: httpx.AsyncClient) -> dict[str, str]:
    try:
        return {cookie.name: cookie.value for cookie in client.cookies.jar}
    except Exception:
        return {}


def _browser_cookie_list(client: httpx.AsyncClient, target_url: str) -> list[dict[str, object]]:
    cookies: list[dict[str, object]] = []
    parsed = urlparse(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else target_url
    try:
        for cookie in client.cookies.jar:
            item: dict[str, object] = {
                "name": cookie.name,
                "value": cookie.value,
            }
            domain = (cookie.domain or "").lstrip(".")
            if domain:
                item["domain"] = domain
                item["path"] = cookie.path or "/"
            else:
                item["url"] = origin
            if bool(cookie.secure):
                item["secure"] = True
            cookies.append(item)
    except Exception:
        return []
    return cookies


def _sync_response_cookies(client: httpx.AsyncClient, cookies: object) -> None:
    try:
        if isinstance(cookies, dict):
            for key, value in cookies.items():
                client.cookies.set(str(key), str(value))
            return
        if isinstance(cookies, (tuple, list)):
            for item in cookies:
                if isinstance(item, dict):
                    name = item.get("name")
                    value = item.get("value")
                    if name is not None and value is not None:
                        client.cookies.set(str(name), str(value))
    except Exception:
        # Cookie synchronization is a compatibility aid; it must never turn a
        # successful fetch into a failed scrape.
        log.debug("Unable to synchronize fallback cookies", exc_info=True)


async def _fetch_with_scrapling_http(
    client: httpx.AsyncClient,
    *,
    normalized: str,
    addresses: list[str],
    accept: str,
    max_bytes: int,
    referer: str | None,
    expected: str,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    started = time.perf_counter()
    try:
        from scrapling.fetchers import AsyncFetcher
    except Exception as exc:  # pragma: no cover - container dependency gate
        raise HTTPException(502, f"Scrapling HTTP fallback unavailable: {type(exc).__name__}.")

    headers = browser_headers(accept=accept, referer=referer, extra_headers=extra_headers)
    # curl_cffi generates a browser-consistent User-Agent/TLS fingerprint when
    # impersonation is enabled. Do not override it with the fixed compatibility UA.
    headers.pop("User-Agent", None)

    try:
        response = await AsyncFetcher.get(
            normalized,
            headers=headers,
            cookies=_httpx_cookie_dict(client) or None,
            stealthy_headers=True,
            impersonate=settings.scraper_scrapling_impersonate,
            follow_redirects="safe",
            max_redirects=settings.scraper_max_redirects,
            timeout=settings.scraper_timeout_seconds,
            retries=max(1, settings.scraper_fetch_attempts - 1),
            retry_delay=settings.scraper_retry_base_seconds,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Scrapling HTTP fallback failed: {type(exc).__name__}: {exc}")

    status = int(getattr(response, "status", 0) or 0)
    final_url = str(getattr(response, "url", normalized) or normalized)
    await validate_public_url(final_url)

    content = bytes(getattr(response, "body", b""))
    content_type = _normalize_content_type(getattr(response, "headers", {}))

    if status >= 400:
        detail = content[:240].decode("utf-8", errors="replace")
        raise HTTPException(
            502,
            f"Scrapling HTTP fallback returned HTTP {status}" + (f": {detail}" if detail else "."),
        )

    content_type = _validate_payload(
        content=content,
        content_type=content_type,
        expected=expected,
        max_bytes=max_bytes,
    )

    if expected == "html" and _looks_like_browser_gate(content):
        raise HTTPException(502, "Scrapling HTTP fallback still received a browser/anti-bot gate.")
    if expected == "html" and _looks_like_js_shell(content):
        raise HTTPException(502, "Scrapling HTTP fallback received an unrendered JavaScript application shell.")

    history = []
    for item in list(getattr(response, "history", []) or []):
        value = str(getattr(item, "url", "") or "")
        if value:
            history.append(value)

    _sync_response_cookies(client, getattr(response, "cookies", None))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(
        "fetch_ok engine=scrapling-http url=%s final_url=%s status=%s bytes=%s redirects=%s duration_ms=%s",
        normalized,
        final_url,
        status,
        len(content),
        len(history),
        elapsed_ms,
    )
    return FetchResult(
        requested_url=normalized,
        final_url=final_url,
        status_code=status,
        content_type=content_type,
        content=content,
        redirects=history,
        resolved_addresses=addresses,
        elapsed_ms=elapsed_ms,
        engine="scrapling-http",
    )


async def _browser_page_setup(page) -> None:
    """Block browser subrequests that resolve to local/private addresses."""
    validated_hosts: set[tuple[str, str, int | None]] = set()
    rejected_hosts: set[tuple[str, str, int | None]] = set()

    async def guard(route) -> None:
        request_url = str(route.request.url)
        parsed = urlparse(request_url)
        if parsed.scheme not in {"http", "https"}:
            await route.continue_()
            return

        key = (parsed.scheme, (parsed.hostname or "").lower(), parsed.port)
        if key in rejected_hosts:
            await route.abort()
            return
        if key not in validated_hosts:
            try:
                await validate_public_url(request_url)
            except Exception:
                rejected_hosts.add(key)
                log.warning("browser_subrequest_blocked url=%s", request_url)
                await route.abort()
                return
            validated_hosts.add(key)
        await route.continue_()

    await page.route("**/*", guard)


async def _browser_autoscroll(page) -> None:
    stable_rounds = 0
    previous_height = -1
    for _ in range(max(1, settings.scraper_browser_autoscroll_steps)):
        try:
            height = int(await page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"))
            await page.evaluate("window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight))")
            await page.wait_for_timeout(max(50, settings.scraper_browser_scroll_delay_ms))
        except Exception:
            break

        if height == previous_height:
            stable_rounds += 1
            if stable_rounds >= 2:
                break
        else:
            stable_rounds = 0
        previous_height = height



def _captured_xhr_url_inventory(response: object, *, host: str) -> list[str]:
    """Extract a bounded URL inventory from same-host XHR/fetch bodies."""
    found: list[str] = []
    seen: set[str] = set()
    responses = list(getattr(response, "captured_xhr", []) or [])
    max_responses = max(0, int(settings.scraper_browser_capture_xhr_max_responses))
    max_body = max(0, int(settings.scraper_browser_capture_xhr_max_body_bytes))
    # Match normal or JSON-escaped absolute/protocol-relative/relative URLs.
    url_re = re.compile(r"(?:(?:https?:)?(?:\\?/\\?/)[^\s\"'`<>]+|(?:\\?/)[A-Za-z0-9_?&=%+.,~:@!$'()*;/-]+)", re.I)

    for xhr in responses[:max_responses]:
        try:
            body = bytes(getattr(xhr, "body", b""))
        except Exception:
            continue
        if not body or len(body) > max_body:
            continue
        text = body.decode("utf-8", errors="replace")
        for match in url_re.finditer(text):
            raw = html_lib.unescape(match.group(0)).replace("\\/", "/")
            if raw.startswith("//"):
                raw = "https:" + raw
            elif raw.startswith("/"):
                raw = "https://" + host + raw
            try:
                parsed = urlparse(raw)
            except Exception:
                continue
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            if raw not in seen:
                seen.add(raw)
                found.append(raw)
                if len(found) >= 512:
                    return found
    return found


def _append_captured_urls_to_html(content: bytes, urls: list[str]) -> bytes:
    if not urls:
        return content
    payload = json.dumps({"urls": urls}, ensure_ascii=False, separators=(",", ":"))
    tag = ("<script type=\"application/json\" id=\"mreader-captured-xhr-urls\">" + payload + "</script>").encode("utf-8")
    lower = content.lower()
    pos = lower.rfind(b"</body>")
    if pos >= 0:
        return content[:pos] + tag + content[pos:]
    return content + tag

async def _fetch_with_scrapling_browser_local(
    client: httpx.AsyncClient,
    *,
    normalized: str,
    addresses: list[str],
    accept: str,
    max_bytes: int,
    referer: str | None,
    browser_scroll: bool,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    started = time.perf_counter()
    try:
        from scrapling.fetchers import StealthyFetcher
    except Exception as exc:  # pragma: no cover - container dependency gate
        raise HTTPException(502, f"Scrapling browser fallback unavailable: {type(exc).__name__}.")

    browser_extra_headers = browser_headers(
        accept=accept, referer=referer, extra_headers=extra_headers
    )
    # Let Patchright/Scrapling own a browser-consistent User-Agent.
    browser_extra_headers.pop("User-Agent", None)

    parsed_host = (urlparse(normalized).hostname or "").lower()
    capture_pattern = None
    if settings.scraper_browser_capture_xhr_enabled and parsed_host:
        capture_pattern = rf"^https?://{re.escape(parsed_host)}/.*"

    async with _BROWSER_SEMAPHORE:
        try:
            response = await StealthyFetcher.async_fetch(
                normalized,
                headless=True,
                timeout=settings.scraper_browser_timeout_ms,
                wait=settings.scraper_browser_wait_ms,
                load_dom=True,
                network_idle=False,
                disable_resources=False,
                block_ads=settings.scraper_browser_block_ads,
                solve_cloudflare=settings.scraper_browser_solve_cloudflare,
                block_webrtc=True,
                hide_canvas=True,
                allow_webgl=True,
                google_search=not bool(referer),
                extra_headers=browser_extra_headers,
                cookies=_browser_cookie_list(client, normalized) or None,
                page_setup=_browser_page_setup,
                page_action=_browser_autoscroll if browser_scroll else None,
                capture_xhr=capture_pattern,
                retries=1,
                retry_delay=settings.scraper_retry_base_seconds,
            )
        except Exception as exc:
            raise HTTPException(502, f"Scrapling browser fallback failed: {type(exc).__name__}: {exc}")

    status = int(getattr(response, "status", 0) or 0)
    final_url = str(getattr(response, "url", normalized) or normalized)
    await validate_public_url(final_url)
    content = bytes(getattr(response, "body", b""))
    if settings.scraper_browser_capture_xhr_enabled and parsed_host:
        captured_urls = _captured_xhr_url_inventory(response, host=parsed_host)
        content = _append_captured_urls_to_html(content, captured_urls)
    content_type = _normalize_content_type(getattr(response, "headers", {}))

    if status >= 400:
        detail = content[:240].decode("utf-8", errors="replace")
        raise HTTPException(
            502,
            f"Scrapling browser fallback returned HTTP {status}" + (f": {detail}" if detail else "."),
        )

    content_type = _validate_payload(
        content=content,
        content_type=content_type,
        expected="html",
        max_bytes=max_bytes,
    )
    if _looks_like_browser_gate(content):
        raise HTTPException(
            502,
            "Browser fallback still received a verification/challenge page. "
            "Interactive challenge solving is disabled by default.",
        )

    _sync_response_cookies(client, getattr(response, "cookies", None))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(
        "fetch_ok engine=scrapling-browser url=%s final_url=%s status=%s bytes=%s duration_ms=%s scroll=%s",
        normalized,
        final_url,
        status,
        len(content),
        elapsed_ms,
        browser_scroll,
    )
    return FetchResult(
        requested_url=normalized,
        final_url=final_url,
        status_code=status,
        content_type=content_type,
        content=content,
        redirects=[],
        resolved_addresses=addresses,
        elapsed_ms=elapsed_ms,
        engine="scrapling-browser",
    )


async def _fetch_with_scrapling_browser_remote(
    client: httpx.AsyncClient,
    *,
    normalized: str,
    addresses: list[str],
    accept: str,
    max_bytes: int,
    referer: str | None,
    browser_scroll: bool,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    remote_url = settings.scraper_browser_remote_url.strip().rstrip("/")
    if not remote_url:
        raise HTTPException(
            502,
            "Browser worker is not configured. Start the optional scraper-browser worker when a source requires JavaScript rendering.",
        )

    payload = {
        "url": normalized,
        "accept": accept,
        "max_bytes": max_bytes,
        "referer": referer,
        "browser_scroll": browser_scroll,
        "extra_headers": extra_headers or {},
        "cookies": _browser_cookie_list(client, normalized),
    }
    timeout_seconds = max(10.0, (float(settings.scraper_browser_timeout_ms) / 1000.0) + 15.0)
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as remote:
            response = await remote.post(f"{remote_url}/fetch", json=payload)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        raise HTTPException(
            502,
            f"Browser worker unavailable: {type(exc).__name__}. Start it with scripts/scraper-browser.sh enable <mode>.",
        ) from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        try:
            parsed = response.json()
            detail = str(parsed.get("detail") or parsed.get("error") or detail)
        except Exception:
            pass
        raise HTTPException(502, f"Browser worker failed: {detail}")

    try:
        data = response.json()
        content = base64.b64decode(str(data["content_b64"]), validate=True)
        final_url = str(data.get("final_url") or normalized)
        status = int(data.get("status_code") or 200)
        content_type = str(data.get("content_type") or "text/html")
    except Exception as exc:
        raise HTTPException(502, f"Browser worker returned an invalid response: {type(exc).__name__}.") from exc

    await validate_public_url(final_url)
    content_type = _validate_payload(
        content=content,
        content_type=content_type,
        expected="html",
        max_bytes=max_bytes,
    )
    if _looks_like_browser_gate(content):
        raise HTTPException(
            502,
            "Browser fallback still received a verification/challenge page. Interactive challenge solving is disabled by default.",
        )

    _sync_response_cookies(client, data.get("cookies"))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    log.info(
        "fetch_ok engine=scrapling-browser-remote url=%s final_url=%s status=%s bytes=%s duration_ms=%s scroll=%s",
        normalized,
        final_url,
        status,
        len(content),
        elapsed_ms,
        browser_scroll,
    )
    return FetchResult(
        requested_url=normalized,
        final_url=final_url,
        status_code=status,
        content_type=content_type,
        content=content,
        redirects=[],
        resolved_addresses=addresses,
        elapsed_ms=elapsed_ms,
        engine="scrapling-browser",
    )


async def _fetch_with_scrapling_browser(
    client: httpx.AsyncClient,
    *,
    normalized: str,
    addresses: list[str],
    accept: str,
    max_bytes: int,
    referer: str | None,
    browser_scroll: bool,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    if settings.scraper_browser_remote_url.strip():
        return await _fetch_with_scrapling_browser_remote(
            client,
            normalized=normalized,
            addresses=addresses,
            accept=accept,
            max_bytes=max_bytes,
            referer=referer,
            browser_scroll=browser_scroll,
            extra_headers=extra_headers,
        )
    if os.getenv("MREADER_BROWSER_LOCAL_RUNTIME", "").strip().lower() in {"1", "true", "yes", "on"}:
        return await _fetch_with_scrapling_browser_local(
            client,
            normalized=normalized,
            addresses=addresses,
            accept=accept,
            max_bytes=max_bytes,
            referer=referer,
            browser_scroll=browser_scroll,
            extra_headers=extra_headers,
        )
    raise HTTPException(
        502,
        "Browser fallback is not available in the lean scraper image. Start the optional scraper-browser worker when needed.",
    )


def _should_escalate(exc: HTTPException) -> bool:
    if exc.status_code in {400, 401, 404, 413, 415, 422}:
        return False
    detail = str(exc.detail).lower()
    if "private" in detail or "local hosts" in detail or "only http/https" in detail:
        return False
    return True


async def fetch_external(
    client: httpx.AsyncClient,
    *,
    url: str,
    accept: str,
    max_bytes: int,
    referer: str | None = None,
    expected: str = "any",
    force_browser: bool = False,
    browser_scroll: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    normalized, addresses = await resolve_public_addresses(url)

    if force_browser:
        if expected != "html":
            raise HTTPException(400, "Browser forcing is supported only for HTML fetches.")
        if not browser_fallback_available():
            raise HTTPException(
                502,
                "Browser fallback is unavailable. Enable the optional scraper-browser worker for JavaScript-rendered sources.",
            )
        result = await _fetch_with_scrapling_browser(
            client, normalized=normalized, addresses=addresses, accept=accept,
            max_bytes=max_bytes, referer=referer, browser_scroll=browser_scroll,
            extra_headers=extra_headers,
        )
        await _remember_engine(result.final_url, result.engine)
        return result

    preferred = await _get_engine_affinity(normalized)
    if preferred == "scrapling-browser" and expected == "html" and browser_fallback_available():
        try:
            return await _fetch_with_scrapling_browser(
                client, normalized=normalized, addresses=addresses, accept=accept,
                max_bytes=max_bytes, referer=referer, browser_scroll=browser_scroll,
                extra_headers=extra_headers,
            )
        except HTTPException as exc:
            log.warning("fetch_affinity_fallback engine=scrapling-browser url=%s reason=%s", normalized, exc.detail)
    elif preferred == "scrapling-http" and settings.scraper_scrapling_enabled:
        try:
            return await _fetch_with_scrapling_http(
                client, normalized=normalized, addresses=addresses, accept=accept,
                max_bytes=max_bytes, referer=referer, expected=expected,
                extra_headers=extra_headers,
            )
        except HTTPException as exc:
            log.warning("fetch_affinity_fallback engine=scrapling-http url=%s reason=%s", normalized, exc.detail)

    try:
        return await _fetch_external_httpx(
            client, normalized=normalized, addresses=addresses, accept=accept,
            max_bytes=max_bytes, referer=referer, expected=expected,
            extra_headers=extra_headers,
        )
    except HTTPException as first_error:
        if not settings.scraper_scrapling_enabled or not _should_escalate(first_error):
            raise
        log.warning(
            "fetch_escalate from=httpx to=scrapling-http url=%s reason=%s",
            normalized, first_error.detail,
        )

    try:
        result = await _fetch_with_scrapling_http(
            client, normalized=normalized, addresses=addresses, accept=accept,
            max_bytes=max_bytes, referer=referer, expected=expected,
            extra_headers=extra_headers,
        )
        await _remember_engine(result.final_url, result.engine)
        return result
    except HTTPException as second_error:
        if (
            expected != "html"
            or not browser_fallback_available()
            or not _should_escalate(second_error)
        ):
            raise
        log.warning(
            "fetch_escalate from=scrapling-http to=scrapling-browser url=%s reason=%s",
            normalized, second_error.detail,
        )
        result = await _fetch_with_scrapling_browser(
            client, normalized=normalized, addresses=addresses, accept=accept,
            max_bytes=max_bytes, referer=referer, browser_scroll=browser_scroll,
            extra_headers=extra_headers,
        )
        await _remember_engine(result.final_url, result.engine)
        return result


async def fetch_html(
    client: httpx.AsyncClient,
    *,
    url: str,
    max_bytes: int | None = None,
    referer: str | None = None,
    force_browser: bool = False,
    browser_scroll: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    return await fetch_external(
        client,
        url=url,
        accept=(
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        max_bytes=max_bytes or settings.scraper_max_response_bytes,
        referer=referer,
        expected="html",
        force_browser=force_browser,
        browser_scroll=browser_scroll,
        extra_headers=extra_headers,
    )


async def fetch_image(
    client: httpx.AsyncClient,
    *,
    url: str,
    referer: str | None,
    max_bytes: int,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    # Browser loading is intentionally not used for raw images. HTTPX keeps the
    # transfer bounded; the curl_cffi fallback is enough for most hotlink/TLS
    # fingerprint cases without launching Chromium per page.
    if not settings.scraper_scrapling_image_fallback_enabled:
        normalized, addresses = await resolve_public_addresses(url)
        return await _fetch_external_httpx(
            client,
            normalized=normalized,
            addresses=addresses,
            accept=(
                "image/avif,image/webp,image/apng,"
                "image/svg+xml,image/*,*/*;q=0.8"
            ),
            max_bytes=max_bytes,
            referer=referer,
            expected="image",
            extra_headers=extra_headers,
        )

    return await fetch_external(
        client,
        url=url,
        accept=(
            "image/avif,image/webp,image/apng,"
            "image/svg+xml,image/*,*/*;q=0.8"
        ),
        max_bytes=max_bytes,
        referer=referer,
        expected="image",
        extra_headers=extra_headers,
    )
