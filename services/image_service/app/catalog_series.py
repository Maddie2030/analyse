from __future__ import annotations

from app.catalog_transport import (
    CatalogTransportCodes,
    CatalogTransportError,
    request_catalog_json,
)


class CatalogSeriesMutationError(RuntimeError):
    pass


async def set_catalog_series_cover(
    *,
    series_id: str,
    actor_id: str | None,
    cover_image_path: str | None,
    media_generation: int,
) -> dict:
    try:
        body = await request_catalog_json(
            method="PUT",
            path=f"/internal/v1/catalog/series/{series_id}/cover",
            payload={
                "cover_image_path": cover_image_path,
                "media_generation": int(media_generation),
            },
            actor_id=actor_id,
            codes=CatalogTransportCodes(
                unavailable="catalog_series_cover_unavailable",
                rejected="catalog_series_cover_rejected",
                invalid="invalid_catalog_series_response",
            ),
        )
    except CatalogTransportError as exc:
        raise CatalogSeriesMutationError(str(exc)) from exc
    if str(body.get("id") or "") != str(series_id):
        raise CatalogSeriesMutationError("invalid_catalog_series_response")
    return body
