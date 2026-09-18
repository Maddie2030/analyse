# Scraper hardening notes

This release keeps MReader's existing scraper workflow/adapters and uses ideas from Scrapling where they close concrete reliability gaps rather than replacing the whole service.

## Architecture applied

1. `httpx` remains the cheapest bounded first fetch path with explicit redirect validation and response-size caps.
2. Scrapling `AsyncFetcher` / `curl_cffi` is the second path for browser-like TLS/header compatibility and cookie-preserving HTTP fetches.
3. Scrapling `StealthyFetcher` is a bounded Chromium fallback for JavaScript-rendered HTML, but Chromium no longer lives in the normal scraper image. It runs in the optional `scraper_browser` container and is called over the internal Compose network only when browser escalation is enabled.
4. A short per-host engine affinity cache remembers a recently required fallback and avoids repeatedly paying for a known-bad transport path.
5. Interactive challenge solving remains disabled. A verification page that survives normal rendering is reported as a source failure instead of silently entering staging.


### Browser worker lifecycle

Browser fallback is disabled by default (`SCRAPER_BROWSER_FALLBACK_ENABLED=false`). Enable it only for source adapters that actually need JavaScript rendering:

```bash
./scripts/scraper-browser.sh enable <mode>
./scripts/scraper-browser.sh disable <mode>
./scripts/scraper-browser.sh purge <mode>
```

The normal scraper image contains no Chromium binary. Existing `.env` files that still set browser fallback to true are also safe: the scraper only considers browser escalation available when a remote worker URL is configured or when running inside the dedicated local-browser image.

## Parser and media resilience

- Static app-shell detection escalates Next/Nuxt/React shells that contain no useful server-rendered DOM.
- Generic page extraction now understands common lazy-load attributes, `picture/source`, background-image attributes, `noscript` image fallbacks, and embedded SPA/script URLs.
- Recursive discovery prioritizes next/pagination/index links before unrelated same-site pages and gives an otherwise empty fetched index page one bounded rendered retry.
- Image validation now checks bytes as well as headers. HTML/challenge bodies mislabeled as `image/*` are rejected, and known AVIF/TIFF signatures correct bad CDN metadata.
- Chapter image download concurrency is configurable and defaults lower than the previous fixed burst.

## Operational knobs

See `.env.example` for `SCRAPER_SCRAPLING_*`, `SCRAPER_BROWSER_*`, `SCRAPER_ENGINE_AFFINITY_*`, and `SCRAPER_IMAGE_DOWNLOAD_CONCURRENCY` settings.


## Source-native additions

- Naver series discovery uses the public `/api/article/list` JSON endpoint first. Chromium is a compatibility fallback, not the default discovery engine.
- Browser fallback enables Scrapling `capture_xhr` only for same-host requests and retains only a bounded URL inventory, not full API payloads.
- Lazy reader images prefer `data-src`, `data-lazy-src`, original/source-set attributes before normal `src`, and known placeholders/data URIs are rejected.
- Common `data-href`/`data-url`/`data-chapter-url`/`data-link` chapter references are harvested for JS/WordPress themes.
- Explicit paid/locked entries are not bypassed.
