from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import httpx


@dataclass(frozen=True)
class CatalogTransportCodes:
    unavailable: str
    rejected: str
    invalid: str


class CatalogTransportError(RuntimeError):
    pass


async def request_catalog_json(
    *,
    method: str,
    path: str,
    payload: dict[str, Any],
    actor_id: str | None,
    codes: CatalogTransportCodes,
) -> dict[str, Any]:
    base = os.getenv("CATALOG_INTERNAL_URL", "http://catalog-admin:8080").strip().rstrip("/")
    if not base:
        raise CatalogTransportError(codes.unavailable)

    headers = {"Content-Type": "application/json"}
    if actor_id:
        headers["X-MReader-Requesting-Actor-ID"] = str(actor_id)
    token = os.getenv("CATALOG_INTERNAL_TOKEN", "").strip()
    if not token:
        raise CatalogTransportError(codes.unavailable)
    headers["X-MReader-Internal-Token"] = token

    timeout = float(os.getenv("CATALOG_PUBLICATION_TIMEOUT_SECONDS", "20"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{base}{path}",
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise CatalogTransportError(codes.unavailable) from exc

    if not 200 <= response.status_code < 300:
        code = codes.rejected
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("code"), str):
                code = body["code"]
        except (TypeError, ValueError):
            pass
        raise CatalogTransportError(code)

    try:
        body = response.json()
    except ValueError as exc:
        raise CatalogTransportError(codes.invalid) from exc
    if not isinstance(body, dict):
        raise CatalogTransportError(codes.invalid)
    return body
