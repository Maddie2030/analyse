from __future__ import annotations

import httpx
from fastapi import HTTPException

from app.config import settings


def _catalog_headers(actor_id: str) -> dict[str, str]:
    token = settings.catalog_internal_token.strip()
    if not token:
        raise HTTPException(503, "Catalog internal transport is not configured.")
    return {
        "Content-Type": "application/json",
        "X-MReader-Requesting-Actor-ID": str(actor_id),
        "X-MReader-Internal-Token": token,
    }


async def ensure_catalog_series(
    client: httpx.AsyncClient,
    *,
    title: str,
    slug: str,
    description: str | None,
    status: str,
    genre_names: list[str],
    tag_names: list[str],
    requesting_actor_id: str,
) -> dict:
    base = settings.catalog_internal_url.rstrip("/")
    try:
        response = await client.post(
            f"{base}/internal/v1/catalog/series",
            json={
                "title": title,
                "slug": slug,
                "description": description,
                "cover_image_path": None,
                "status": status,
                "genre_names": list(genre_names),
                "tag_names": list(tag_names),
            },
            headers=_catalog_headers(requesting_actor_id),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Catalog series creation is temporarily unavailable.") from exc
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"Catalog series creation failed: {response.text[:1000]}",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Catalog returned an invalid series response.") from exc
    if not isinstance(body, dict) or not body.get("id"):
        raise HTTPException(502, "Catalog returned an invalid series response.")
    return body
