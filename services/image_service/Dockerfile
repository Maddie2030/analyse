# ==========================================================
# Stage 1 - Builder
# ==========================================================
FROM python:3.12.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Copy requirements first for better layer caching
COPY services/image_service/requirements.txt .

# Install Python packages into a separate directory. All Python requirements are exact pins.
RUN python -m pip install --prefix=/install -r requirements.txt

# Install shared package
COPY shared /shared
RUN python -m pip install --prefix=/install --no-deps -e /shared


# ==========================================================
# Stage 2 - Runtime
# ==========================================================
FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2

WORKDIR /app

# Runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvips42=8.14.1-3+deb12u3 \
    gosu=1.14-1+b10 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

# Copy installed Python packages
COPY --from=builder /install /usr/local

# Copy shared package
COPY --chown=app:app shared /shared

# Copy application
COPY --chown=app:app services/image_service /app
COPY scripts/docker/mreader-staging-entrypoint.sh /usr/local/bin/mreader-staging-entrypoint

# The lifecycle worker shares the scraper staging named volume. Use the same
# numeric uid/gid as the scraper image so marker/page ownership is portable
# across images and Docker Desktop hosts.
RUN mkdir -p /var/lib/mreader/scraper-staging && \
    chown app:app /var/lib/mreader/scraper-staging && \
    chmod 0770 /var/lib/mreader/scraper-staging && \
    chmod 0755 /usr/local/bin/mreader-staging-entrypoint

# Same privilege-drop entrypoint as the scraper image. The normal image API and
# lifecycle worker both run as uid/gid 10001 after a tiny root-only volume repair.
USER root
ENTRYPOINT ["/usr/local/bin/mreader-staging-entrypoint"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${IMAGE_API_WORKERS:-1}"]
