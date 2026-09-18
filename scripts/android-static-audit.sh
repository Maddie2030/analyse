#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANDROID="$ROOT_DIR/android"
REPO="$ANDROID/app/src/main/java/com/mreader/android/core/repository/MReaderRepository.kt"
API_SERVICE="$ANDROID/app/src/main/java/com/mreader/android/core/network/MReaderApiService.kt"
API_ADAPTER="$ANDROID/app/src/main/java/com/mreader/android/core/network/MReaderApiAdapter.kt"
READER="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/ReaderScreen.kt"
THEME="$ANDROID/app/src/main/java/com/mreader/android/ui/theme/Theme.kt"
COMMON="$ANDROID/app/src/main/java/com/mreader/android/ui/components/Common.kt"
LAYOUT_POLICY="$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReaderLayoutPolicy.kt"
DECODER="$ANDROID/app/src/main/java/com/mreader/android/core/codec/ProtectedPageDecoder.kt"
CATALOG="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/CatalogScreen.kt"
SEARCH="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/SearchScreen.kt"
NOTIFICATIONS="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/NotificationsScreen.kt"
REGISTER="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/RegisterScreen.kt"
SETTINGS="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/SettingsScreen.kt"
APP_NAV="$ANDROID/app/src/main/java/com/mreader/android/ui/MReaderApp.kt"
APP_VIEWMODEL="$ANDROID/app/src/main/java/com/mreader/android/ui/AppViewModel.kt"
LIBRARY="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/LibraryScreen.kt"
SERIES="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/SeriesScreen.kt"
MODELS="$ANDROID/app/src/main/java/com/mreader/android/core/model/Models.kt"
PARSERS="$ANDROID/app/src/main/java/com/mreader/android/core/network/JsonParsers.kt"
READER_LAYOUT_TEST="$ANDROID/app/src/test/java/com/mreader/android/core/repository/ReaderLayoutPolicyTest.kt"
COMMENTS="$ANDROID/app/src/main/java/com/mreader/android/ui/components/CommentSection.kt"
WEB_READER="$ANDROID/app/src/main/java/com/mreader/android/ui/screens/WebReaderScreen.kt"
USER_GATEWAY="$ROOT_DIR/deploy/docker-desktop-hybrid/Caddyfile.user"
ADMIN_GATEWAY="$ROOT_DIR/deploy/docker-desktop-hybrid/Caddyfile.admin"

fail() { printf 'ANDROID AUDIT FAILED: %s\n' "$*" >&2; exit 1; }
pass() { printf '  [ok] %s\n' "$*"; }
require_text() {
  local file="$1" text="$2" label="$3"
  grep -Fq -- "$text" "$file" || fail "$label ($text not found in ${file#$ROOT_DIR/})"
  pass "$label"
}
forbid_text() {
  local file="$1" text="$2" label="$3"
  ! grep -Fq -- "$text" "$file" || fail "$label ($text still present in ${file#$ROOT_DIR/})"
  pass "$label"
}

printf '==> Android static integration audit\n'
[[ -f "$ANDROID/app/build.gradle.kts" ]] || fail "Android app Gradle file missing"
[[ -f "$REPO" ]] || fail "Android repository missing"
[[ -f "$API_SERVICE" ]] || fail "Retrofit API service missing"
[[ -f "$API_ADAPTER" ]] || fail "Retrofit API adapter missing"
[[ -f "$READER" ]] || fail "Android reader missing"
[[ -f "$THEME" ]] || fail "Android theme missing"
[[ -f "$DECODER" ]] || fail "Android protected decoder missing"
[[ -f "$USER_GATEWAY" ]] || fail "Public user gateway Caddyfile missing"

require_text "$ANDROID/app/build.gradle.kts" 'versionName = "ver.1.1.0"' 'Android version matches requested app version'
require_text "$ANDROID/app/build.gradle.kts" 'versionCode = 484' 'Android build code matches RC4.84 continuity/recovery release'
require_text "$ANDROID/app/src/main/res/values/strings.xml" '<string name="app_name">Mreader</string>' 'Android launcher label remains Mreader'
require_text "$COMMON" 'Text("Mreader"' 'In-app mobile brand label matches Mreader launcher name'
require_text "$ANDROID/app/src/main/AndroidManifest.xml" 'android:icon="@mipmap/ic_launcher"' 'Android manifest uses supplied launcher icon'
require_text "$ANDROID/app/src/main/AndroidManifest.xml" 'android:roundIcon="@mipmap/ic_launcher_round"' 'Android manifest wires round launcher icon'
require_text "$READER_LAYOUT_TEST" 'import org.junit.Test' 'Reader layout regression test uses configured JUnit 4 runner'
require_text "$READER_LAYOUT_TEST" 'import org.junit.Assert.assertEquals' 'Reader layout regression test uses JUnit 4 assertions'
if grep -Fq 'import kotlin.test' "$READER_LAYOUT_TEST"; then
  fail 'ReaderLayoutPolicyTest still imports kotlin.test without kotlin-test dependency'
fi
pass 'Reader layout regression test has no unsupported kotlin.test imports'
require_text "$ANDROID/app/build.gradle.kts" 'https://overlord.seahorse-banded.ts.net' 'Public MReader gateway is the Android default'
require_text "$ANDROID/app/build.gradle.kts" 'compileSdk = 36' 'Android compile SDK uses current stable API 36'
require_text "$ANDROID/app/build.gradle.kts" 'targetSdk = 36' 'Android target SDK is API 36'
require_text "$ANDROID/docker/Dockerfile" 'ARG ANDROID_PLATFORM=36' 'Docker toolchain installs stable Android API 36'
require_text "$ANDROID/docker/Dockerfile" 'android --sdk="${ANDROID_SDK_ROOT}" sdk install' 'Docker toolchain uses Android CLI SDK installer'
require_text "$ANDROID/app/build.gradle.kts" 'compose-bom:2026.06.01' 'Compose BOM is pinned to the API-36-compatible 1.11.4 line'
require_text "$ANDROID/app/build.gradle.kts" 'lifecycle-runtime-compose:2.10.0' 'Lifecycle runtime Compose is pinned before the API-37 bump'
require_text "$ANDROID/app/build.gradle.kts" 'lifecycle-viewmodel-compose:2.10.0' 'Lifecycle ViewModel Compose is pinned before the API-37 bump'
require_text "$ANDROID/app/build.gradle.kts" 'navigation-compose:2.9.8' 'Navigation Compose is pinned before the API-37 bump'
if grep -Eq 'compose-bom:2026\.08\.00|lifecycle-(runtime|viewmodel)-compose:2\.11\.0|navigation-compose:2\.10\.0' "$ANDROID/app/build.gradle.kts"; then
  fail 'API-37-only AndroidX dependency pin remains in the API-36 build'
