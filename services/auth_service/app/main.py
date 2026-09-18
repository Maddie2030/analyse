from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared import init_redis_pool, close_redis_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_redis_pool()
    yield
    await close_redis_pool()


app = FastAPI(title="Auth Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "auth"}


from app.routers import auth  # noqa: E402

app.include_router(auth.router, prefix="/api/auth")
