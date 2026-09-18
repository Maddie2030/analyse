# ======================================================
# Stage 1 - Build Dependencies
# ======================================================
FROM python:3.12.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Copy requirements first for Docker layer caching
COPY services/auth_service/requirements.txt .

# Install Python packages into a separate location
RUN pip install --prefix=/install -r requirements.txt

# Install shared package
COPY shared /shared
RUN pip install --prefix=/install --no-deps -e /shared


# ======================================================
# Stage 2 - Runtime Image
# ======================================================
FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2

WORKDIR /app

# Create non-root user
RUN addgroup --system app && \
    adduser --system --ingroup app app

# Copy installed dependencies
COPY --from=builder /install /usr/local

# Copy shared package
COPY --chown=app:app shared /shared

# Copy auth service
COPY --chown=app:app services/auth_service /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${AUTH_API_WORKERS:-1}"]