fi
pass 'No known API-37-only AndroidX pins remain'
if grep -Fq 'sdkmanager --install' "$ANDROID/docker/Dockerfile"; then
  fail 'Dockerfile still uses deprecated sdkmanager to install SDK packages'
fi
pass 'Deprecated sdkmanager package installation is absent'

require_text "$ANDROID/app/build.gradle.kts" 'com.squareup.retrofit2:retrofit:3.0.0' 'Retrofit 3 API adapter dependency is pinned'
require_text "$API_ADAPTER" 'class MReaderApiAdapter' 'Dedicated Android API adapter exists'
require_text "$API_ADAPTER" '.cookieJar(cookieJar)' 'Retrofit/OkHttp stack uses encrypted session cookies'
require_text "$API_ADAPTER" '.retryOnConnectionFailure(true)' 'OkHttp retries recoverable transport failures'
require_text "$API_ADAPTER" '.fastFallback(true)' 'OkHttp Happy Eyeballs fast fallback is enabled'
require_text "$API_ADAPTER" 'maxRequestsPerHost = 8' 'Android request concurrency is bounded'
require_text "$API_ADAPTER" 'probeGateway' 'Connection diagnostics probe exists'
require_text "$API_SERVICE" 'api/auth/profile' 'Auth profile endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/auth/login' 'Auth login endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/auth/logout' 'Auth logout endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/auth/register' 'Auth registration endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/catalog/tags' 'Catalog tags endpoint wired through Retrofit'
require_text "$API_SERVICE" 'min_rating' 'Advanced search rating filter is wired through Retrofit'
require_text "$API_SERVICE" 'api/social/series/metrics-batch' 'Search card social metrics endpoint is wired through Retrofit'
require_text "$API_SERVICE" 'api/social/comments' 'Series/chapter comments API is wired through Retrofit'
require_text "$API_SERVICE" 'api/notifications' 'Notification feed endpoint is wired through Retrofit'
require_text "$API_SERVICE" 'api/notifications/count' 'Notification badge endpoint is wired through Retrofit'
require_text "$API_SERVICE" 'api/catalog/series/{slug}' 'Catalog detail endpoint wired through Retrofit'
require_text "$API_SERVICE" '@GET("api/catalog/series")' 'Catalog list endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/reader/{seriesSlug}/{chapterSlug}' 'Reader manifest endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/mobile/v1/health' 'Versioned mobile reader adapter health endpoint is wired through Retrofit'
require_text "$API_SERVICE" 'api/mobile/v1/reader/{seriesSlug}/{chapterSlug}/page/{pageNumber}' 'Versioned mobile page adapter is wired through Retrofit'
require_text "$API_SERVICE" 'api/token/chapter/{seriesSlug}/{chapterSlug}' 'Chapter-scoped token refresh endpoint wired through Retrofit'
forbid_text "$API_SERVICE" 'api/token/page/' 'Legacy page-token Retrofit endpoint is removed'
require_text "$API_SERVICE" 'api/progress/{seriesSlug}/{chapterSlug}' 'Progress endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/social/library' 'Smart library endpoint wired through Retrofit'
require_text "$API_SERVICE" 'api/social/bookmarks/{seriesId}' 'Bookmark endpoints wired through Retrofit'

require_text "$USER_GATEWAY" '@auth path /api/auth /api/auth/*' 'Public gateway routes Auth'
require_text "$USER_GATEWAY" '@catalog path /api/catalog /api/catalog/*' 'Public gateway routes Catalog'
require_text "$USER_GATEWAY" '@mobile path /api/mobile /api/mobile/*' 'Public gateway routes mobile reader adapter'
require_text "$USER_GATEWAY" '@reader path /api/reader /api/reader/*' 'Public gateway routes Reader'
require_text "$USER_GATEWAY" '@token path /api/token /api/token/*' 'Public gateway routes Token'
require_text "$USER_GATEWAY" '@progress path /api/progress /api/progress/*' 'Public gateway routes Progress'
require_text "$USER_GATEWAY" '@social path /api/social /api/social/*' 'Public gateway routes Social'
require_text "$USER_GATEWAY" '@notifications path /api/notifications /api/notifications/*' 'Public gateway routes Notifications'
require_text "$USER_GATEWAY" '@images path /images /images/*' 'Public gateway routes Images'
require_text "$ADMIN_GATEWAY" '@mobile path /api/mobile /api/mobile/*' 'Hybrid admin gateway routes mobile reader adapter'
require_text "$ADMIN_GATEWAY" 'reader-go.mreader-user.svc.cluster.local:8080' 'Hybrid admin gateway targets Reader across namespaces'

require_text "$ROOT_DIR/services/auth_service/app/routers/auth.py" '@router.post("/login"' 'Auth service exposes login'
require_text "$ROOT_DIR/services/catalog_go/internal/httpapi/api.go" 'chapter_offset' 'Catalog service supports chapter pagination'
require_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" 'r.Get("/api/mobile/v1/health"' 'Reader service exposes mobile adapter health'
require_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" 'r.Get("/api/mobile/v1/reader/{seriesSlug}/{chapterSlug}/page/{pageNumber}"' 'Reader service exposes mobile protected-page adapter'
require_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" 'still-scrambled bytes' 'Mobile adapter preserves protected page bytes'
require_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" 'r.Get("/api/reader/{seriesSlug}/{chapterSlug}"' 'Reader service exposes manifest'
require_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" 'r.Get("/api/token/chapter/{seriesSlug}/{chapterSlug}"' 'Reader service exposes chapter-grant refresh'
forbid_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" '/api/token/page/' 'Reader service no longer exposes page-token refresh'
require_text "$ROOT_DIR/services/progress_go/internal/httpapi/api.go" '"/api/progress/{seriesSlug}/{chapterSlug}/commit"' 'Progress service exposes exit commit'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'app.get("/api/social/library"' 'Social service exposes smart library'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'app.get("/api/social/comments"' 'Social service exposes comments'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'app.post("/api/social/comments"' 'Social service accepts comments'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'app.get("/api/notifications"' 'Social service exposes notifications'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'series_slug: row.series?.slug ?? null' 'Notification payload includes Android navigation slug'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'chapter_slug: row.chapter?.slug ?? null' 'Notification payload includes Android chapter slug'

