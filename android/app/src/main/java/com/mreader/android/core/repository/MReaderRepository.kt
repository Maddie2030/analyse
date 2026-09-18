package com.mreader.android.core.repository

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import com.mreader.android.core.codec.ProtectedPageDecoder
import com.mreader.android.core.model.*
import com.mreader.android.core.network.ApiException
import com.mreader.android.core.network.GatewayDiagnostics
import com.mreader.android.core.network.ConnectionException
import com.mreader.android.core.network.MReaderApiAdapter
import com.mreader.android.core.network.parseCuration
import com.mreader.android.core.network.parseComment
import com.mreader.android.core.network.parseCommentPage
import com.mreader.android.core.network.parseDiscovery
import com.mreader.android.core.network.parseGenres
import com.mreader.android.core.network.parseProgress
import com.mreader.android.core.network.parseReaderManifest
import com.mreader.android.core.network.parseSeries
import com.mreader.android.core.network.parseSeriesArray
import com.mreader.android.core.network.parseSeriesReadingState
import com.mreader.android.core.network.parseSocialMetricsBatch
import com.mreader.android.core.network.parseSmartLibrary
import com.mreader.android.core.network.parseTags
import com.mreader.android.core.network.parseSocialMetrics
import com.mreader.android.core.network.parseTrending
import com.mreader.android.core.network.parseNotifications
import com.mreader.android.core.network.parseUser
import com.mreader.android.core.network.parseViewerState
import com.mreader.android.core.settings.ServerConfig
import com.mreader.android.core.settings.ServerConfigStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.supervisorScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

class MReaderRepository(context: Context) {
    private val appContext = context.applicationContext
    private var authenticationGeneration = 0L
    val configStore = ServerConfigStore(appContext)
    val api = MReaderApiAdapter(appContext, configStore)
    val assetStore = ProtectedAssetStore(appContext)
    val coverStore = CoverImageStore(appContext)
    val reading = ReadingRepository(appContext, configStore.current().baseUrl, api)
    private val userSnapshot = EncryptedUserSnapshotStore(appContext, configStore.namespace)
    val contentCache = MobileContentCacheStore(appContext, "mreader_content_v2_${configStore.namespace}")
    private val personalContentCache = MobileContentCacheStore(appContext, "mreader_personal_v2_${configStore.namespace}")
    private val prefs = appContext.getSharedPreferences("mreader_mobile", Context.MODE_PRIVATE)
    private val chapterTokens = ConcurrentHashMap<String, String>()
    private val tokenLocks = Array(16) { Mutex() }
    private val protectedAssetLocks = Array(32) { Mutex() }
    private val decoderMutex = Mutex()
    // Parsed app-process snapshots sit above the bounded JSON disk cache. They
    // make Reader -> Browse and top-level tab returns render immediately without
    // waiting even for a cacheDir read/JSON parse. Network revalidation still runs.
    private val hotSeriesLists = ConcurrentHashMap<String, List<Series>>()
    private val hotAdvancedSearch = ConcurrentHashMap<String, List<Series>>()
    private val hotTrending = ConcurrentHashMap<String, TrendingResponse>()
    private val hotSeriesDetails = ConcurrentHashMap<String, Series>()
    private val hotSmartLibrary = ConcurrentHashMap<String, SmartLibraryPage>()
    @Volatile private var hotGenres: List<Genre>? = null
    @Volatile private var hotTags: List<Tag>? = null
    @Volatile private var hotDiscovery: DiscoveryResponse? = null
    @Volatile private var hotCuration: CurationResponse? = null

    fun serverConfig(): ServerConfig = configStore.current()

    fun isAnnouncementDismissed(announcementId: String): Boolean =
        prefs.getBoolean(announcementDismissKey(announcementId), false)

    fun dismissAnnouncement(announcementId: String) {
        prefs.edit().putBoolean(announcementDismissKey(announcementId), true).apply()
    }

    private fun announcementDismissKey(announcementId: String): String =
        "announcement_dismissed:${configStore.namespace}:$announcementId"

    private fun clearHotContentCache() {
        hotSeriesLists.clear()
        hotAdvancedSearch.clear()
        hotTrending.clear()
        hotSeriesDetails.clear()
        hotSmartLibrary.clear()
        hotGenres = null
        hotTags = null
        hotDiscovery = null
        hotCuration = null
    }

