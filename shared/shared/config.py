from functools import lru_cache
import os

from pydantic_settings import BaseSettings


WORKLOAD_DATABASE_DSN_ENV_KEYS = (
    "AUTH_DATABASE_URL",
    "AUTH_ADMIN_DATABASE_URL",
    "IMAGE_DATABASE_URL",
    "MEDIA_DATABASE_URL",
    "MEDIA_THUMBNAIL_DATABASE_URL",
    "LIFECYCLE_DATABASE_URL",
)


def require_workload_database_url() -> str:
    configured = [
        (key, value)
        for key in WORKLOAD_DATABASE_DSN_ENV_KEYS
        if (value := os.getenv(key, "").strip())
    ]
    if len(configured) != 1:
        names = ", ".join(WORKLOAD_DATABASE_DSN_ENV_KEYS)
        raise RuntimeError(
            "exactly one dedicated database DSN is required; expected one of " + names
        )
    dsn = configured[0][1]
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn[len("postgresql://"):]
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn[len("postgres://"):]
    return dsn


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────
    @property
    def database_url(self) -> str:
        return require_workload_database_url()

    # Conservative per-process defaults. Containers scale via worker/replica count;
    # oversized per-process pools waste RAM and can exhaust PostgreSQL connections.
    DB_POOL_SIZE: int = 4
    DB_MAX_OVERFLOW: int = 2
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    DB_STATEMENT_TIMEOUT_MS: int = 10000

    # ── Redis ──────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_MAX_CONNECTIONS: int = 40

    # ── RabbitMQ operational jobs ──────────────────────
    RABBITMQ_URL: str = "amqp://mreader:mreader@rabbitmq:5672/mreader"
    RABBITMQ_JOBS_EXCHANGE: str = "mreader.jobs"
    RABBITMQ_RETRY_DELAY_MS: int = 5000
    RABBITMQ_MAX_ATTEMPTS: int = 3
    RABBITMQ_CONNECT_TIMEOUT_SECONDS: float = 10.0

    # ── SeaweedFS ──────────────────────────────────────
    SEAWEEDFS_MASTER_URL: str = "http://seaweedfs-master:9333"
    SEAWEEDFS_FILER_URL: str = "http://seaweedfs-filer:8888"
    SEAWEEDFS_REPLICATION: str = "001"
    SEAWEEDFS_TTL_DAYS: int = 0
    SEAWEEDFS_MAX_RETRIES: int = 8
    SEAWEEDFS_RETRY_BASE_SECONDS: float = 1.0
    SEAWEEDFS_RETRY_MAX_DELAY_SECONDS: float = 15.0
    SEAWEEDFS_CONNECT_TIMEOUT: float = 5.0
    SEAWEEDFS_READ_TIMEOUT: float = 30.0
    SEAWEEDFS_HTTP_MAX_CONNECTIONS: int = 16
    SEAWEEDFS_HTTP_KEEPALIVE_CONNECTIONS: int = 8
    # Protect the NAS from write bursts while user reads keep priority.
    SEAWEEDFS_WRITE_CONCURRENCY: int = 2
    SEAWEEDFS_SLOW_WRITE_THRESHOLD_SECONDS: float = 1.5
    SEAWEEDFS_SLOW_WRITE_COOLDOWN_SECONDS: float = 0.25

    # ── Auth / Sessions ────────────────────────────────
    TOKEN_SECRET: str = "change-me-in-production"
    SESSION_TTL_SECONDS: int = 86400
    SESSION_COOKIE_NAME: str = "session_id"
    COOKIE_SECURE: bool = False

    # ── Image Tokens / protected page delivery ─────────
    IMAGE_TOKEN_TTL_SECONDS: int = 300
    IMAGE_TOKEN_BATCH_SIZE: int = 50
    PAGE_ENCODING_V4_ROWS: int = 4
    PAGE_ENCODING_V4_COLUMNS: int = 4
    PAGE_ENCODING_V4_OVERLAP: int = 12
    PAGE_MAX_WIDTH: int = 1080
    PAGE_RESPONSIVE_WIDTH: int = 720
    IMAGE_GRANT_ALLOW_SESSIONLESS_DELIVERY: bool = False

    # ── Rate Limiting ──────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 200
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ── Cache ──────────────────────────────────────────
    CACHE_TTL_SERIES_LIST: int = 60
    CACHE_TTL_SERIES_DETAIL: int = 120
    CACHE_TTL_GENRES: int = 600
    CACHE_TTL_CHAPTER_DETAIL: int = 120

    # ── Turnstile ──────────────────────────────────────
    TURNSTILE_SECRET: str = ""
    TURNSTILE_ENABLED: bool = False

    # ── CORS / Frontend ────────────────────────────────
    ALLOWED_ORIGIN: str = "http://localhost:5173,http://localhost:3000"
    DEBUG: bool = False

    # ── Upload ──────────────────────────────────────────
    STORAGE_PATH: str = "/data/manga_storage"
    MAX_UPLOAD_SIZE_MB: int = 500

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