# Payload-schema compatibility: URLs alone are not enough; the Android parsers
# must agree with the service response field names used by the packaged backend.
require_text "$ROOT_DIR/services/auth_service/app/schemas/auth.py" 'avatar_key: str = "skull"' 'Auth avatar contract matches Android'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/network/JsonParsers.kt" 'obj.optString("avatar_key", "skull")' 'Android auth parser uses backend avatar default'
require_text "$ROOT_DIR/services/catalog_go/internal/model/model.go" 'json:"cover_image_path"' 'Catalog cover field matches Android parser'
require_text "$ROOT_DIR/services/catalog_go/internal/model/model.go" 'json:"chapter_has_more"' 'Catalog chapter pagination envelope matches Android parser'
require_text "$ROOT_DIR/services/catalog_go/internal/model/model.go" 'json:"first_chapter"' 'Catalog first-chapter field matches Android parser'
require_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" 'json:"chapter_token"' 'Reader chapter-grant field matches Android parser'
require_text "$ROOT_DIR/services/reader_go/internal/httpapi/api.go" 'json:"responsive_image_path,omitempty"' 'Reader responsive page field matches Android parser'
require_text "$ROOT_DIR/services/progress_go/internal/store/commands.go" 'json:"scroll_position"' 'Progress scroll field matches Android parser'
require_text "$ROOT_DIR/services/progress_go/internal/store/store.go" 'json:"updated_at"' 'Progress timestamp field matches Android parser'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 's.cover_image_path AS series_cover' 'Smart Library cover field matches Android parser'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'END AS read_state' 'Smart Library read-state field matches Android parser'

if grep -Fq 'repository.saveProgress(' "$READER"; then
  fail 'Reader still calls the obsolete scrolling saveProgress API'
fi
pass 'No obsolete per-scroll progress API call remains'
if grep -R --include='*.kt' -Fq '!!' "$ANDROID/app/src/main/java"; then
  fail 'Android production source still contains Kotlin non-null assertions (!!)'
fi
pass 'Android production source avoids non-null assertions'
require_text "$READER" 'manifest.seriesSlug, manifest.chapterSlug, token,' 'Token refresh passes the stale chapter grant for deduplicated refresh'
require_text "$ANDROID/app/src/main/java/com/mreader/android/core/repository/ProgressSelectionPolicy.kt" 'if (local == null) return server' 'Progress restore handles a nullable local checkpoint explicitly'
require_text "$ANDROID/app/src/test/java/com/mreader/android/core/repository/ProgressSelectionPolicyTest.kt" 'fun noProgressReturnsNull()' 'Progress selection nullable-state regression tests are present'

require_text "$READER" 'manifest = loaded' 'Reader exposes the manifest before progress restoration completes'
require_text "$READER" 'LaunchedEffect(seriesSlug, chapterSlug, loadAttempt)' 'Reader manifest loading is not gated on Auth profile initialization'
require_text "$READER" 'withTimeoutOrNull(4_000L)' 'Progress restoration is time-bounded and non-blocking'
require_text "$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReaderTokenPolicy.kt" 'object ReaderTokenPolicy' 'Reader chapter-grant policy exists'
require_text "$READER" 'page.encodingVersion == 4' 'Reader accepts only the current protected page encoding v4'
require_text "$READER" 'repository.assetStore.evict(lockedIdentity)' 'Corrupt protected cache entries are evicted before refetch under the shared asset lock'
require_text "$READER" 'page.encodingVersion == 4 && activeToken.isNotBlank()' 'V4 persistent cache reuse requires a current chapter grant'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'MAX_CACHE_BYTES = 256L * 1024L * 1024L' 'Persistent protected-page cache is bounded to 256 MiB'
require_text "$ROOT_DIR/android/app/build.gradle.kts" 'okhttp-bom:5.4.0' 'Android HTTP client uses current pinned OkHttp BOM'
require_text "$ANDROID/app/src/main/AndroidManifest.xml" 'android.permission.ACCESS_NETWORK_STATE' 'Android connection diagnostics can inspect network state'

# Web/mobile UI parity and reader reliability retained through RC4.68.
require_text "$THEME" 'Ink950 = Color(0xFF0C0B09)' 'Android background matches the web ink-night palette'
require_text "$THEME" 'Brand400 = Color(0xFFEF806C)' 'Android primary matches the web coral palette'
require_text "$THEME" 'Brand800 = Color(0xFF7A2818)' 'Android theme includes the web brand-800 shade used by reader borders'
require_text "$THEME" 'Gold400 = Color(0xFFE8B96A)' 'Android secondary matches the web gold palette'
require_text "$CATALOG" 'Find the next series worth losing sleep over.' 'Android browse hero mirrors the web discovery experience'
require_text "$CATALOG" 'Surprise me' 'Android browse includes web-style Surprise me discovery'
require_text "$CATALOG" 'DiscoveryBrowseAction(onBrowse = ::browseCatalog' 'Browse action under Surprise me is wired to the catalog anchor'
require_text "$CATALOG" 'gridState.animateScrollToItem(catalogHeadingItemIndex())' 'Browse action moves directly to the catalog section'
require_text "$CATALOG" 'browseJumpRequest' 'Browse jump waits for discovery shelf geometry to settle before scrolling'
require_text "$CATALOG" 'displayedCatalogKey' 'Catalog never presents stale rows as a newly selected page/filter'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/MobileContentCacheStore.kt" 'private val memory = LinkedHashMap' 'Catalog metadata cache has an in-memory hot layer for instant tab returns'
require_text "$REPO" 'fun peekListSeries(' 'Repository exposes parsed process-hot Catalog snapshots for zero-wait tab returns'
require_text "$REPO" 'fun peekDiscovery()' 'Repository exposes process-hot discovery snapshots'
require_text "$CATALOG" 'repository.peekListSeries(' 'Browse initializes directly from parsed process-hot Catalog data'
require_text "$SEARCH" 'repository.peekAdvancedSearch(' 'Search initializes directly from parsed process-hot result data'
require_text "$SERIES" 'repository.peekSeries(' 'Series initializes directly from parsed process-hot detail data'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/MobileContentCacheStore.kt" 'mreader_content_v1' 'Catalog metadata has a bounded persistent local cache'
require_text "$REPO" 'suspend fun cachedListSeries(' 'Catalog pages can render from local cache before revalidation'
require_text "$CATALOG" 'repository.cachedListSeries(' 'Browse uses stale-while-revalidate catalog pages'
require_text "$CATALOG" 'repository.cachedDiscovery()' 'Browse restores discovery shelves from local cache'
require_text "$SEARCH" 'repository.cachedAdvancedSearch(' 'Advanced Search can restore cached result pages before refresh'
require_text "$SEARCH" 'displayedSearchKey' 'Search never presents stale rows as a newly requested query/page'
require_text "$SERIES" 'repository.cachedSeries(' 'Series detail/chapter pages can restore cached catalog detail before refresh'
require_text "$CATALOG" 'val thumbnailWidth = if (compact) 114.dp else 130.dp' 'Latest Updates uses a larger responsive series thumbnail'
require_text "$CATALOG" 'fontSize = 11.sp' 'Latest Updates chapter labels use larger readable mobile typography'
require_text "$SEARCH" 'Advanced Search' 'Android includes the web advanced-search surface'
require_text "$SEARCH" 'selectedTags' 'Android advanced search includes multi-tag filtering'
require_text "$REGISTER" 'Create account' 'Android includes the web registration flow'
require_text "$NOTIFICATIONS" 'Notifications' 'Android includes the web notification feed'
require_text "$ANDROID/app/src/main/java/com/mreader/android/ui/AppViewModel.kt" 'fun markNotificationRead(notificationId: String)' 'Notification read mutation survives screen navigation via ViewModel scope'
require_text "$APP_NAV" 'Lifecycle.Event.ON_RESUME' 'Notification badge refreshes on foreground without background polling'
if grep -Eq '\}[[:space:]]*\}[[:space:]]*catch' "$NOTIFICATIONS"; then
  fail 'Notifications screen contains an extra closing brace before catch'