    /**
     * Process-hot snapshots are an acceleration layer, not an unbounded history
     * of every filter/page a user has ever visited. The disk cache underneath is
     * already bounded; cap these parsed maps too so long browsing sessions cannot
     * gradually retain an arbitrary number of parsed Series objects.
     */
    private fun <T> putHot(map: ConcurrentHashMap<String, T>, key: String, value: T, maxEntries: Int = HOT_CACHE_MAX_ENTRIES) {
        map[key] = value
        while (map.size > maxEntries) {
            val victim = map.keys.firstOrNull { it != key } ?: break
            map.remove(victim)
        }
    }

    suspend fun testServerConfig(baseUrl: String, imageCdnUrl: String): Pair<ServerConfig, GatewayDiagnostics> {
        val candidate = configStore.validate(baseUrl, imageCdnUrl)
        val diagnostics = api.probeGateway(candidate.baseUrl)
        return candidate to diagnostics
    }

    fun cachedProfile(): User? = userSnapshot.read()

    suspend fun profile(): User? {
        val generation = authenticationGeneration
        return try {
            val user = parseUser(api.profile())
            if (generation != authenticationGeneration) throw CancellationException("Authentication changed")
            userSnapshot.write(user)
            user
        } catch (error: ApiException) {
            if (generation != authenticationGeneration) throw CancellationException("Authentication changed")
            if (error.status == 401 || error.status == 403) { userSnapshot.clear(); null } else throw error
        }
    }

    suspend fun register(username: String, email: String, password: String): User {
        val generation = ++authenticationGeneration
        reading.suspendAccount()
        val user = parseUser(api.register(username, email, password))
        if (generation != authenticationGeneration) throw CancellationException("Authentication changed")
        userSnapshot.write(user)
        chapterTokens.clear()
        return user
    }

    suspend fun login(identifier: String, password: String): User {
        val generation = ++authenticationGeneration
        reading.suspendAccount()
        val user = parseUser(api.login(identifier, password))
        if (generation != authenticationGeneration) throw CancellationException("Authentication changed")
        userSnapshot.write(user)
        chapterTokens.clear()
        return user
    }

    suspend fun updateAvatar(avatarKey: String): User =
        parseUser(api.updateProfileAvatar(avatarKey)).also(userSnapshot::write)

    suspend fun clearExpiredSessionState() {
        reading.suspendAccount()
        api.clearSession()
        userSnapshot.clear()
        chapterTokens.clear()
        assetStore.clear()
        personalContentCache.clear()
        hotSmartLibrary.clear()
    }

    suspend fun logout() {
        authenticationGeneration++
        reading.discardPrivateForLogout()
        try {
            api.logout()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            // Clearing the local session remains authoritative even if the best-effort
            // server logout request cannot be completed.
        }
        api.clearSession()
        userSnapshot.clear()
        chapterTokens.clear()
        assetStore.clear()
        personalContentCache.clear()
        hotSmartLibrary.clear()
    }

    private fun listSeriesCacheKey(search: String, offset: Int, limit: Int, sort: String, genreId: Int?): String =
        "catalog|${search.trim().lowercase()}|${if (search.isBlank()) sort else "relevance"}|${genreId ?: "all"}|${offset.coerceAtLeast(0)}|${limit.coerceIn(1, 100)}"

    fun peekListSeries(
        search: String = "",
        offset: Int = 0,
        limit: Int = 30,
        sort: String = if (search.isBlank()) "updated" else "relevance",
        genreId: Int? = null,
    ): List<Series>? = hotSeriesLists[listSeriesCacheKey(search, offset, limit, sort, genreId)]

    suspend fun cachedListSeries(
        search: String = "",
        offset: Int = 0,
        limit: Int = 30,
        sort: String = if (search.isBlank()) "updated" else "relevance",
        genreId: Int? = null,
    ): List<Series>? {
        val key = listSeriesCacheKey(search, offset, limit, sort, genreId)
        hotSeriesLists[key]?.let { return it }
        val parsed = contentCache.read(key)
            ?.let { payload -> runCatching { parseSeriesArray(JSONArray(payload)) }.getOrNull() }
        if (parsed != null) putHot(hotSeriesLists, key, parsed)
        return parsed
    }

