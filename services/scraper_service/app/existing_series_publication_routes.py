from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request

from app.config import settings
from app.drafts import (
    ExistingSeriesPublishRequest,
    publish_existing_series_draft,
    reconcile_existing_series_draft,
)
from app.security import require_admin


router = APIRouter()


@dataclass(frozen=True)
class ExistingSeriesRouteContext:
    pool: Any
    client: httpx.AsyncClient
    session_id: str | None
    actor_id: str


async def existing_series_route_context(
    request: Request,
    _admin: dict = Depends(require_admin),
) -> ExistingSeriesRouteContext:
    return ExistingSeriesRouteContext(
        pool=request.app.state.db,
        client=request.app.state.http,
        session_id=request.cookies.get(settings.SESSION_COOKIE_NAME),
        actor_id=str(_admin["user_id"]),
    )


@router.get("/api/scraper/drafts/{draft_id}")
async def existing_series_draft_status(
    draft_id: uuid.UUID,
    context: ExistingSeriesRouteContext = Depends(existing_series_route_context),
):
    return await reconcile_existing_series_draft(
        context.pool,
        context.client,
        draft_id=str(draft_id),
        session_id=context.session_id,
    )


@router.post("/api/scraper/drafts/{draft_id}/publish")
async def existing_series_draft_publish(
    draft_id: uuid.UUID,
    context: ExistingSeriesRouteContext = Depends(existing_series_route_context),
):
    return await publish_existing_series_draft(
        context.pool,
        context.client,
        ExistingSeriesPublishRequest(
            draft_id=str(draft_id),
            actor_id=context.actor_id,
            session_id=context.session_id or "",
        ),
    )