fi
pass 'Notifications coroutine try/catch structure has no RC4.62 double-brace regression'
require_text "$APP_NAV" 'Routes.SEARCH' 'Bottom navigation includes Search'
require_text "$APP_NAV" 'Routes.NOTIFICATIONS' 'Signed-in bottom navigation includes Alerts'
require_text "$WEB_READER" 'fun WebReaderScreen(' 'Crash-safe web-compatible chapter reader bridge exists'
require_text "$WEB_READER" 'MIXED_CONTENT_NEVER_ALLOW' 'Web reader bridge keeps HTTPS-only mixed-content protection'
require_text "$APP_NAV" 'ReaderScreen(' 'Chapter navigation defaults to optimized native reader'
require_text "$APP_NAV" 'onWebFallback = { navController.navigate(Routes.webReader(seriesSlug, chapterSlug)) }' 'Native reader keeps explicit web-reader fallback'
require_text "$API_ADAPTER" 'webViewCookies()' 'Native authenticated session can be bridged into WebView reader'
require_text "$WEB_READER" 'cookieManager.setCookie(baseUrl, sessionCookies[index])' 'Web reader bridge waits for native session cookie writes'
require_text "$WEB_READER" 'update = { },' 'Web reader bridge does not race cookie handoff from AndroidView.update'
require_text "$API_ADAPTER" 'mobileReaderPage(' 'Native fallback can use the versioned mobile page adapter'
require_text "$SETTINGS" 'Choose your reader mark' 'Android profile includes the web avatar selector'
require_text "$SETTINGS" 'Text("Connection"' 'Settings exposes a simple connection-status surface'
require_text "$SETTINGS" '"Connected"' 'Settings can report connected state'
require_text "$SETTINGS" '"Server under maintenance."' 'Settings can report maintenance state when disconnected'
if grep -Eq 'gateway URL|CDN URL|overlord\.seahorse' "$SETTINGS"; then
  fail 'Settings exposes server URLs instead of connection status only'
fi
pass 'Settings hides gateway/CDN URLs from the normal application UI'
require_text "$COMMENTS" 'fun CommentSection(' 'Android includes reusable web-style discussion UI'
require_text "$REPO" 'createComment(seriesId' 'Android repository can post comments'
require_text "$READER" 'key = "chapter-discussion"' 'Chapter reader includes chapter discussion'
require_text "$ANDROID/app/src/main/java/com/mreader/android/ui/screens/SeriesScreen.kt" 'key = "series-discussion"' 'Series detail includes series discussion'
require_text "$READER" 'listOfNotNull(responsive, primary)' 'Phone reader prefers the responsive protected derivative before canonical fallback'
require_text "$READER" 'for ((index, variant) in variants.withIndex())' 'Android reader automatically falls back between page variants'
require_text "$READER" 'Mobile reader adapter returned invalid protected page data.' 'Android reader diagnoses invalid mobile adapter responses'
require_text "$DECODER" 'targetWidthPx' 'Protected decoder reconstructs to a display-sized Android bitmap'
require_text "$DECODER" 'MAX_OUTPUT_PIXELS = 4_000_000L' 'Native decoder output budget is reduced for phone stability'
require_text "$REPO" 'suspend fun prefetchReaderWindow(' 'Native reader has bounded encoded-byte prefetch support'
require_text "$READER" 'ahead = 3' 'Reader network window is increased to three pages ahead'
require_text "$READER" 'behind = 2' 'Reader network window is increased to two pages behind'
require_text "$REPO" 'val gate = Semaphore(2)' 'Encoded-page prefetch overlaps at most two network requests'
require_text "$REPO" 'suspend fun cacheReaderChapter(' 'Signed-in chapter-wide persistent cache path exists'
require_text "$APP_VIEWMODEL" 'fun cacheChapterFor24Hours(' 'Chapter cache work survives Reader -> Browse navigation in ViewModel scope'
require_text "$READER" 'appViewModel.cacheChapterFor24Hours(loaded, screenWidthDp, screenWidthPx)' 'Opening a signed-in chapter starts its persistent 24-hour cache'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'RETENTION_MS = 24L * 60L * 60L * 1000L' 'Persistent chapter cache has strict 24-hour retention'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'val savedAtMillis: Long' 'In-memory protected pages carry the same retention timestamp as disk pages'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'entry.persistent && !fileFor(identity).isFile' 'Disk LRU eviction demotes matching RAM entries from persistent state'
require_text "$REPO" 'suspend fun <T> withProtectedAssetLock(' 'Protected-page loads share per-object request locks'
require_text "$READER" 'repository.withProtectedAssetLock(path)' 'Visible reader load deduplicates against prefetch/background caching'
require_text "$REPO" 'private suspend fun fetchReaderPageBytes(' 'Background chapter caching reuses canonical reader transport'
require_text "$REPO" 'for (index in manifest.pages.indices)' 'Chapter-wide 24-hour caching uses one sequential low-contention background lane'
require_text "$APP_VIEWMODEL" 'delay(900L)' 'Chapter-wide cache yields to the visible reader/prefetch window before starting'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'if (!persistent) return@withContext null' 'Guest chapter reads cannot reuse persistent disk cache'
require_text "$SETTINGS" 'Clear downloaded data' 'Settings exposes explicit downloaded-data clearing'
require_text "$SETTINGS" 'appViewModel.clearDownloadedData()' 'Settings cancels background chapter cache jobs before clearing data'
require_text "$SETTINGS" 'appViewModel.cacheEpoch.collectAsStateWithLifecycle()' 'Settings cache usage reacts when background chapter caching completes'
require_text "$APP_VIEWMODEL" 'cancelChapterCacheJobsAndAwait()' 'Background chapter-cache jobs are cancellable for logout/clear'