    suspend fun listSeries(
        search: String = "",
        offset: Int = 0,
        limit: Int = 30,
        sort: String = if (search.isBlank()) "updated" else "relevance",
        genreId: Int? = null,
    ): List<Series> {
        val safeOffset = offset.coerceAtLeast(0)
        val safeLimit = limit.coerceIn(1, 100)
        val effectiveSort = if (search.isBlank()) sort else "relevance"
        val raw = api.listSeries(
            search = search,
            sort = effectiveSort,
            genreId = genreId,
            offset = safeOffset,
            limit = safeLimit,
        )
        val key = listSeriesCacheKey(search, safeOffset, safeLimit, effectiveSort, genreId)
        val parsed = parseSeriesArray(raw)
        putHot(hotSeriesLists, key, parsed)
        contentCache.write(key, raw.toString())
        return parsed
    }

    fun peekGenres(): List<Genre>? = hotGenres

    suspend fun cachedGenres(): List<Genre>? {
        hotGenres?.let { return it }
        val parsed = contentCache.read("genres")
            ?.let { payload -> runCatching { parseGenres(JSONArray(payload)) }.getOrNull() }
        if (parsed != null) hotGenres = parsed
        return parsed
    }

    suspend fun genres(): List<Genre> {
        val raw = api.genres()
        val parsed = parseGenres(raw)
        hotGenres = parsed
        contentCache.write("genres", raw.toString())
        return parsed
    }

    fun peekTags(): List<Tag>? = hotTags

    suspend fun cachedTags(): List<Tag>? {
        hotTags?.let { return it }
        val parsed = contentCache.read("tags")
            ?.let { payload -> runCatching { parseTags(JSONArray(payload)) }.getOrNull() }
        if (parsed != null) hotTags = parsed
        return parsed
    }

    suspend fun tags(): List<Tag> {
        val raw = api.tags()
        val parsed = parseTags(raw)
        hotTags = parsed
        contentCache.write("tags", raw.toString())
        return parsed
    }

    private fun advancedSearchCacheKey(
        search: String, genreIds: List<Int>, tagIds: List<Int>, status: String?, minRating: Double?,
        sort: String, offset: Int, limit: Int,
    ): String = "advanced|${search.trim().lowercase()}|${genreIds.sorted().joinToString(",")}|${tagIds.sorted().joinToString(",")}|${status.orEmpty()}|${minRating ?: "any"}|$sort|${offset.coerceAtLeast(0)}|${limit.coerceIn(1, 100)}"

    fun peekAdvancedSearch(
        search: String, genreIds: List<Int>, tagIds: List<Int>, status: String?, minRating: Double?,
        sort: String, offset: Int = 0, limit: Int = 20,
    ): List<Series>? = hotAdvancedSearch[
        advancedSearchCacheKey(search, genreIds, tagIds, status, minRating, sort, offset, limit)
    ]

    suspend fun cachedAdvancedSearch(
        search: String, genreIds: List<Int>, tagIds: List<Int>, status: String?, minRating: Double?,
        sort: String, offset: Int = 0, limit: Int = 20,
    ): List<Series>? {
        val key = advancedSearchCacheKey(search, genreIds, tagIds, status, minRating, sort, offset, limit)
        hotAdvancedSearch[key]?.let { return it }
        val parsed = contentCache.read(key)
            ?.let { payload -> runCatching { parseSeriesArray(JSONArray(payload)) }.getOrNull() }
        if (parsed != null) putHot(hotAdvancedSearch, key, parsed)
        return parsed
    }

    suspend fun advancedSearch(
        search: String,
        genreIds: List<Int>,
        tagIds: List<Int>,
        status: String?,
        minRating: Double?,
        sort: String,
        offset: Int = 0,
        limit: Int = 20,
    ): List<Series> {
        val safeOffset = offset.coerceAtLeast(0)
        val safeLimit = limit.coerceIn(1, 100)
        val raw = api.advancedSeries(
            search = search,
            sort = sort,
            genreIds = genreIds,
            tagIds = tagIds,
            status = status,
            minRating = minRating,
            offset = safeOffset,
            limit = safeLimit,
        )
        val key = advancedSearchCacheKey(search, genreIds, tagIds, status, minRating, sort, safeOffset, safeLimit)
        val parsed = parseSeriesArray(raw)
        putHot(hotAdvancedSearch, key, parsed)
        contentCache.write(key, raw.toString())
        return parsed
    }

