#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_READER="$ROOT_DIR/frontend/src/pages/Reader.tsx"
WEB_PROTECTED="$ROOT_DIR/frontend/src/reader/ProtectedPage.tsx"
WEB_API="$ROOT_DIR/frontend/src/api/client.ts"
WEB_RUNTIME="$ROOT_DIR/frontend/src/config/runtime.ts"
ANDROID_NAV="$ROOT_DIR/android/app/src/main/java/com/mreader/android/ui/MReaderApp.kt"
ANDROID_WEB="$ROOT_DIR/android/app/src/main/java/com/mreader/android/ui/screens/WebReaderScreen.kt"
ANDROID_NATIVE="$ROOT_DIR/android/app/src/main/java/com/mreader/android/ui/screens/ReaderScreen.kt"
ANDROID_API="$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/network/MReaderApiService.kt"
ANDROID_VARIANT_POLICY="$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ReaderVariantPolicy.kt"
READER_GO="$ROOT_DIR/services/reader_go/internal/httpapi/api.go"
STORE_GO="$ROOT_DIR/services/reader_go/internal/store/store.go"
USER_GATEWAY="$ROOT_DIR/deploy/docker-desktop-hybrid/Caddyfile.user"
ADMIN_GATEWAY="$ROOT_DIR/deploy/docker-desktop-hybrid/Caddyfile.admin"

fail() { printf 'WEB/ANDROID READER CONTRACT AUDIT FAILED: %s\n' "$*" >&2; exit 1; }
pass() { printf '  [ok] %s\n' "$*"; }
need() {
  local file="$1" text="$2" label="$3"
  grep -Fq -- "$text" "$file" || fail "$label ($text missing from ${file#$ROOT_DIR/})"
  pass "$label"
}

printf '==> Web/Android reader contract audit\n'

# Source-of-truth web flow.
need "$WEB_API" '/api/reader/${seriesSlug}/${chapterSlug}' 'Web reader manifest uses /api/reader'
need "$WEB_API" '/api/token/chapter/${encodeURIComponent(seriesSlug)}/${encodeURIComponent(chapterSlug)}' 'Web reader refreshes one chapter grant with /api/token/chapter'
need "$WEB_READER" 'setChapterToken(d.chapter_token || "")' 'Web reader accepts only manifest chapter_token'
if grep -Fq '/api/token/page' "$WEB_API"; then fail 'Web API still exposes legacy page-token refresh'; fi
if grep -Fq 'pages.find((page) => Boolean(page.token))' "$WEB_READER"; then fail 'Web Reader still scans legacy per-page tokens'; fi
need "$WEB_PROTECTED" 'protectedAssetUrl(selectedAsset.path, token)' 'Web protected pages use runtime protectedAssetUrl'
need "$WEB_RUNTIME" 'const relative = `/images/' 'Web protected asset path is /images/<manifest path>'

# Android native reader is the default again, but it must consume the same
# manifest/token semantics as the working web reader. The embedded web reader
# remains an explicit fail-safe route rather than the primary chapter engine.
need "$ANDROID_NAV" 'ReaderScreen(' 'Android chapter route defaults to optimized native reader'
need "$ANDROID_NAV" 'onWebFallback = { navController.navigate(Routes.webReader(seriesSlug, chapterSlug)) }' 'Native reader retains explicit proven-web fallback'
need "$ANDROID_WEB" '"$baseUrl/read/${Uri.encode(seriesSlug)}/${Uri.encode(chapterSlug)}"' 'Fallback bridge loads exact /read/<series>/<chapter> route'
need "$ANDROID_WEB" 'cookieManager.setCookie(baseUrl, sessionCookies[index])' 'Fallback bridge waits to bridge native auth cookies into WebView'
need "$ANDROID_WEB" 'MIXED_CONTENT_NEVER_ALLOW' 'Fallback bridge keeps HTTPS mixed-content protection'
need "$ANDROID_NATIVE" 'repository.prefetchReaderWindow(' 'Native reader warms a bounded encoded-byte viewport window'
need "$WEB_PROTECTED" "devicePixels <= responsiveWidth * 1.15" 'Web reader uses physical-pixel-aware responsive selection'
need "$ANDROID_VARIANT_POLICY" 'screenWidthDp > 820' 'Android uses the same 820dp responsive cutoff as web'
need "$ANDROID_VARIANT_POLICY" 'screenWidthPx <= width.toFloat() * 1.15f' 'Android uses the same 15% physical-pixel tolerance as web'
need "$ANDROID_NATIVE" 'repository.api.mobileReaderPage(' 'Visible native pages use the versioned mobile adapter first'
if grep -Fq 'protectedAssetUrls(path, token)' "$ANDROID_NATIVE"; then fail 'Native reader still has direct /images compatibility fallback'; fi
pass 'Native reader uses only the versioned mobile protected-page adapter'
need "$ANDROID_API" 'api/mobile/v1/reader/{seriesSlug}/{chapterSlug}/page/{pageNumber}' 'Android native reader has versioned mobile page adapter'
need "$READER_GO" 'r.Get("/api/mobile/v1/reader/{seriesSlug}/{chapterSlug}/page/{pageNumber}", a.mobilePage)' 'Reader Go exposes versioned mobile page adapter'
need "$STORE_GO" 'ReaderPageAsset(' 'Mobile adapter derives page path from canonical published database row'
need "$READER_GO" 'a.validateImageRequest(r, imagePath, r.URL.Query().Get("token"))' 'Mobile adapter validates existing image/chapter grant'
need "$READER_GO" 'a.streamSeaweedAsset(w, r, imagePath, true)' 'Mobile adapter streams protected storage bytes without decode'

# Canonical runtime is Docker Desktop Kubernetes. User plane can address Reader
# by same-namespace service name; admin plane must cross into mreader-user.
need "$USER_GATEWAY" '@mobile path /api/mobile /api/mobile/*' 'Hybrid user gateway routes mobile adapter'
need "$USER_GATEWAY" 'reverse_proxy reader-go:8080' 'Hybrid user gateway targets same-namespace reader-go service'
need "$ADMIN_GATEWAY" '@mobile path /api/mobile /api/mobile/*' 'Hybrid admin gateway routes mobile adapter'
need "$ADMIN_GATEWAY" 'reader-go.mreader-user.svc.cluster.local:8080' 'Hybrid admin gateway targets Reader across namespaces'

printf '==> Web/Android reader contract audit passed\n'
