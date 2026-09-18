from __future__ import annotations

from decimal import Decimal
from typing import Any

from shared.catalog_publication_contract import replay_receipt, seal_command

from app.catalog_transport import (
    CatalogTransportCodes,
    CatalogTransportError,
    request_catalog_json,
)


class CatalogPublicationError(RuntimeError):
    pass


def canonical_chapter_number(value: Decimal) -> str:
    if not value.is_finite() or value < 0 or value > Decimal("999999.99"):
        raise ValueError("chapter_number is outside the publication contract")
    quantized = value.quantize(Decimal("0.01"))
    if quantized != value:
        raise ValueError("chapter_number supports at most two decimal places")
    return format(quantized, ".2f")


def _asset(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "image_path": str(value["image_path"]),
        "width": int(value["width"]),
        "height": int(value["height"]),
        "size_bytes": int(value["size_bytes"]),
        "sha256": str(value["sha256"]),
    }


def build_manifest(
    *,
    series_id: str,
    series_slug: str,
    chapter_slug: str,
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    result_pages: list[dict[str, Any]] = []
    for page in pages:
        responsive = page.get("responsive")
        result_pages.append(
            {
                "page_number": int(page["page_number"]),
                **_asset(page),
                "encoding_version": int(page["encoding_version"]),
                "encoding_rows": int(page["encoding_rows"]),
                "encoding_columns": int(page["encoding_columns"]),
                "encoding_seed": str(page["encoding_seed"]),
                "responsive": _asset(responsive) if responsive else None,
            }
        )
    return {
        "schema_version": 1,
        "series_id": str(series_id),
        "series_slug": str(series_slug),
        "chapter_slug": str(chapter_slug),
        "pages": result_pages,
    }


def build_publication_command(
    *,
    idempotency_key: str,
    operation_id: str,
    actor_id: str,
    source_revision: int,
    ingestion_generation: int,
    media_operation_id: str,
    media_generation: int,
    chapter_id: str | None,
    expected_revision: int,
    chapter_number: Decimal,
    title: str | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    return seal_command(
        {
            "schema_version": 1,
            "idempotency_key": str(idempotency_key),
            "operation_id": str(operation_id),
            "actor_id": str(actor_id),
            "source_revision": int(source_revision),
            "ingestion_generation": int(ingestion_generation),
            "media_operation_id": str(media_operation_id),
            "media_generation": int(media_generation),
            "chapter_id": str(chapter_id) if chapter_id else None,
            "expected_revision": int(expected_revision),
            "chapter_number": canonical_chapter_number(chapter_number),
            "title": title,
            "manifest": manifest,
        }
    )


async def publish_catalog_command(command: dict[str, Any]) -> dict[str, Any]:
    try:
        receipt = await request_catalog_json(
            method="POST",
            path="/internal/v1/catalog/publications",
            payload=command,
            actor_id=str(command["actor_id"]),
            codes=CatalogTransportCodes(
                unavailable="catalog_publication_unavailable",
                rejected="catalog_publication_rejected",
                invalid="invalid_catalog_receipt",
            ),
        )
    except CatalogTransportError as exc:
        raise CatalogPublicationError(str(exc)) from exc
    try:
        return replay_receipt(command, receipt, actor_id=str(command["actor_id"]))
    except ValueError as exc:
        raise CatalogPublicationError(str(exc)) from exc