    suspend fun socialMetricsBatch(seriesIds: List<String>): Map<String, SeriesSocialMetrics> =
        if (seriesIds.isEmpty()) emptyMap() else parseSocialMetricsBatch(api.seriesMetricsBatch(seriesIds))

    fun peekDiscovery(): DiscoveryResponse? = hotDiscovery

    suspend fun cachedDiscovery(): DiscoveryResponse? {
        hotDiscovery?.let { return it }
        val parsed = contentCache.read("discovery")
            ?.let { payload -> runCatching { parseDiscovery(JSONObject(payload)) }.getOrNull() }
        if (parsed != null) hotDiscovery = parsed
        return parsed
    }

    suspend fun discovery(): DiscoveryResponse {
        val raw = api.discovery()
        val parsed = parseDiscovery(raw)
        hotDiscovery = parsed
        contentCache.write("discovery", raw.toString())
        return parsed
    }

    private fun trendingCacheKey(window: String, limit: Int): String = "trending|$window|${limit.coerceIn(1, 25)}"

    fun peekTrending(window: String = "24h", limit: Int = 10): TrendingResponse? =
        hotTrending[trendingCacheKey(window, limit)]

    suspend fun cachedTrending(window: String = "24h", limit: Int = 10): TrendingResponse? {
        val key = trendingCacheKey(window, limit)
        hotTrending[key]?.let { return it }
        val parsed = contentCache.read(key)
            ?.let { payload -> runCatching { parseTrending(JSONObject(payload)) }.getOrNull() }
        if (parsed != null) putHot(hotTrending, key, parsed, HOT_TRENDING_MAX_ENTRIES)
        return parsed
    }

    suspend fun trending(window: String = "24h", limit: Int = 10): TrendingResponse {
        val safeLimit = limit.coerceIn(1, 25)
        val key = trendingCacheKey(window, safeLimit)
        val raw = api.trending(window, safeLimit)
        val parsed = parseTrending(raw)
        putHot(hotTrending, key, parsed, HOT_TRENDING_MAX_ENTRIES)
        contentCache.write(key, raw.toString())
        return parsed
    }

    fun peekCuration(): CurationResponse? = hotCuration

    suspend fun cachedCuration(): CurationResponse? {
        hotCuration?.let { return it }
        val parsed = contentCache.read("curation")
            ?.let { payload -> runCatching { parseCuration(JSONObject(payload)) }.getOrNull() }
        if (parsed != null) hotCuration = parsed
        return parsed
    }

    suspend fun curation(): CurationResponse {
        val raw = api.curation()
        val parsed = parseCuration(raw)
        hotCuration = parsed
        contentCache.write("curation", raw.toString())
        return parsed
    }

    suspend fun history(offset: Int = 0, limit: Int = 10, scope: String? = null): List<HistoryItem> {
        val account = scope ?: return emptyList()
        val page = smartLibrary(accountId = account, scope = "history", state = "all", sort = "activity", offset = offset, limit = limit)
        return page.items.mapNotNull { item ->
            val chapterId = item.resumeChapterId ?: return@mapNotNull null
            val chapterSlug = item.resumeChapterSlug ?: return@mapNotNull null
            HistoryItem(item.seriesId, item.seriesTitle, item.seriesSlug, chapterId,
                item.resumeChapterNumber ?: 0.0, item.resumeChapterTitle, chapterSlug, item.readAt)
        }
    }

    private fun seriesCacheKey(slug: String, chapterOffset: Int, chapterLimit: Int, chapterSearch: String): String =
        "series|${slug.trim().lowercase()}|${chapterSearch.trim().lowercase()}|${chapterOffset.coerceAtLeast(0)}|${chapterLimit.coerceIn(1, 100)}"

