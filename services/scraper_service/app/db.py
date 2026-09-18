from __future__ import annotations

import json
from typing import Any

import asyncpg


def _json_encoder(value: Any) -> str:
    # Existing scraper queries commonly pass json.dumps(...) into $n::jsonb.
    # Preserve valid JSON strings while also supporting direct dict/list values.
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _json_decoder(value: str):
    return json.loads(value)


async def configure_connection(
    connection: asyncpg.Connection,
) -> None:
    """
    asyncpg returns json/jsonb as strings unless a codec is registered.

    The scraper service API and workers expect dict/list values for fields such
    as scraper_drafts.pages, chapter_data, series_data, batch source_files, and
    full-series draft genres/tags/pages.
    """
    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            schema="pg_catalog",
            encoder=_json_encoder,
            decoder=_json_decoder,
            format="text",
        )