# RC4.73 end-to-end cache/integration hardening discovered by manual audit.
require_text "$REPO" 'private fun <T> putHot(' 'Process-hot metadata snapshots are explicitly bounded'
require_text "$REPO" 'HOT_CACHE_MAX_ENTRIES = 48' 'Process-hot metadata cache has a bounded entry ceiling'
require_text "$COMMON" 'initialValue = repository.coverStore.peek(url)' 'Warm covers render without a navigation-frame loading spinner'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/CoverImageStore.kt" 'fun peek(url: String): Bitmap?' 'Cover cache exposes a synchronous memory-only hot lookup'
require_text "$CATALOG" 'var displayedCatalogKey' 'Catalog tracks which page/filter its visible rows belong to'
require_text "$CATALOG" 'Never label rows from the previous page/filter as the new request.' 'Catalog clears stale rows for uncached page/filter changes'
require_text "$SERIES" 'var displayedChapterKey' 'Series tracks which chapter page/search is currently displayed'
require_text "$SERIES" 'val cached = repository.cachedSeries(' 'Every chapter page/search checks local cache before network refresh'
require_text "$REPO" 'suspend fun <T> withProtectedAssetLock(' 'Protected page fetches share a per-object deduplication lock'
require_text "$READER" 'repository.withProtectedAssetLock(path)' 'Visible reader participates in protected-page fetch deduplication'
require_text "$REPO" 'private suspend fun fetchReaderPageBytes(' 'Background chapter cache uses the canonical mobile reader transport'
forbid_text "$REPO" 'api.protectedAssetUrls(path, grant)' 'Background chapter cache has no direct /images compatibility fallback'
require_text "$REPO" 'api.mobileReaderPage(' 'Background chapter cache uses the versioned mobile reader adapter'
require_text "$REPO" 'for (index in manifest.pages.indices)' 'Chapter-wide persistent cache uses one sequential low-priority lane'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'val savedAtMillis: Long' 'In-memory protected bytes obey the same 24-hour age tracking'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'persistent && !hot.persistent' 'Guest RAM bytes are promoted only after the user gains persistent privilege'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ProtectedAssetStore.kt" 'val persisted = writeDisk(identity, bytes, savedAt)' 'Persistent RAM state reflects actual disk-write success'
require_text "$APP_VIEWMODEL" 'val cacheEpoch: StateFlow<Long>' 'Cache completion/clear events have a dedicated Settings refresh signal'
require_text "$SETTINGS" 'LaunchedEffect(cacheEpoch, user?.id)' 'Settings refreshes cache usage after background chapter caching changes'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/ReaderVariantPolicy.kt" 'screenWidthPx <= width.toFloat() * 1.15f' 'Android responsive-asset policy matches the web physical-pixel tolerance'
require_text "$ROOT_DIR/android/app/src/test/java/com/mreader/android/core/repository/ReaderVariantPolicyTest.kt" 'fun highDprPhoneKeepsPrimaryAsset()' 'Responsive-asset policy has high-DPR regression coverage'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/SuspendUtils.kt" 'throw cancelled' 'Best-effort UI helpers preserve coroutine cancellation'
require_text "$APP_NAV" 'saveState = true' 'Top-level navigation preserves tab scroll/filter state'
require_text "$APP_NAV" 'restoreState = true' 'Top-level navigation restores cached tab compositions while refresh epochs revalidate data'
# RC4.67 mobile/web personal-state parity.
require_text "$MODELS" 'val furthestChapterNumber: Double?' 'Smart Library model keeps furthest/reached chapter state from web API'
require_text "$MODELS" 'val latestPublishedAt: String?' 'Smart Library model keeps latest publication activity from web API'
require_text "$PARSERS" 'furthestChapterNumber = item.nullableDouble("furthest_chapter_number")' 'Smart Library parser preserves reached chapter state'
require_text "$PARSERS" 'publishedChapterCount = item.optInt("published_chapter_count")' 'Smart Library parser preserves chapter availability counts'
require_text "$CATALOG" 'user: StateFlow<User?>' 'Browse personal history follows authenticated session state'
require_text "$CATALOG" 'LaunchedEffect(currentUser?.id, refreshEpoch, reloadKey)' 'Browse reloads personal history when the signed-in account changes'
require_text "$CATALOG" 'repository.history(limit = 8, scope = currentUser?.id)' 'Browse consumes canonical Library history'
require_text "$APP_NAV" 'appViewModel.refreshForegroundContent()' 'Foreground resume refreshes personal content, not only notifications'
require_text "$LIBRARY" 'label = "Reached"' 'Mobile Smart Library mirrors web reached/latest chapter semantics'
require_text "$LIBRARY" '"Read next"' 'Mobile Smart Library mirrors web continue-action semantics'
require_text "$SERIES" 'onContentChanged: () -> Unit' 'Series personal mutations invalidate shared mobile content state'
if grep -Fq '${chapter.pageCount} pages' "$SERIES"; then
  fail 'Series chapter rows still expose chapter page counts on mobile'
fi
if grep -Eq 'Page [^\"]*/|[[:space:]][0-9]* pages • Native protected reader|m\.pages\.size.*pages' "$READER"; then
  fail 'Reader chrome still exposes chapter/page totals on mobile'
