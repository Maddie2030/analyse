from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # Shared session-cookie contract used by scraper admin authentication.
    # Keep this aligned with auth/catalog/reader/social/realtime services.
    SESSION_COOKIE_NAME: str = "session_id"

    postgres_db: str = "manhwa"
    scraper_database_url: str = ""
    scraper_batch_database_url: str = ""
    scraper_series_database_url: str = ""

    redis_url: str = "redis://redis:6379/0"
    rabbitmq_url: str = "amqp://mreader:mreader@rabbitmq:5672/mreader"
    rabbitmq_jobs_exchange: str = "mreader.jobs"
    rabbitmq_connection_name: str = "mreader-scraper"
    rabbitmq_connect_timeout_seconds: float = 10.0
    rabbitmq_retry_delay_ms: int = 5000
    rabbitmq_max_attempts: int = 3
    seaweedfs_filer_url: str = "http://seaweedfs-filer:8888"
    # Non-secret NAS coordinates are kept separately so Database Protection can
    # detect a stale Kubernetes env/Secret instead of merely showing the URL
    # currently used by the pod. Hybrid deploy derives SEAWEEDFS_FILER_URL from
    # these values.
    nas_seaweedfs_host: str = ""
    nas_seaweedfs_port: int = 8888
    postgres_backup_tz: str = "Asia/Kolkata"
    postgres_backup_auto_window_start: str = "20:00"
    postgres_backup_auto_window_end: str = "22:00"
    postgres_backup_daily_retention_days: int = 4
    postgres_backup_snapshot_retention_days: int = 2
    catalog_internal_url: str = "http://catalog_go:8080"
    reader_internal_url: str = "http://reader_go:8080"
    image_internal_url: str = "http://image_service:8000"
    catalog_internal_token: str = ""
    media_internal_token: str = ""
    recovery_bridge_internal_url: str = "http://host.docker.internal:18084"
    recovery_bridge_token: str = ""

    scraper_timeout_seconds: float = 30.0
    scraper_connect_timeout_seconds: float = 10.0
    scraper_max_response_bytes: int = 15 * 1024 * 1024
    scraper_max_redirects: int = 5
    scraper_fetch_attempts: int = 3
    scraper_retry_base_seconds: float = 0.75

    # Multi-engine fetch escalation. HTTPX remains the bounded/cheap first path.
    # Scrapling's curl_cffi fetcher is used only when normal HTTP fails or is
    # challenged, and Chromium is reserved for HTML that genuinely requires JS.
    scraper_scrapling_enabled: bool = True
    scraper_scrapling_image_fallback_enabled: bool = True
    scraper_scrapling_impersonate: str = "chrome"
    # Chromium is intentionally isolated in the optional scraper-browser
    # worker. The normal scraper image remains browser-free and uses HTTPX +
    # Scrapling/curl_cffi only. Enable this together with
    # SCRAPER_BROWSER_REMOTE_URL when the optional worker is running.
    scraper_browser_fallback_enabled: bool = False
    scraper_browser_remote_url: str = ""
    scraper_browser_concurrency: int = 1
    scraper_browser_timeout_ms: int = 60_000
    scraper_browser_wait_ms: int = 750
    scraper_browser_autoscroll_steps: int = 12
    scraper_browser_scroll_delay_ms: int = 250
    scraper_browser_block_ads: bool = True
    # When Chromium is already required, capture only same-host XHR/fetch URLs
    # and expose a bounded URL inventory to the existing parser. This costs no
    # extra source requests and lets SPA/API-backed readers disclose data that
    # never becomes a normal DOM attribute.
    scraper_browser_capture_xhr_enabled: bool = True
    scraper_browser_capture_xhr_max_responses: int = 16
    scraper_browser_capture_xhr_max_body_bytes: int = 1024 * 1024
    # Remember the least expensive engine that recently worked for a host.
    # This prevents every chapter/index request from repeating known-failing
    # transport attempts while the TTL remains short enough to self-heal.
    scraper_engine_affinity_ttl_seconds: int = 900
    scraper_engine_affinity_max_hosts: int = 256
    scraper_image_download_concurrency: int = 6

    # Durable local staging spool. Raw scraped images wait here until publish;
    # only final encoded assets are written to the NAS/SeaweedFS production tier.
    scraper_staging_root: str = "/var/lib/mreader/scraper-staging"
    scraper_staging_require_shared_mount: bool = True
    # Automatic expiry is intentionally disabled by default so upgrades never
    # silently delete unpublished staged content. Set >0 only when desired.
    scraper_staging_ttl_hours: int = 0
    scraper_staging_incomplete_ttl_minutes: int = 60
    scraper_staging_cleanup_wait_seconds: float = 30.0
    scraper_staging_retention_scan_seconds: int = 300

    # Production-object crash recovery. A tiny PostgreSQL ledger records every
    # possible external path before it is written, then clears that path list
    # immediately after canonical commit or durable cleanup handoff.
    scraper_storage_attempt_heartbeat_seconds: float = 20.0
    scraper_storage_attempt_stale_seconds: int = 300
    scraper_storage_attempt_recovery_batch: int = 50
    scraper_storage_attempt_retention_days: int = 7

    # Production/NAS transport resilience. These retries cover short network
    # interruptions before durable publish recovery takes over.
    scraper_storage_network_max_attempts: int = 8
    scraper_storage_network_retry_base_seconds: float = 1.0
    scraper_storage_network_retry_max_delay_seconds: float = 15.0
    scraper_storage_write_concurrency: int = 2
    scraper_storage_slow_write_threshold_seconds: float = 1.5
    scraper_storage_slow_write_cooldown_seconds: float = 0.25

    # When PostgreSQL is remote, page-by-page polling can become expensive.
    # Cancellation remains responsive while repeated worker checks are cached
    # for a very short bounded interval.
    scraper_db_poll_min_interval_seconds: float = 1.0
    scraper_progress_min_interval_seconds: float = 2.0
    # Deliberately disabled by default. This keeps the service focused on public
    # pages/JS rendering rather than automatically solving interactive challenges.
    scraper_browser_solve_cloudflare: bool = False

    # Resource/concurrency guards. These keep one scraper container from
    # opening excessive database/socket pools; scale by raising env values.
    scraper_redis_max_connections: int = 32
    scraper_api_db_max_connections: int = 5
    scraper_api_http_max_connections: int = 32
    scraper_api_http_keepalive_connections: int = 12
    scraper_batch_db_max_connections: int = 3
    scraper_batch_http_max_connections: int = 16
    scraper_batch_http_keepalive_connections: int = 8
    scraper_series_db_max_connections: int = 8
    scraper_series_http_max_connections: int = 32
    scraper_series_http_keepalive_connections: int = 16

    # scraper_v_1.0.3 used a normal Chrome UA. This is intentionally a
    # compatibility UA, not an anti-bot bypass mechanism.
    scraper_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
    scraper_accept_language: str = "en-US,en;q=0.9"

    @staticmethod
    def _require_database_url(value: str, env_name: str) -> str:
        value = value.strip()
        if not value:
            raise RuntimeError(f"{env_name} is required")
        return value

    @property
    def database_url(self) -> str:
        return self._require_database_url(self.scraper_database_url, "SCRAPER_DATABASE_URL")

    @property
    def batch_database_url(self) -> str:
        return self._require_database_url(
            self.scraper_batch_database_url, "SCRAPER_BATCH_DATABASE_URL"
        )

    @property
    def series_database_url(self) -> str:
        return self._require_database_url(
            self.scraper_series_database_url, "SCRAPER_SERIES_DATABASE_URL"
        )


settings = Settings()
