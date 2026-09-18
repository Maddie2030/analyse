from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from http.cookies import SimpleCookie
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


SENSITIVE_KEYS = {
    "password",
    "turnstile_token",
    "cookie",
    "authorization",
    "token",
    "old_token",
    "access_token",
    "refresh_token",
    "chapter_token",
    "session_token",
    "csrf_token",
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or lowered.endswith("_token")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***" if _is_sensitive_key(str(key)) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return _redact_url(value)
    return value




def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = [
            (key, "***" if _is_sensitive_key(key) else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return url


_SENSITIVE_TEXT_QUERY = re.compile(
    r"(?i)(?P<key>(?:old_|access_|refresh_|chapter_|session_|csrf_)?token|password|authorization)=(?P<value>[^&\s\"']+)"
)
_SENSITIVE_TEXT_JSON = re.compile(
    r'(?i)(?P<prefix>["\'](?:password|authorization|(?:old_|access_|refresh_|chapter_|session_|csrf_)?token)["\']\s*:\s*["\'])(?P<value>[^"\']+)(?P<suffix>["\'])'
)


def _redact_text(text: str) -> str:
    redacted = _SENSITIVE_TEXT_QUERY.sub(lambda match: f"{match.group('key')}=***", text)
    return _SENSITIVE_TEXT_JSON.sub(
        lambda match: f"{match.group('prefix')}***{match.group('suffix')}",
        redacted,
    )


def safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


class ApiSession(requests.Session):
    def __init__(self, base_url: str, exchange_log: Path | None = None):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.exchange_log = exchange_log

    def _replay_secure_cookie_for_local_http(self, response: requests.Response, target: str) -> None:
        """Replay Secure auth cookies only inside the Docker diagnostic harness.

        The real RC4.45 deployment can legitimately run with COOKIE_SECURE=true
        because public access is HTTPS. The Docker test container reaches the same
        gateway through host.docker.internal over plain HTTP, and requests will
        correctly refuse to resend a Secure cookie on that transport. Rather than
        weakening the application cookie policy, the harness copies only cookies
        returned by the application into its private session jar as host-only
        non-Secure cookies for subsequent local diagnostic requests.
        """
        if not target.startswith("http://"):
            return
        if os.getenv("MREADER_TEST_HTTP_COOKIE_REPLAY", "true").lower() not in {"1", "true", "yes", "on"}:
            return
        header = response.headers.get("Set-Cookie")
        if not header:
            return

        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except Exception:
            return

        for name, morsel in parsed.items():
            if not morsel["secure"]:
                continue
            # Remove every copy of the same cookie name first, including the
            # Secure copy requests extracted from the response. This keeps
            # logout/rotation deterministic and prevents duplicate Cookie fields.
            for existing in list(self.cookies):
                if existing.name == name:
                    try:
                        self.cookies.clear(existing.domain, existing.path, existing.name)
                    except KeyError:
                        pass

            max_age = (morsel["max-age"] or "").strip()
            if morsel.value == "" or max_age == "0":
                continue

            self.cookies.set(
                name,
                morsel.value,
                path=morsel["path"] or "/",
                secure=False,
            )

    def request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        target = url if url.startswith("http") else f"{self.base_url}{url}"
        started = time.perf_counter()
        response = super().request(method, target, **kwargs)
        self._replay_secure_cookie_for_local_http(response, target)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        if self.exchange_log is not None:
            payload = {
                "method": method.upper(),
                "url": _redact_url(target),
                "status": response.status_code,
                "duration_ms": duration_ms,
                "request_json": _redact(kwargs.get("json")),
                "request_params": _redact(kwargs.get("params")),
                "response_json": _redact(safe_json(response)),
                "response_text": (
                    None
                    if safe_json(response) is not None
                    else _redact_text(response.text[:2000])
                ),
            }
            self.exchange_log.parent.mkdir(parents=True, exist_ok=True)
            with self.exchange_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, default=str) + "\n")

        return response

    def get_json(self, url: str, **kwargs) -> Any:
        response = self.get(url, **kwargs)
        assert_status(response, 200)
        return response.json()


class JourneyRecorder:
    def __init__(self, path: Path, nodeid: str):
        self.path = path
        self.nodeid = nodeid

    def record(
        self,
        action: str,
        *,
        intended: str,
        observed: Any = None,
        expected: Any = None,
        passed: bool,
    ) -> None:
        payload = {
            "nodeid": self.nodeid,
            "action": action,
            "intended": intended,
            "expected": _redact(expected),
            "observed": _redact(observed),
            "passed": bool(passed),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")

    def assert_true(
        self,
        action: str,
        condition: bool,
        *,
        intended: str,
        observed: Any = None,
    ) -> None:
        self.record(
            action,
            intended=intended,
            observed=observed,
            expected=True,
            passed=bool(condition),
        )
        assert condition, f"{action}: {intended}; observed={observed!r}"

    def assert_equal(
        self,
        action: str,
        observed: Any,
        expected: Any,
        *,
        intended: str,
    ) -> None:
        passed = observed == expected
        self.record(
            action,
            intended=intended,
            observed=observed,
            expected=expected,
            passed=passed,
        )
        assert passed, (
            f"{action}: {intended}; expected={expected!r}, observed={observed!r}"
        )


def assert_status(response: requests.Response, expected: int | set[int]) -> None:
    allowed = {expected} if isinstance(expected, int) else expected
    assert response.status_code in allowed, (
        f"{response.request.method} {response.url}: "
        f"expected {sorted(allowed)}, got {response.status_code}; "
        f"body={response.text[:1000]}"
    )


def wait_until(
    fn,
    *,
    timeout: float = 60.0,
    interval: float = 1.0,
    description: str = "condition",
):
    deadline = time.time() + timeout
    last = None

    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)

    raise AssertionError(f"Timed out waiting for {description}. Last value: {last!r}")




def zip_image_chapter(image_bytes: bytes) -> bytes:
    """Build the smallest deterministic multi-page image archive used by media tests."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("001.png", image_bytes)
        archive.writestr("002.png", image_bytes)
    return buffer.getvalue()


def wait_series_draft_terminal(
    session: ApiSession,
    draft_id: str,
    *,
    timeout: float = 180.0,
):
    terminal = {"published", "published_partial", "failed", "duplicate", "cancelled"}
    path = f"/api/scraper/series-drafts/{draft_id}"
    return wait_until(
        lambda: draft
        if (draft := session.get_json(path, timeout=10)).get("workflow_status") in terminal
        else None,
        timeout=timeout,
        interval=1,
        description=f"series draft {draft_id} terminal state",
    )


def wait_media_job(
    session: ApiSession,
    job_id: str,
    *,
    timeout: float = 180.0,
):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = session.get(f"/api/upload/jobs/{job_id}", timeout=10)
        assert_status(response, 200)
        last = response.json()
        if last.get("status") in {"completed", "failed"}:
            return last
        time.sleep(1)
    raise AssertionError(f"Timed out waiting for media job {job_id}. Last value: {last!r}")


@dataclass
class Identity:
    user_id: str
    username: str
    email: str
    password: str
    session: ApiSession