fi
pass 'Android chapter/page-count text is absent from mobile chapter rows and reader chrome'

# RC4.71 edge-to-edge reader geometry plus retained RC4.68 paging/fetch stability.
require_text "$LAYOUT_POLICY" 'fun contentWidthPx(' 'Reader image demand uses full visible reader width'
require_text "$LAYOUT_POLICY" 'return ReaderProgressMath.relativeHeight(width, height)' 'Reader progress geometry follows image aspect ratio directly'
require_text "$READER" 'ReaderLayoutPolicy.pageRelativeHeight(' 'Reader progress/resume uses shared edge-to-edge geometry'
require_text "$READER" 'ReaderLayoutPolicy.contentWidthPx(screenWidthDp, screenWidthPx)' 'Responsive derivative selection uses full reader width'
if grep -Eq 'ReaderCream|creamInsetDp|TARGET_CREAM_INSET_DP|MIN_PAGE_CONTENT_DP' "$THEME" "$LAYOUT_POLICY" "$READER"; then
  fail 'Cream reader surround/inset code is still present after RC4.71 removal'
fi
pass 'Cream reader surround/inset is removed from the native reader'
require_text "$COMMON" 'fun StableHorizontalShelf(' 'Shared stable horizontal shelf prevents carousel geometry drift'
require_text "$COMMON" 'fun adaptiveCarouselPosterWidth()' 'Carousel poster widths use one adaptive mobile policy'
require_text "$COMMON" 'fun MobilePaginationBar(' 'Shared mobile pagination control exists'
require_text "$COMMON" 'heightIn(min = 48.dp)' 'Pagination preserves a minimum 48dp touch target'
require_text "$COMMON" 'val compactAction = action != null && maxWidth < 380.dp' 'Section heading actions stack safely on narrow phones'
require_text "$API_SERVICE" '@Query("chapter_search") chapterSearch: String?' 'Android Catalog detail API wires web chapter_search'
require_text "$SERIES" 'private const val CHAPTER_PAGE_SIZE = 20' 'Series chapter page size matches web paging'
require_text "$SERIES" 'delay(250L)' 'Series chapter-number search uses the web debounce interval'
require_text "$SERIES" 'chapterSearch = chapterSearchQuery' 'Series search is sent to the Catalog service'
require_text "$SERIES" 'previousLabel = "Newer"' 'Series pager matches web Newer direction'
require_text "$SERIES" 'nextLabel = "Older"' 'Series pager matches web Older direction'
if grep -Fq 'Load more chapters' "$SERIES"; then
  fail 'Series screen regressed to append-style chapter loading'
fi
pass 'Series chapter paging no longer uses Load more'
require_text "$CATALOG" 'private const val CATALOG_PAGE_SIZE = 20' 'Catalog mobile page size matches web'
require_text "$CATALOG" 'pageIndex = catalogOffset / CATALOG_PAGE_SIZE' 'Catalog renders explicit page navigation'
if grep -Fq 'Load more' "$CATALOG"; then
  fail 'Catalog screen regressed to append-style Load more paging'
fi
pass 'Catalog paging uses explicit Previous/Next controls'
require_text "$SEARCH" 'private const val SEARCH_PAGE_SIZE = 20' 'Advanced Search page size matches web'
require_text "$SEARCH" 'lastRequestedOffset = requestedOffset' 'Search remembers the exact page attempted for retry'
require_text "$SEARCH" 'execute(lastRequestedOffset)' 'Search retries the exact failed page'
require_text "$SEARCH" 'loading = false' 'Search can release primary loading before optional enrichment completes'
require_text "$SEARCH" 'LaunchedEffect(refreshEpoch)' 'Search participates in foreground content reconciliation'
if grep -Fq 'Load more results' "$SEARCH"; then
  fail 'Advanced Search regressed to append-style Load more paging'
fi
pass 'Advanced Search paging uses explicit Previous/Next controls'
forbid_text "$LIBRARY" 'historyDeferred' 'Library has no duplicate Progress-history fetch alongside Smart Library'
require_text "$SERIES" 'val viewerDeferred = async' 'Series social and reading-state enrichment is parallelized'
require_text "$SERIES" 'if (currentUser == null) null else' 'Guests skip unnecessary personal series-reading fetches'
require_text "$APP_NAV" 'refreshEpoch = contentEpoch' 'Top-level mobile screens receive shared content freshness epoch'

require_text "$CATALOG" 'ResponsiveFrame(' 'Catalog uses responsive centered content framing'
require_text "$SEARCH" 'ResponsiveFrame(' 'Search uses responsive centered content framing'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/ui/screens/LibraryScreen.kt" 'dataGeneration' 'Library pagination discards stale filter-generation responses'
if grep -Fq 'onDispose { (state as? PageLoadState.Ready)?.bitmap?.recycle() }' "$READER"; then
  fail 'Reader still manually recycles a bitmap that Compose may be drawing'
fi
pass 'Reader leaves displayed bitmap lifetime to Compose/Android GC'

bash -n "$ROOT_DIR/build-android-apk.sh" || fail 'Root Android build script has Bash syntax errors'
bash -n "$ANDROID/build-apk-docker.sh" || fail 'Android wrapper build script has Bash syntax errors'
bash -n "$ROOT_DIR/scripts/android-public-gateway-smoke.sh" || fail 'Android public gateway smoke script has Bash syntax errors'
pass 'Build scripts pass Bash syntax checks'

validate_xml_with_python() {
  local python_cmd="$1"
  "$python_cmd" - "$ANDROID" <<'PY'
import pathlib, sys, xml.etree.ElementTree as ET
root = pathlib.Path(sys.argv[1])
for path in root.glob('app/src/*/res/**/*.xml'):
    ET.parse(path)
for path in root.glob('app/src/*/AndroidManifest.xml'):
    ET.parse(path)
print('  [ok] Android manifests/resources are well-formed XML')
PY
}

if command -v python3 >/dev/null 2>&1; then
  validate_xml_with_python python3
elif command -v python >/dev/null 2>&1; then
  validate_xml_with_python python
elif command -v xmllint >/dev/null 2>&1; then
  while IFS= read -r -d '' xml; do
    xmllint --noout "$xml" || fail "Malformed Android XML: ${xml#$ROOT_DIR/}"
  done < <(find "$ANDROID/app/src" -type f \( -name '*.xml' -o -name 'AndroidManifest.xml' \) -print0)
  pass 'Android manifests/resources are well-formed XML'
