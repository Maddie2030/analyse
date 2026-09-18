#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"

# Worker-level bounded concurrency.
grep -q 'PUBLISH_QUEUE: min(2, concurrency)' services/scraper_service/app/series_worker.py
grep -q 'CHAPTER_PUBLISH_QUEUE: min(2, concurrency)' services/scraper_service/app/series_worker.py
grep -q 'STAGE_QUEUE: concurrency' services/scraper_service/app/series_worker.py

# Same logical production series is serialized; different series remain parallel.
grep -q 'scraper-publish:series:{published_series_id}' services/scraper_service/app/series_drafts.py
grep -q 'scraper-publish:slug:{normalized_slug}' services/scraper_service/app/series_drafts.py
grep -q 'scraper-stage-series:{target_series_id}' services/scraper_service/app/series_drafts.py

# Existing-series updates must subtract already-published chapter numbers both at
# discovery and again transactionally at staging.
grep -q 'chapters_already_present' services/scraper_service/app/series_drafts.py
grep -q 'Skipped because this chapter number already exists in production' services/scraper_service/app/series_drafts.py
grep -q 'Another active update already owns this chapter number' services/scraper_service/app/series_drafts.py

# Submission/source dedupe + final DB chapter uniqueness remain the last line of defense.
grep -q 'scraper-source:{source_key}' services/scraper_service/app/series_drafts.py
grep -q 'source_url_key' db/migrations/035_fresh_baseline_concurrency.sql
grep -q 'UNIQUE (series_id, chapter_number)' db/init.sql

awk '/name: scraper-series-worker/{f=1} f&&/maxReplicaCount:/{print; exit}' deploy/docker-desktop-hybrid/admin-keda.yaml | grep -q 'maxReplicaCount: 2'
awk '/name: scraper-batch-worker/{f=1} f&&/maxReplicaCount:/{print; exit}' deploy/docker-desktop-hybrid/admin-keda.yaml | grep -q 'maxReplicaCount: 2'

echo 'hybrid concurrency static regression PASSED'
