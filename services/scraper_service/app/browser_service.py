from __future__ import annotations

import base64
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.fetcher import (
    _fetch_with_scrapling_browser_local,
    _sync_response_cookies,
)
from app.security import resolve_public_addresses


app = FastAPI(title="MReader Scraper Browser Worker", version="1.3.0-rc4.84")


class BrowserFetchRequest(BaseModel):
    url: str
    accept: str = "text/html,application/xhtml+xml"
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=32 * 1024 * 1024)
    referer: str | None = None
    browser_scroll: bool = False
    extra_headers: dict[str, str] = Field(default_factory=dict)
    cookies: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "scraper-browser"}


@app.post("/fetch")
async def fetch(request: BrowserFetchRequest) -> dict[str, Any]:
    # Re-resolve and re-validate inside the browser worker. The caller is an
    # internal scraper process, but the target URL still originates from user/
    # admin supplied scrape input and must never bypass the SSRF guard.
    normalized, addresses = await resolve_public_addresses(request.url)

    async with httpx.AsyncClient(follow_redirects=False) as client:
        _sync_response_cookies(client, request.cookies)
        result = await _fetch_with_scrapling_browser_local(
            client,
            normalized=normalized,
            addresses=addresses,
            accept=request.accept,
            max_bytes=request.max_bytes,
            referer=request.referer,
            browser_scroll=request.browser_scroll,
            extra_headers=request.extra_headers,
        )

        cookies: list[dict[str, str]] = []
        try:
            for cookie in client.cookies.jar:
                cookies.append({"name": str(cookie.name), "value": str(cookie.value)})
        except Exception:
            cookies = []

    if result.status_code >= 400:
        raise HTTPException(502, f"Browser fetch returned HTTP {result.status_code}.")

    return {
        "requested_url": result.requested_url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "content_b64": base64.b64encode(result.content).decode("ascii"),
        "elapsed_ms": result.elapsed_ms,
        "engine": result.engine,
        "cookies": cookies,
    }