else
  printf '  [defer] Host XML parser unavailable; Docker Gradle Android resource processing will validate XML during the real build.\n'
fi

if command -v kotlinc >/dev/null 2>&1; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  kotlinc \
    "$ANDROID/app/src/main/java/com/mreader/android/core/codec/ProtectedCodecMath.kt" \
    "$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReaderProgressMath.kt" \
    "$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReaderTokenPolicy.kt" \
    "$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReaderVariantPolicy.kt" \
    "$LAYOUT_POLICY" \
    "$MODELS" \
    "$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReadingJournal.kt" \
    -d "$tmp/math.jar"
  [[ -s "$tmp/math.jar" ]] || fail 'Pure Kotlin codec/progress math did not compile'
  pass 'Pure Kotlin codec/progress/token/reading model compiles'
fi


# RC4.66 compile regression: Catalog discovery rows use the actual Series model.
if grep -Fq 'List<SeriesSummary>' "$CATALOG"; then
  fail 'Catalog still references nonexistent SeriesSummary model'
fi
require_text "$CATALOG" 'rows: List<Series>,' 'Catalog Surprise Me action uses the real Series model'
pass 'RC4.66 Catalog compile regression guard passed'

require_text "$SETTINGS" 'AvatarOption("bard"' 'Android settings exposes Bard avatar'
require_text "$SETTINGS" 'AvatarOption("shadow_rogue"' 'Android settings exposes Shadow Rogue avatar'
require_text "$API_ADAPTER" 'SERVER_MAINTENANCE_MESSAGE = "Server under maintenance."' 'Android connection failures collapse to maintenance message'
require_text "$SETTINGS" 'false -> "Server under maintenance."' 'Settings connection status shows maintenance when disconnected'
require_text "$CATALOG" 'val chapterRowHeight = if (compact) 38.dp else 42.dp' 'Latest Updates card uses larger fixed chapter-row alignment'
require_text "$CATALOG" 'chapter.title?.takeIf { it.isNotBlank() } ?: "Latest chapter"' 'Latest Updates exposes aligned latest-chapter title line'
require_text "$CATALOG" 'entry.latestChapters.take(2)' 'Latest Updates shows only the latest two chapters on mobile'

require_text "$ROOT_DIR/db/init.sql" "avatar_key IN ('skull','bard','cleric','fire_wielder','king','paladin','shadow_rogue','sorcerer','swordsman')" 'Fresh database schema accepts the replacement avatar set'
require_text "$ROOT_DIR/db/migrations/043_profile_avatar_set_rc475.sql" "UPDATE users" 'Avatar migration remaps removed avatar keys for existing users'
require_text "$ROOT_DIR/db/migrations/043_profile_avatar_set_rc475.sql" "'shadow_rogue'" 'Avatar migration installs the replacement avatar constraint'
require_text "$PARSERS" 'normalizedAvatarKey' 'Android normalizes legacy avatar keys during rolling upgrades'
require_text "$ROOT_DIR/frontend/src/utils/avatars.ts" 'normalizeAvatarKey' 'Web profile normalizes legacy avatar keys during rolling upgrades'
require_text "$SETTINGS" '.height(226.dp)' 'Android avatar cards use stable fixed geometry'
require_text "$SETTINGS" 'textAlign = TextAlign.Center' 'Android avatar labels are centered consistently'
require_text "$CATALOG" 'modifier = Modifier.width(60.dp)' 'Latest Updates chapter numbers use a wider fixed alignment column'
require_text "$COMMON" 'tint = Ink600' 'Cached cover placeholders avoid per-card loading spinners'
require_text "$API_ADAPTER" 'response.code() in 500..599' 'All server/edge 5xx failures collapse to maintenance messaging'

# RC4.76 avatar/database, Smart Library and top-level navigation integration hardening.
require_text "$ROOT_DIR/db/init.sql" 'CONSTRAINT ck_users_avatar_key CHECK' 'Fresh installs use the canonical named avatar constraint'
require_text "$ROOT_DIR/db/migrations/044_profile_avatar_constraint_repair_rc476.sql" "pg_get_constraintdef(c.oid) ILIKE '%avatar_key%'" 'Avatar repair migration discovers every legacy avatar CHECK constraint'
require_text "$ROOT_DIR/db/migrations/044_profile_avatar_constraint_repair_rc476.sql" 'DROP CONSTRAINT IF EXISTS %I' 'Avatar repair migration drops legacy generated constraint names'
require_text "$ROOT_DIR/db/migrations/044_profile_avatar_constraint_repair_rc476.sql" 'ADD CONSTRAINT ck_users_avatar_key' 'Avatar repair migration installs one canonical constraint'
require_text "$ROOT_DIR/frontend/src/pages/Profile.tsx" 'PROFILE_AVATAR_OPTIONS.map' 'Web profile renders default and themed avatars through one aligned card path'
require_text "$ROOT_DIR/frontend/src/pages/Profile.tsx" 'auto-rows-fr items-stretch' 'Web avatar grid keeps rows/card heights aligned'
require_text "$SETTINGS" 'Modifier.fillMaxWidth().height(38.dp)' 'Android avatar labels use a fixed alignment slot'
require_text "$SETTINGS" 'Modifier.fillMaxWidth().height(48.dp)' 'Android avatar descriptions use a fixed alignment slot'
require_text "$ROOT_DIR/android/app/src/main/java/com/mreader/android/core/repository/MobileContentCacheStore.kt" 'namespace: String = "mreader_content_v1"' 'Mobile metadata cache supports isolated namespaces'
require_text "$REPO" 'mreader_personal_v2_${configStore.namespace}' 'Smart Library cache is isolated from public catalog metadata'
require_text "$REPO" 'cachedSmartLibrary(' 'Repository exposes account-scoped Smart Library stale cache'
require_text "$LIBRARY" 'repository.cachedSmartLibrary(' 'Library restores its account-scoped cache before network revalidation'
require_text "$LIBRARY" 'accountId = accountId' 'Library passes authenticated account identity through Smart Library cache/fetch path'
require_text "$APP_NAV" 'private fun navigateTopLevel' 'Bottom navigation uses one explicit top-level navigation policy'
require_text "$APP_NAV" 'navController.popBackStack(Routes.CATALOG, inclusive = false)' 'Browse taps explicitly return to the existing Catalog root'
require_text "$APP_NAV" 'val selected = atDestination' 'Bottom bar highlights only the actually visible destination'
if grep -Fq 'route == Routes.SERIES && item.route == Routes.CATALOG' "$APP_NAV"; then
  fail 'Series route still falsely marks Browse as selected'
