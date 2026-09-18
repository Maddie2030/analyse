# Scraper source compatibility

## What was wrong

MReader had all three fetch tiers (HTTPX, Scrapling/curl_cffi, Scrapling Chromium), but a few integration choices prevented them from being used efficiently:

1. JSON endpoints were fetched as generic payloads. A HTTP 200 HTML challenge could pass transport validation and fail only in `json.loads`, after the fetcher had lost the opportunity to escalate to Scrapling HTTP.
2. Chromium engine affinity was host-wide. One difficult URL could make every later HTML request on the host browser-first for the affinity TTL.
3. Generic manga parsing was stricter than the attached `scraper_v_1.0.3`, especially around root-level chapter URLs and lazy/data-* attributes.
4. Naver's desktop list page is a client-rendered shell even though the same episode data is available from its public JSON endpoint.
5. ThunderScans uses root-level chapter URLs and WordPress/Madara-style lazy reader containers; generic parsing alone made this unnecessarily fragile.

## Current strategy

- **Naver:** public JSON episode list/info -> static episode HTML (`#comic_view_area`) -> Scrapling HTTP when transport compatibility is required -> Chromium only as the final HTML fallback.
- **ThunderScans:** static series HTML + source-specific root chapter matcher -> source-specific lazy reader extraction -> Scrapling HTTP -> Chromium only if the reader DOM truly needs JavaScript.
- **Generic sites:** broad safe link/image harvesting, bounded XHR URL capture during the browser fallback, SSRF checks on browser subrequests, and no interactive challenge solving by default.

Locked/login-only entries are not bypassed. If a source exposes chapter text without a public URL, MReader leaves that entry inaccessible instead of attempting to defeat the source's access controls.

## Resource policy

Only `scrapling-http` can receive host-level engine affinity. Chromium is re-evaluated per request. Chapter image download concurrency comes from `SCRAPER_IMAGE_DOWNLOAD_CONCURRENCY`.