    fun peekSeries(
        slug: String,
        chapterOffset: Int = 0,
        chapterLimit: Int = 50,
        chapterSearch: String = "",
    ): Series? = hotSeriesDetails[seriesCacheKey(slug, chapterOffset, chapterLimit, chapterSearch)]

    suspend fun cachedSeries(
        slug: String,
        chapterOffset: Int = 0,
        chapterLimit: Int = 50,
        chapterSearch: String = "",
    ): Series? {
        val key = seriesCacheKey(slug, chapterOffset, chapterLimit, chapterSearch)
        hotSeriesDetails[key]?.let { return it }
        val parsed = contentCache.read(key)
            ?.let { payload -> runCatching { parseSeries(JSONObject(payload)) }.getOrNull() }
        if (parsed != null) putHot(hotSeriesDetails, key, parsed)
        return parsed
    }

    suspend fun getSeries(
        slug: String,
        chapterOffset: Int = 0,
        chapterLimit: Int = 50,
        chapterSearch: String = "",
    ): Series {
        val safeOffset = chapterOffset.coerceAtLeast(0)
        val safeLimit = chapterLimit.coerceIn(1, 100)
        val raw = api.series(
            slug = slug,
            chapterOffset = safeOffset,
            chapterLimit = safeLimit,
            chapterSearch = chapterSearch,
        )
        val key = seriesCacheKey(slug, safeOffset, safeLimit, chapterSearch)
        val parsed = parseSeries(raw)
        putHot(hotSeriesDetails, key, parsed)
        contentCache.write(key, raw.toString())
        return parsed
    }

    suspend fun decodeProtectedPage(
        bytes: ByteArray,
        encoding: ProtectedPageDecoder.Encoding,
        targetWidthPx: Int,
    ): Bitmap = decoderMutex.withLock {
        withContext(Dispatchers.Default) { ProtectedPageDecoder().decode(bytes, encoding, targetWidthPx) }
    }



    private fun protectedAssetIdentity(path: String): String {
        val config = serverConfig()
        return "${config.imageCdnUrl.ifBlank { config.baseUrl }}|${path.trimStart('/')}"
    }

    /**
     * Serializes cache/fetch/write work for one protected object across visible
     * rendering, viewport prefetch, and background chapter caching. This prevents
     * the three reader paths from downloading the same encoded page concurrently.
     */
    suspend fun <T> withProtectedAssetLock(path: String, block: suspend (identity: String) -> T): T {
        val identity = protectedAssetIdentity(path)
        val lock = protectedAssetLocks[(identity.hashCode() and Int.MAX_VALUE) % protectedAssetLocks.size]
        return lock.withLock { block(identity) }
    }

    /**
     * Uses the same protected mobile-adapter contract as visible rendering.
     * Authorization failures refresh the chapter grant and retry the adapter;
     * protected pages never fall back to direct /images requests.
     */
    private suspend fun fetchReaderPageBytes(
        manifest: ReaderManifest,
        page: ReaderPage,
        path: String,
        variant: String,
        initialToken: String,
    ): ByteArray {
        var token = initialToken
        if (token.isBlank()) {
            token = refreshChapterToken(manifest.seriesSlug, manifest.chapterSlug, "")
        }

        suspend fun fetch(grant: String): ByteArray {
            val response = api.mobileReaderPage(
                manifest.seriesSlug, manifest.chapterSlug, page.pageNumber, variant, grant,
            )
            val type = response.contentType.orEmpty().lowercase()
            if (type.startsWith("text/") || type.contains("json") || response.bytes.isEmpty()) {
                throw java.io.IOException("Mobile reader adapter returned invalid protected page data.")
            }
            return response.bytes
        }

        return try {
            fetch(token)
        } catch (auth: ApiException) {
            if (auth.status != 401 && auth.status != 403) throw auth
            val refreshed = refreshChapterToken(manifest.seriesSlug, manifest.chapterSlug, token)
            fetch(refreshed)
        }
    }