fi
pass 'Series detail no longer impersonates the Browse destination'
require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'SELECT * FROM reading_state_v1' 'Smart Library consumes the Progress-owned reading projection'

require_text "$ROOT_DIR/tests/api/test_03_auth_session_profile.py" 'replacement_avatars[-1]' 'Auth integration test exercises every replacement avatar through the database'

require_text "$REPO" 'fun cachedProfile(): User? = userSnapshot.read()' 'Android preserves last verified account identity for offline Smart Library scope'
require_text "$APP_VIEWMODEL" 'MutableStateFlow<User?>(repository.cachedProfile())' 'App initializes personal UI from encrypted last-known profile'
require_text "$APP_VIEWMODEL" 'repository.clearExpiredSessionState()' 'A real profile 401 clears stale personal session/cache state'
require_text "$APP_VIEWMODEL" 'Keep the encrypted last-known identity' 'Transport failure no longer demotes cached signed-in user to guest'
require_text "$ROOT_DIR/db/migrations/044_profile_avatar_constraint_repair_rc476.sql" "users_avatar_key_check" 'Avatar HTTP-500 repair documents legacy generated constraint'

# RC4.79 shared Smart Library history visibility repair.
require_text "$ROOT_DIR/services/progress_go/internal/httpapi/api.go" '"/api/progress/{seriesSlug}/{chapterSlug}/open"' 'Progress exposes explicit synchronous chapter-open history endpoint'
require_text "$ROOT_DIR/services/progress_go/internal/progress/service.go" 'func (s *Service) RecordOpen' 'Progress service records chapter-open history synchronously'
require_text "$ROOT_DIR/frontend/src/api/client.ts" 'recordChapterOpen:' 'Web API client exposes chapter-open history mutation'
require_text "$API_SERVICE" '@POST("api/progress/{seriesSlug}/{chapterSlug}/open")' 'Android API contract exposes chapter-open history mutation'
require_text "$APP_VIEWMODEL" 'fun recordChapterOpen(manifest: ReaderManifest)' 'Android ViewModel records local/server history immediately'
require_text "$READER" 'appViewModel.recordChapterOpen(loaded)' 'Android reader records Smart Library history after manifest load'
require_text "$ROOT_DIR/db/migrations/048_rc483_current_baseline.sql" 'DROP TABLE IF EXISTS reading_history' 'RC4.83 upgrade migration removes transition reading_history state'
require_text "$ROOT_DIR/services/progress_go/internal/store/store.go" 'FROM chapter_reads cr' 'Progress History reads canonical chapter ledger'

require_text "$ROOT_DIR/tests/api/test_26_reading_commands.py" '/open' 'API regression test exercises synchronous chapter-open history'
require_text "$ROOT_DIR/tests/api/test_06_reader_manifest_history.py" 'library_body["summary"]["history"] >= 1' 'API regression test guards Smart Library unique-series History count'

require_text "$ROOT_DIR/services/social_ts/src/routes.ts" 'WHERE user_id=$1::uuid AND (has_history OR furthest_chapter_id IS NOT NULL)' 'Smart Library History keeps the canonical reading projection user-scoped'


# RC4.83 consolidated reading-state and public-series-metrics contract.
forbid_text "$LIBRARY" 'repository.history(limit = 100, scope = accountId)' 'Android Library does not duplicate Social Smart Library with Progress History'
forbid_text "$LIBRARY" 'historyCountFloor' 'Android History badge uses canonical Smart Library summary directly'
require_text "$REPO" 'suspend fun publicSeriesMetrics(seriesId: String): SeriesSocialMetrics' 'Android repository exposes strictly public series aggregate metrics'
require_text "$CATALOG" 'repository.socialMetricsBatch(metricSeriesIds)' 'Android Browse loads aggregate series metrics for guest-visible cards'
require_text "$COMMON" 'it.subscriptionCount.toString()' 'Android shared series cards display public subscriber/follower count'
require_text "$SERIES" 'var socialMetrics by remember(slug)' 'Android Series separates public aggregate metrics from personal viewer state'
[[ -f "$ROOT_DIR/db/migrations/047_consolidate_reading_state_rc482.sql" ]] || fail 'RC4.82 transition migration 047 is missing from upgrade history'
[[ -f "$ROOT_DIR/db/migrations/048_rc483_current_baseline.sql" ]] || fail 'RC4.83 current-baseline migration missing'
pass 'RC4.83 reading-state upgrade history is packaged'

# RC4.85 reading ownership. These are source contracts, not Android runtime evidence.
READING_REPO="$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReadingRepository.kt"
READING_MODEL="$ANDROID/app/src/main/java/com/mreader/android/core/repository/ReadingJournal.kt"
require_text "$API_SERVICE" '@Header("X-MReader-Account-ID") accountId: String' 'Queued reading commands carry their captured account'
require_text "$READING_REPO" 'if (!save(account)) break' 'Reading transport waits for durable command persistence'
require_text "$READING_MODEL" 'if (!value.accepted) return copy(pauseCode =' 'Rejected acknowledgements retain paused local intent'
require_text "$READING_MODEL" 'sent.id != value.commandId' 'Acknowledgements match command identity'
require_text "$READING_REPO" 'it.chapterId == target.chapterId' 'Resume restore checks the canonical chapter'
require_text "$READER" 'decodedPages[it.pageNumber] == true' 'Completion depends on decoded media evidence'
require_text "$READER" 'userInteracted' 'Late restore is fenced after interaction'
require_text "$PARSERS" 'obj.getInt("contract_version") == 1' 'Unknown Library contracts are rejected'
require_text "$LIBRARY" 'recent = page.recentlyOpened' 'Recently Opened comes from the same Library response'
require_text "$LIBRARY" 'nextOffset = page.offset + page.items.size' 'Pagination advances by server rows, not client deduplication'
require_text "$ANDROID/app/src/main/java/com/mreader/android/core/settings/ServerConfigStore.kt" 'ServerConfig(configuredOrigin, "")' 'API and media share the build-configured origin'
forbid_text "$REPO" 'HistoryMergePolicy' 'Repository has no independent history merge'
forbid_text "$REPO" 'localRecentReads' 'Repository has no competing recent-read owner'

printf '==> Android static integration audit passed (source checks only)\n'
