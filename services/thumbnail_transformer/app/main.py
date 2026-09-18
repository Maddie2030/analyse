from __future__ import annotations

import hmac
import logging
import os

import pyvips

# Suppress routine libvips pipeline diagnostics while retaining warnings/errors.
logging.getLogger("pyvips").setLevel(logging.WARNING)
logging.getLogger("pyvips.voperation").setLevel(logging.WARNING)

from fastapi import FastAPI, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

app = FastAPI(title="MReader Thumbnail Transformer", version="1.3.0-rc4.84")

MAX_INPUT_BYTES = max(1, min(int(os.getenv("MAX_INPUT_BYTES", str(10 * 1024 * 1024))), 50 * 1024 * 1024))
MAX_WIDTH = max(64, min(int(os.getenv("MAX_OUTPUT_WIDTH", "4096")), 8192))
WEBP_QUALITY = max(40, min(int(os.getenv("WEBP_QUALITY", "82")), 100))
SHARED_SECRET = os.getenv("TRANSFORM_SHARED_SECRET", "")


def _authorize(request: Request) -> None:
    if not SHARED_SECRET:
        raise HTTPException(status_code=503, detail="transform service is not configured")
    supplied = request.headers.get("x-mreader-transform-token", "")
    if not hmac.compare_digest(supplied, SHARED_SECRET):
        raise HTTPException(status_code=401, detail="unauthorized")


def _retain_icc_metadata_only(image: pyvips.Image) -> pyvips.Image:
    """Keep ICC color data while stripping other metadata on libvips 8.14.x."""
    output = image.copy()
    for field in output.get_fields():
        if field != "icc-profile-data":
            output.remove(field)
    return output


def _transform(data: bytes, width: int) -> tuple[bytes, int, int]:
    try:
        image = pyvips.Image.new_from_buffer(data, "", page=0, access="sequential")
    except pyvips.Error:
        image = pyvips.Image.new_from_buffer(data, "", access="sequential")
    image = image.autorot().copy_memory()
    if width > 0 and image.width > width:
        scale = width / image.width
        image = image.resize(scale, kernel="lanczos3")
    output = _retain_icc_metadata_only(image).write_to_buffer(
        ".webp", Q=WEBP_QUALITY
    )
    return output, image.width, image.height


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "thumbnail-transformer"}


@app.post("/v1/thumbnail")
async def thumbnail(request: Request, width: int = Query(default=0, ge=0, le=8192)) -> Response:
    _authorize(request)
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty image")
    if len(data) > MAX_INPUT_BYTES:
        raise HTTPException(status_code=413, detail="image too large")
    width = min(width, MAX_WIDTH) if width > 0 else 0
    try:
        body, out_width, out_height = await run_in_threadpool(_transform, data, width)
    except (pyvips.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="unsupported image") from exc
    return Response(
        content=body,
        media_type="image/webp",
        headers={
            "X-Image-Width": str(out_width),
            "X-Image-Height": str(out_height),
            "Cache-Control": "no-store",
        },
    )