    /**
     * Fetches one protected page into the encoded-byte cache without decoding it.
     * Responsive/primary selection follows the same policy as visible rendering.
     */
    private suspend fun cacheReaderPageIndex(
        manifest: ReaderManifest,
        index: Int,
        chapterToken: String,
        screenWidthDp: Int,
        screenWidthPx: Float,
        persistentCacheEnabled: Boolean,
    ) {
        if (index !in manifest.pages.indices) return
        val page = manifest.pages[index]
        if (page.encodingVersion != 4) return
        val responsiveAvailable = !page.responsiveImagePath.isNullOrBlank() &&
            page.responsiveWidth != null && page.responsiveHeight != null
        val preferResponsive = responsiveAvailable && ReaderVariantPolicy.preferResponsive(
            screenWidthDp = screenWidthDp,
            screenWidthPx = screenWidthPx,
            responsiveWidth = page.responsiveWidth,
        )
        val variants = if (preferResponsive) {
            listOf("responsive" to requireNotNull(page.responsiveImagePath), "primary" to page.imagePath)
        } else {
            listOf("primary" to page.imagePath)
        }

        for ((variant, path) in variants) {
            val cached = withProtectedAssetLock(path) { identity ->
                if (assetStore.read(identity, persistent = persistentCacheEnabled) != null) {
                    return@withProtectedAssetLock true
                }
                val token = chapterTokens[tokenKey(manifest.seriesSlug, manifest.chapterSlug)]
                    ?.takeIf { it.isNotBlank() } ?: chapterToken
                val bytes = try {
                    fetchReaderPageBytes(manifest, page, path, variant, token)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Throwable) {
                    return@withProtectedAssetLock false
                }
                if (bytes.isEmpty()) return@withProtectedAssetLock false
                assetStore.write(identity, bytes, persistent = persistentCacheEnabled)
                true
            }
            if (cached) return
            if (variant != "responsive") return
        }
    }

    /**
     * Warms encoded protected bytes around the active page. The window is three
     * ahead/two behind; decoding remains visible-page-only to protect Android heap.
     */
    suspend fun prefetchReaderWindow(
        manifest: ReaderManifest,
        centerPageNumber: Int,
        chapterToken: String,
        screenWidthDp: Int,
        screenWidthPx: Float,
        persistentCacheEnabled: Boolean,
        ahead: Int = 3,
        behind: Int = 2,
    ) {
        if (manifest.pages.isEmpty()) return
        val center = manifest.pages.indexOfFirst { it.pageNumber == centerPageNumber }
            .let { if (it >= 0) it else 0 }
        val order = buildList {
            for (distance in 1..maxOf(ahead, behind)) {
                if (distance <= ahead) add(center + distance)
                if (distance <= behind) add(center - distance)
            }
        }.filter { it in manifest.pages.indices }.distinct()

        supervisorScope {
            val gate = Semaphore(2)
            order.map { index ->
                async(Dispatchers.IO) {
                    gate.withPermit {
                        try {
                            cacheReaderPageIndex(
                                manifest, index, chapterToken, screenWidthDp, screenWidthPx, persistentCacheEnabled,
                            )
                        } catch (cancelled: CancellationException) {
                            throw cancelled
                        } catch (_: Throwable) {
                            // Prefetch is best-effort; visible loading owns errors.
                        }
                    }
                }
            }.awaitAll()
        }
    }

    /**
     * Signed-in-only persistent chapter warm-up. This is launched from the app
     * ViewModel so it may continue while the user returns to Browse. Encoded page
     * bytes are retained by ProtectedAssetStore for at most 24 hours.
     */
    suspend fun cacheReaderChapter(
        manifest: ReaderManifest,
        chapterToken: String,
        screenWidthDp: Int,
        screenWidthPx: Float,
        persistentCacheEnabled: Boolean,
    ) {
        if (!persistentCacheEnabled || manifest.pages.isEmpty()) return
        // Deliberately sequential: the visible page and 3/2 viewport prefetch own
        // the interactive bandwidth. Launching one waiting coroutine per chapter
        // page added scheduler/memory overhead without making this background lane
        // any faster because it was gated to concurrency=1 anyway.
        for (index in manifest.pages.indices) {
            try {
                cacheReaderPageIndex(
                    manifest, index, chapterToken, screenWidthDp, screenWidthPx, persistentCacheEnabled = true,
                )
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                // Full chapter caching is best-effort; reading must never fail because it did.
            }
        }
    }

