FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /tests

COPY tests/api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY tests/api /tests
COPY tests/load/seed.py /load/seed.py

# Self-contained source/API coverage audit. Keeping this inside the Docker test
# image avoids requiring Python on a Windows Git Bash host.
COPY services /repo/services
COPY tests /repo/tests
COPY contracts /repo/contracts
COPY db/migrations /repo/db/migrations
COPY scripts/tests/api-route-audit.py /repo/scripts/tests/api-route-audit.py

CMD ["python", "-u", "-m", "pytest", "-vv", "-ra", "--disable-warnings", "--maxfail=0", "-m", "not external"]
