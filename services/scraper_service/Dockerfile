FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libvips42=8.14.1-3+deb12u3 \
    gosu=1.14-1+b10 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY services/scraper_service/requirements.txt .
RUN pip install -r requirements.txt

# Scraper security/session validation uses the repository shared package.
# Keep this explicit so API and worker images cannot build successfully while
# failing at runtime with ModuleNotFoundError: shared.
COPY shared /shared
RUN pip install --no-deps -e /shared

COPY services/scraper_service/app ./app
COPY scripts/docker/mreader-staging-entrypoint.sh /usr/local/bin/mreader-staging-entrypoint
COPY scripts/docker/mreader-staging-volume-init.sh /usr/local/bin/mreader-staging-volume-init

RUN mkdir -p /var/lib/mreader/scraper-staging && \
    chown -R app:app /app /var/lib/mreader/scraper-staging && \
    chmod 0770 /var/lib/mreader/scraper-staging && \
    chmod 0755 /usr/local/bin/mreader-staging-entrypoint /usr/local/bin/mreader-staging-volume-init

# Chromium deliberately does NOT live in this image. JavaScript-only source
# rendering is handled by the optional Dockerfile.browser worker.
USER root
ENTRYPOINT ["/usr/local/bin/mreader-staging-entrypoint"]
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${SCRAPER_API_WORKERS:-1} --no-access-log"]