    suspend fun reader(seriesSlug: String, chapterSlug: String): ReaderManifest {
        val manifest = parseReaderManifest(api.reader(seriesSlug, chapterSlug, visitorId()))
        if (manifest.chapterToken.isNotBlank()) chapterTokens[tokenKey(seriesSlug, chapterSlug)] = manifest.chapterToken
        return manifest
    }

    suspend fun refreshChapterToken(
        seriesSlug: String,
        chapterSlug: String,
        staleToken: String = "",
    ): String {
        val key = tokenKey(seriesSlug, chapterSlug)
        val lock = tokenLocks[(key.hashCode() and Int.MAX_VALUE) % tokenLocks.size]
        return lock.withLock {
            val current = chapterTokens[key]
            if (!current.isNullOrBlank() && current != staleToken) return@withLock current
            val refreshed = api.refreshChapterToken(seriesSlug, chapterSlug).getString("token")
            chapterTokens[key] = refreshed
            refreshed
        }
    }

    suspend fun seriesReadingState(seriesSlug: String): SeriesReadingState? {
        val accountId = reading.view.value.scope?.accountId ?: return null
        val identityVersion = reading.identityVersion()
        if (!reading.isCurrent(accountId, identityVersion)) throw CancellationException("Reading account changed")
        val parsed = try { parseSeriesReadingState(api.seriesReadingState(seriesSlug, accountId)) }
            catch (error: ApiException) { if (error.status == 404) null else throw error }
        if (!reading.isCurrent(accountId, identityVersion)) throw CancellationException("Reading account changed")
        return parsed
    }

    private fun smartLibraryCacheKey(
        accountId: String,
        scope: String,
        state: String,
        sort: String,
        offset: Int,
        limit: Int,
    ): String = "smart-library-v1|${configStore.current().baseUrl}|$accountId|$scope|$state|$sort|${offset.coerceAtLeast(0)}|${limit.coerceIn(1, 100)}"

    fun peekSmartLibrary(
        accountId: String,
        scope: String = "all",
        state: String = "all",
        sort: String = "activity",
        offset: Int = 0,
        limit: Int = 30,
    ): SmartLibraryPage? {
        val key = smartLibraryCacheKey(accountId, scope, state, sort, offset, limit)
        return hotSmartLibrary[key].takeIf { reading.isCurrent(accountId) }
    }

    suspend fun cachedSmartLibrary(
        accountId: String,
        scope: String = "all",
        state: String = "all",
        sort: String = "activity",
        offset: Int = 0,
        limit: Int = 30,
    ): SmartLibraryPage? {
        val key = smartLibraryCacheKey(accountId, scope, state, sort, offset, limit)
        if (!reading.isCurrent(accountId)) return null
        hotSmartLibrary[key]?.let { return it }
        val parsed = personalContentCache.read(key)
            ?.let { payload -> runCatching { parseSmartLibrary(JSONObject(payload)) }.getOrNull() }
        if (parsed != null) putHot(hotSmartLibrary, key, parsed, HOT_SMART_LIBRARY_MAX_ENTRIES)
        return parsed.takeIf { reading.isCurrent(accountId) }
    }

    suspend fun smartLibrary(
        accountId: String,
        scope: String = "all",
        state: String = "all",
        sort: String = "activity",
        offset: Int = 0,
        limit: Int = 30,
    ): SmartLibraryPage {
        val identityVersion = reading.identityVersion()
        if (!reading.isCurrent(accountId, identityVersion)) throw CancellationException("Reading account changed")
        val safeOffset = offset.coerceAtLeast(0)
        val safeLimit = limit.coerceIn(1, 100)
        val key = smartLibraryCacheKey(accountId, scope, state, sort, safeOffset, safeLimit)
        val raw = api.smartLibrary(
            scope = scope,
            state = state,
            sort = sort,
            offset = safeOffset,
            limit = safeLimit,
        )
        val parsed = parseSmartLibrary(raw)
        if (!reading.isCurrent(accountId, identityVersion)) throw CancellationException("Reading account changed")
        require(parsed.requestIdentity == LibraryRequest(scope, state, sort, safeOffset, safeLimit)) { "Library response did not match this request" }
        putHot(hotSmartLibrary, key, parsed, HOT_SMART_LIBRARY_MAX_ENTRIES)
        personalContentCache.write(key, raw.toString())
        if (!reading.isCurrent(accountId, identityVersion)) throw CancellationException("Reading account changed")
        return parsed
    }

