FROM python:3.12.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libvips42=8.14.1-3+deb12u3 ca-certificates=20250419~deb12u1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/thumbnail_transformer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY services/thumbnail_transformer/app /app/app
RUN useradd --system --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
