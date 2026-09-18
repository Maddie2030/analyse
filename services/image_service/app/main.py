from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from shared import (
    close_redis_pool,
    close_seaweedfs_client,
    init_redis_pool,
    init_seaweedfs_client,
)

from app.health import readiness
from app.rabbitmq import close_broker
from app.observability import RequestLoggingMiddleware, configure_logging


configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_redis_pool()
    init_seaweedfs_client()
    yield
    await close_broker()
    await close_redis_pool()
    await close_seaweedfs_client()


app = FastAPI(
    title="MReader Media Service",
    version="1.3.0-rc4.84",
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)


@app.get("/health")
@app.get("/health/live")
async def health_live():
    return {
        "status": "ok",
        "service": "media",
    }


@app.get("/health/ready")
async def health_ready():
    healthy, dependencies = await readiness()

    payload = {
        "status": "ok" if healthy else "degraded",
        "service": "media",
        "dependencies": dependencies,
    }

    if healthy:
        return payload

    return JSONResponse(
        status_code=503,
        content=payload,
    )


from app.routers import exports, jobs, lifecycle, upload  # noqa: E402

# Keep the existing public API stable.
app.include_router(upload.router, prefix="/api/upload")

app.include_router(jobs.router, prefix="/api/upload/jobs")
app.include_router(jobs.internal_router, prefix="/internal/v1/media/jobs")

# Admin-only storage export endpoints.
app.include_router(exports.router, prefix="/api/upload/admin")

app.include_router(lifecycle.router, prefix="/api/upload/admin")