    suspend fun bookmark(seriesId: String) {
        api.bookmark(seriesId)
    }

    suspend fun unbookmark(seriesId: String) {
        api.unbookmark(seriesId)
    }

    suspend fun isBookmarked(seriesId: String): Boolean = try {
        api.bookmarkStatus(seriesId).optBoolean("bookmarked")
    } catch (error: ApiException) {
        if (error.status == 401) false else throw error
    }

    suspend fun publicSeriesMetrics(seriesId: String): SeriesSocialMetrics =
        parseSocialMetrics(api.seriesMetrics(seriesId))

    suspend fun viewerState(seriesId: String): SeriesViewerState = try {
        parseViewerState(api.viewerState(seriesId))
    } catch (error: ApiException) {
        if (error.status == 401) {
            val metrics = publicSeriesMetrics(seriesId)
            SeriesViewerState(metrics = metrics, bookmarked = false, subscribed = false)
        } else throw error
    }

    suspend fun subscribe(seriesId: String) { api.subscribe(seriesId) }

    suspend fun unsubscribe(seriesId: String) { api.unsubscribe(seriesId) }

    suspend fun rateSeries(seriesId: String, rating: Int): SeriesSocialMetrics =
        parseSocialMetrics(api.setRating(seriesId, rating))

    suspend fun clearRating(seriesId: String) { api.clearRating(seriesId) }


    suspend fun comments(seriesId: String, chapterId: String? = null, offset: Int = 0, limit: Int = 50): CommentPage =
        parseCommentPage(
            api.comments(
                seriesId = seriesId,
                chapterId = chapterId,
                offset = offset.coerceAtLeast(0),
                limit = limit.coerceIn(1, 100),
            )
        )

    suspend fun createComment(seriesId: String, chapterId: String?, parentId: String?, content: String): CommentItem {
        val normalized = content.trim()
        require(normalized.isNotEmpty()) { "Comment cannot be empty." }
        require(normalized.length <= 2_000) { "Comment is limited to 2,000 characters." }
        return parseComment(api.createComment(seriesId, chapterId, parentId, normalized))
    }

    suspend fun deleteComment(commentId: String) { api.deleteComment(commentId) }


    suspend fun notifications(unreadOnly: Boolean = false, offset: Int = 0, limit: Int = 30): List<NotificationItem> =
        parseNotifications(api.notifications(unreadOnly, offset.coerceAtLeast(0), limit.coerceIn(1, 100)))

    suspend fun notificationCount(): Int = try {
        api.notificationCount()
    } catch (error: ApiException) {
        if (error.status == 401) 0 else throw error
    }

    suspend fun markNotificationRead(notificationId: String) { api.markNotificationRead(notificationId) }

    suspend fun markAllNotificationsRead() { api.markAllNotificationsRead() }

    suspend fun downloadedCacheUsage(): CacheUsage {
        val chapter = assetStore.usage()
        val metadata = contentCache.usage()
        val personal = personalContentCache.usage()
        val covers = coverStore.usage()
        return CacheUsage(
            chapter.bytes + metadata.bytes + personal.bytes + covers.bytes,
            chapter.entries + metadata.entries + personal.entries + covers.entries,
        )
    }

    suspend fun clearDownloadedData() {
        assetStore.clear()
        contentCache.clear()
        personalContentCache.clear()
        clearHotContentCache()
        coverStore.clear()
    }

    private fun tokenKey(seriesSlug: String, chapterSlug: String): String = "$seriesSlug/$chapterSlug"

    private fun visitorId(): String {
        val existing = prefs.getString("reader_visitor", null)
        if (!existing.isNullOrBlank()) return existing
        val created = UUID.randomUUID().toString()
        prefs.edit().putString("reader_visitor", created).apply()
        return created
    }

    private companion object {
        const val HOT_CACHE_MAX_ENTRIES = 48
        const val HOT_TRENDING_MAX_ENTRIES = 8
        const val HOT_SMART_LIBRARY_MAX_ENTRIES = 24
    }
}
