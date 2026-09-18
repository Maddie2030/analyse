#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$ROOT/services/scraper_service/app/series_drafts.py"
IDENTITY="$ROOT/services/scraper_service/app/chapter_identity.py"
UI="$ROOT/frontend/src/pages/AdminScraperNewSeries.tsx"
CLIENT="$ROOT/frontend/src/api/client.ts"

# Scraped chapter identity must be number-derived on both backend and UI.
grep -q 'chapter_slug_from_number(number)' "$BACKEND"
grep -q 'return f"ch-{text.replace' "$IDENTITY"
grep -q 'chapterSlugFromNumber(chapterNumber)' "$UI"
grep -q 'title="Automatically generated from the chapter number"' "$UI"

# Chapter titles must not drive slugs anymore.
if grep -q 'patch.chapter_slug = kebabCase(chapterTitle)' "$UI"; then
  echo 'chapter title still controls scraper slug' >&2
  exit 1
fi

# Clear-all persists a suppression policy and is not gated by published_series_id.
grep -q 'options\["suppress_chapter_titles"\] = True' "$BACKEND"
grep -q 'None if suppress_chapter_titles else chapter.title' "$BACKEND"
grep -q 'chapter_titles_suppressed' "$BACKEND"
grep -q 'chapter_titles_suppressed' "$CLIENT"
grep -q 'chapterTitleClearAllowed' "$UI"

# Discovery completion must hydrate the full draft so new update chapters appear.
grep -q 'discoveryJustFinished' "$UI"
grep -q 'scraperGetSeriesDraft(draft.id)' "$UI"

printf '%s\n' 'scraper chapter identity/title-policy static regression PASS'
