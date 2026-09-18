package com.mreader.android.core.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import com.mreader.android.BuildConfig
import com.mreader.android.core.settings.ServerConfigStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Interceptor
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import retrofit2.Response
import retrofit2.Retrofit
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException
import javax.net.ssl.SSLHandshakeException

class ApiException(
    val status: Int,
    val detail: String,
    val code: String? = null,
    val owner: String? = null,
    val requestId: String? = null,
    val operationId: String? = null,
    val revision: Long? = null,
    val retryable: Boolean? = null,
) : IOException(detail)

private const val SERVER_MAINTENANCE_MESSAGE = "Server under maintenance."

class ConnectionException(message: String = SERVER_MAINTENANCE_MESSAGE, cause: Throwable? = null) : IOException(message, cause)

data class BinaryResponse(
    val bytes: ByteArray,
    val contentType: String?,
    val cacheControl: String?,
)

data class GatewayDiagnostics(
    val baseUrl: String,
    val healthLatencyMs: Long,
    val healthProtocol: String,
    val catalogLatencyMs: Long,
    val authStatus: Int,
    val imageRouteStatus: Int,
) {
    fun summary(): String = if (healthLatencyMs >= 0 && catalogLatencyMs >= 0) "Connected" else SERVER_MAINTENANCE_MESSAGE
}

private data class RawBody(
    val bytes: ByteArray,
    val contentType: String?,
    val cacheControl: String?,
)

/**
 * Standard Android API adapter: Retrofit declares MReader endpoints, OkHttp owns
 * transport/TLS/cookies/pooling/retries, while this class enforces response-size
 * limits and converts service responses into the existing domain parsers.
 *
 * Retrofit instances are cached per origin, so all routes use the installed build's configured origin.
 */
class MReaderApiAdapter(
    context: Context,
    val configStore: ServerConfigStore,
) {
    private val appContext = context.applicationContext
    val cookieJar = EncryptedCookieJar(appContext, configStore.namespace)
    private val connectivity = appContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    private val dispatcher = okhttp3.Dispatcher().apply {
        maxRequests = 16
        maxRequestsPerHost = 8
    }

    private val client = OkHttpClient.Builder()
        .dispatcher(dispatcher)
        .cookieJar(cookieJar)
        .addInterceptor(ClientHeadersInterceptor())
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(40, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .callTimeout(55, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .fastFallback(true)
        .build()

    private val services = ConcurrentHashMap<String, MReaderApiService>()

    suspend fun profile(): JSONObject = jsonObject(callApi { it.profile() })

    suspend fun updateProfileAvatar(avatarKey: String): JSONObject = jsonObject(
        callApi { api -> api.updateProfile(
            JSONObject().apply { put("avatar_key", avatarKey.trim()) }.toString().toRequestBody(JSON)
        ) }
    )

    suspend fun register(username: String, email: String, password: String): JSONObject = jsonObject(
        callApi { api -> api.register(
            JSONObject().apply {
                put("username", username.trim())
                put("email", email.trim())
                put("password", password)
                put("turnstile_token", "")
            }.toString().toRequestBody(JSON)
        ) }
    )

    suspend fun login(identifier: String, password: String): JSONObject = jsonObject(
        callApi { api -> api.login(
            JSONObject().apply {
                put("username_or_email", identifier.trim())
                put("password", password)
                put("turnstile_token", "")
            }.toString().toRequestBody(JSON)
        ) }
    )

    suspend fun logout() {
        unit(callApi { it.logout() })
    }

    suspend fun listSeries(search: String, sort: String, genreId: Int?, offset: Int, limit: Int): JSONArray = jsonArray(
        callApi { it.listSeries(search.trim().takeIf { value -> value.isNotEmpty() }, sort, genreId, offset, limit) }
    )

    suspend fun genres(): JSONArray = jsonArray(callApi { it.genres() })

    suspend fun tags(): JSONArray = jsonArray(callApi { it.tags() })

    suspend fun discovery(): JSONObject = jsonObject(callApi { it.discovery() })

    suspend fun trending(window: String, limit: Int): JSONObject =
        jsonObject(callApi { it.trending(window, limit) })

    suspend fun curation(): JSONObject = jsonObject(callApi { it.curation() })

    suspend fun advancedSeries(
        search: String,
        sort: String,
        genreIds: List<Int>,
        tagIds: List<Int>,
        status: String?,
        minRating: Double?,
        offset: Int,
        limit: Int,
    ): JSONArray = jsonArray(
        callApi { api -> api.advancedSeries(
            search = search.trim().takeIf { it.isNotEmpty() },
            sort = sort,
            genre = genreIds.takeIf { it.isNotEmpty() }?.joinToString(","),
            tag = tagIds.takeIf { it.isNotEmpty() }?.joinToString(","),
            status = status?.trim()?.takeIf { it.isNotEmpty() },
            minRating = minRating,
            offset = offset,
            limit = limit,
        ) }
    )

    suspend fun series(slug: String, chapterOffset: Int, chapterLimit: Int, chapterSearch: String = ""): JSONObject =
        jsonObject(callApi { it.series(slug, chapterOffset, chapterLimit, chapterSearch.trim().takeIf { value -> value.isNotEmpty() }) })

    suspend fun reader(seriesSlug: String, chapterSlug: String, visitorId: String): JSONObject =
        jsonObject(callApi { it.reader(seriesSlug, chapterSlug, visitorId) })

    suspend fun mobileAdapterAvailable(): Boolean = try {
        val response = callApi { it.mobileHealth() }
        val raw = successfulBody(response, MAX_JSON_BYTES).bytes.toString(Charsets.UTF_8)
        raw.contains("reader-mobile-adapter") && raw.contains("v1")
    } catch (cancelled: kotlinx.coroutines.CancellationException) {
        throw cancelled
    } catch (_: Throwable) {
        false
    }

    suspend fun mobileReaderPage(
        seriesSlug: String,
        chapterSlug: String,
        pageNumber: Int,
        variant: String,
        token: String,
    ): BinaryResponse {
        val response = callApi {
            it.mobileReaderPage(
                seriesSlug = seriesSlug,
                chapterSlug = chapterSlug,
                pageNumber = pageNumber.coerceAtLeast(1),
                variant = if (variant == "responsive") "responsive" else "primary",
                token = token,
            )
        }
        val raw = successfulBody(response, MAX_BINARY_BYTES)
        if (raw.bytes.isEmpty()) throw IOException("Mobile reader adapter returned an empty page.")
        return BinaryResponse(raw.bytes, raw.contentType, raw.cacheControl)
    }

    suspend fun refreshChapterToken(seriesSlug: String, chapterSlug: String): JSONObject =
        jsonObject(callApi { it.refreshChapterToken(seriesSlug, chapterSlug) })

    suspend fun progress(seriesSlug: String, chapterSlug: String, accountId: String): JSONObject =
        jsonObject(callApi { it.progress(seriesSlug, chapterSlug, accountId) })

    suspend fun recordChapterOpen(seriesSlug: String, chapterSlug: String, accountId: String, body: String): JSONObject =
        jsonObject(callApi { it.recordChapterOpen(seriesSlug, chapterSlug, accountId, body.toRequestBody(JSON)) })

    suspend fun seriesReadingState(seriesSlug: String, accountId: String): JSONObject =
        jsonObject(callApi { it.seriesReadingState(seriesSlug, accountId) })

    suspend fun commitProgress(seriesSlug: String, chapterSlug: String, accountId: String, body: String): JSONObject =
        jsonObject(callApi { it.commitProgress(seriesSlug, chapterSlug, accountId, body.toRequestBody(JSON)) })

    suspend fun smartLibrary(scope: String, state: String, sort: String, offset: Int, limit: Int): JSONObject =
        jsonObject(callApi { it.smartLibrary(scope = scope, state = state, sort = sort, offset = offset, limit = limit) })

    suspend fun bookmark(seriesId: String) {
        unit(callApi { it.bookmark(seriesId) })
    }

    suspend fun unbookmark(seriesId: String) {
        unit(callApi { it.unbookmark(seriesId) })
    }

    suspend fun bookmarkStatus(seriesId: String): JSONObject = jsonObject(callApi { it.bookmarkStatus(seriesId) })

    suspend fun subscribe(seriesId: String) { unit(callApi { it.subscribe(seriesId) }) }

    suspend fun unsubscribe(seriesId: String) { unit(callApi { it.unsubscribe(seriesId) }) }

    suspend fun viewerState(seriesId: String): JSONObject = jsonObject(callApi { it.viewerState(seriesId) })

    suspend fun seriesMetricsBatch(seriesIds: List<String>): JSONObject = jsonObject(
        callApi { api -> api.seriesMetricsBatch(
            JSONObject().apply { put("series_ids", org.json.JSONArray(seriesIds.distinct().take(100))) }
                .toString().toRequestBody(JSON)
        ) }
    )

    suspend fun seriesMetrics(seriesId: String): JSONObject = jsonObject(callApi { it.seriesMetrics(seriesId) })

    suspend fun setRating(seriesId: String, rating: Int): JSONObject = jsonObject(
        callApi { api -> api.setRating(
            seriesId,
            JSONObject().apply { put("rating", rating.coerceIn(1, 5)) }.toString().toRequestBody(JSON)
        ) }
    )

    suspend fun clearRating(seriesId: String) { unit(callApi { it.clearRating(seriesId) }) }


    suspend fun comments(seriesId: String, chapterId: String?, offset: Int, limit: Int): JSONObject =
        jsonObject(callApi { it.comments(seriesId, chapterId, offset, limit) })

    suspend fun createComment(seriesId: String, chapterId: String?, parentId: String?, content: String): JSONObject =
        jsonObject(
            callApi { api ->
                api.createComment(
                    JSONObject().apply {
                        put("series_id", seriesId)
                        if (chapterId == null) put("chapter_id", JSONObject.NULL) else put("chapter_id", chapterId)
                        if (parentId == null) put("parent_id", JSONObject.NULL) else put("parent_id", parentId)
                        put("content", content.trim())
                    }.toString().toRequestBody(JSON)
                )
            }
        )

    suspend fun deleteComment(commentId: String) { unit(callApi { it.deleteComment(commentId) }) }

    suspend fun notifications(unreadOnly: Boolean, offset: Int, limit: Int): JSONArray =
        jsonArray(callApi { it.notifications(unreadOnly.takeIf { value -> value }, offset, limit) })

    suspend fun notificationCount(): Int =
        jsonObject(callApi { it.notificationCount() }).optInt("unread", 0)

    suspend fun markNotificationRead(notificationId: String) {
        unit(callApi { it.markNotificationRead(notificationId) })
    }

    suspend fun markAllNotificationsRead() {
        unit(callApi { it.markAllNotificationsRead() })
    }

    /**
     * Tests the actual mobile path, not merely the frontend root:
     * health -> catalog route -> auth route. A 401 from profile is success for a guest.
     */
    suspend fun probeGateway(baseUrl: String): GatewayDiagnostics = withContext(Dispatchers.IO) {
        ensureNetworkAvailable()
        try {
            val api = service(baseUrl)

            val healthStarted = System.nanoTime()
            val healthResponse = api.health()
            val healthLatency = elapsedMillis(healthStarted)
            val healthText = text(healthResponse, 4L * 1024L)
            if (!healthText.trim().equals("ok", ignoreCase = true)) {
                throw ConnectionException("Gateway responded, but /healthz did not return MReader health status.")
            }
            val protocol = healthResponse.raw().protocol.toString()

            val catalogStarted = System.nanoTime()
            // Parsing also proves that the public Catalog route returned the expected API shape.
            try {
                jsonArray(api.listSeries(search = null, sort = "updated", genre = null, offset = 0, limit = 1))
            } catch (apiFailure: ApiException) {
                throw ConnectionException("Gateway is reachable, but Catalog API failed with HTTP ${apiFailure.status}: ${apiFailure.detail}", apiFailure)
            }
            val catalogLatency = elapsedMillis(catalogStarted)

            val auth = api.profile()
            if (auth.code() != 401) {
                // 200 means a persisted session was accepted. Any other non-2xx is a real route failure.
                if (!auth.isSuccessful) {
                    val status = auth.code()
                    val detail = runCatching { readLimited(auth.errorBody(), MAX_JSON_BYTES).bytes.toString(Charsets.UTF_8) }.getOrDefault("")
                    throw ConnectionException("Gateway and Catalog are reachable, but Auth API failed with HTTP $status${if (detail.isBlank()) "" else ": ${detail.take(240)}"}.")
                }
                readLimited(auth.body(), MAX_JSON_BYTES)
            } else {
                readLimited(auth.errorBody(), MAX_JSON_BYTES)
            }

            val imageProbeUrl = baseUrl.trimEnd('/') + "/images/__mreader_android_probe__"
            val imageStatus = client.newCall(Request.Builder().url(imageProbeUrl).get().build()).execute().use { response ->
                readLimited(response.body, 32L * 1024L)
                response.code
            }
            if (imageStatus !in 400..499) {
                throw ConnectionException("Gateway APIs are reachable, but the protected image route returned HTTP $imageStatus.")
            }

            GatewayDiagnostics(
                baseUrl = baseUrl.trimEnd('/'),
                healthLatencyMs = healthLatency,
                healthProtocol = protocol,
                catalogLatencyMs = catalogLatency,
                authStatus = auth.code(),
                imageRouteStatus = imageStatus,
            )
        } catch (failure: Throwable) {
            if (failure is ConnectionException || failure is ApiException) throw failure
            throw ConnectionException(describeConnectionFailure(baseUrl, failure), failure)
        }
    }

    suspend fun getBytes(absoluteOrRelativeUrl: String, maxBytes: Long = MAX_BINARY_BYTES): BinaryResponse =
        withContext(Dispatchers.IO) {
            ensureNetworkAvailable()
            val url = if (absoluteOrRelativeUrl.startsWith("http://") || absoluteOrRelativeUrl.startsWith("https://")) {
                absoluteOrRelativeUrl
            } else {
                apiUrl(absoluteOrRelativeUrl)
            }
            try {
                client.newCall(Request.Builder().url(url).get().build()).execute().use { response ->
                    val raw = readLimited(response.body, maxBytes)
                    if (!response.isSuccessful) {
                        val detail = raw.bytes.toString(Charsets.UTF_8).take(512).ifBlank { "HTTP ${response.code}" }
                        throw ApiException(response.code, detail)
                    }
                    if (raw.bytes.isEmpty()) throw IOException("Image response was empty.")
                    BinaryResponse(raw.bytes, raw.contentType, raw.cacheControl)
                }
            } catch (failure: Throwable) {
                if (failure is ApiException) throw failure
                throw ConnectionException(describeConnectionFailure(url, failure), failure)
            }
        }

    fun apiUrl(path: String): String {
        val base = configStore.current().baseUrl
        return "$base/${path.trimStart('/')}"
    }

    fun coverUrl(path: String): String = apiUrl("/images/${path.trimStart('/')}")

    fun webViewCookies(): List<String> {
        val base = configStore.current().baseUrl.trimEnd('/')
        val url = runCatching { base.toHttpUrl() }.getOrNull() ?: return emptyList()
        return cookieJar.loadForRequest(url).map { cookie ->
            buildString {
                append(cookie.name).append('=').append(cookie.value)
                append("; Path=").append(cookie.path)
                if (cookie.secure) append("; Secure")
                if (cookie.httpOnly) append("; HttpOnly")
                append("; SameSite=Lax")
            }
        }
    }

    fun clearSession() {
        cookieJar.clear()
        runCatching {
            android.webkit.CookieManager.getInstance().removeAllCookies(null)
            android.webkit.CookieManager.getInstance().flush()
        }
    }

    fun invalidateBaseUrlCache() {
        services.clear()
        client.connectionPool.evictAll()
    }

    private suspend fun <T> callApi(
        origin: String = configStore.current().baseUrl,
        block: suspend (MReaderApiService) -> T,
    ): T {
        ensureNetworkAvailable()
        return try {
            block(service(origin))
        } catch (failure: Throwable) {
            if (failure is ApiException || failure is ConnectionException) throw failure
            throw ConnectionException(describeConnectionFailure(origin, failure), failure)
        }
    }

    private fun service(origin: String = configStore.current().baseUrl): MReaderApiService {
        val normalized = origin.trimEnd('/')
        return services.getOrPut(normalized) {
            Retrofit.Builder()
                .baseUrl("$normalized/")
                .client(client)
                .build()
                .create(MReaderApiService::class.java)
        }
    }

    private suspend fun jsonObject(response: Response<ResponseBody>): JSONObject {
        val raw = successfulBody(response, MAX_JSON_BYTES)
        val text = raw.bytes.toString(Charsets.UTF_8)
        return if (text.isBlank()) JSONObject() else JSONObject(text)
    }

    private suspend fun jsonArray(response: Response<ResponseBody>): JSONArray {
        val raw = successfulBody(response, MAX_JSON_BYTES)
        return JSONArray(raw.bytes.toString(Charsets.UTF_8))
    }

    private suspend fun text(response: Response<ResponseBody>, maxBytes: Long): String =
        successfulBody(response, maxBytes).bytes.toString(Charsets.UTF_8)

    private suspend fun unit(response: Response<ResponseBody>) {
        successfulBody(response, MAX_JSON_BYTES)
    }

    private suspend fun successfulBody(response: Response<ResponseBody>, maxBytes: Long): RawBody {
        if (!response.isSuccessful) throwApi(response)
        return readLimited(response.body(), maxBytes)
    }

    private suspend fun throwApi(response: Response<ResponseBody>): Nothing {
        if (response.code() in 500..599) {
            response.errorBody()?.close()
            throw ConnectionException()
        }
        val body = readLimited(response.errorBody(), MAX_JSON_BYTES).bytes.toString(Charsets.UTF_8)
        val obj = runCatching { JSONObject(body) }.getOrNull()
        val detail = when {
            obj?.optString("detail")?.isNotBlank() == true -> obj.optString("detail")
            obj?.optString("message")?.isNotBlank() == true -> obj.optString("message")
            else -> "HTTP ${response.code()}"
        }
        val responseRequestId = response.headers()["X-Request-ID"]
            ?: response.raw().request.header("X-Request-ID")
        val responseOwner = response.headers()["X-MReader-Owner"]
        throw ApiException(
            status = response.code(),
            detail = detail,
            code = obj?.optString("code")?.takeIf { it.isNotBlank() },
            owner = obj?.optString("owner")?.takeIf { it.isNotBlank() } ?: responseOwner,
            requestId = obj?.optString("request_id")?.takeIf { it.isNotBlank() } ?: responseRequestId,
            operationId = obj?.optString("operation_id")?.takeIf { it.isNotBlank() },
            revision = obj?.takeIf { it.has("revision") && !it.isNull("revision") }?.optLong("revision"),
            retryable = obj?.takeIf { it.has("retryable") && !it.isNull("retryable") }?.optBoolean("retryable"),
        )
    }

    private fun readLimited(body: ResponseBody?, maxBytes: Long): RawBody {
        if (body == null) return RawBody(ByteArray(0), null, null)
        return body.use { responseBody ->
            val declared = responseBody.contentLength()
            if (declared > maxBytes) throw IOException("HTTP response exceeds the Android safety limit.")
            val source = responseBody.source()
            val buffer = Buffer()
            var total = 0L
            while (true) {
                val remaining = maxBytes + 1L - total
                if (remaining <= 0L) throw IOException("HTTP response exceeds the Android safety limit.")
                val read = source.read(buffer, minOf(16L * 1024L, remaining))
                if (read == -1L) break
                total += read
                if (total > maxBytes) throw IOException("HTTP response exceeds the Android safety limit.")
            }
            RawBody(
                bytes = buffer.readByteArray(),
                contentType = responseBody.contentType()?.toString(),
                cacheControl = null,
            )
        }
    }

    private fun ensureNetworkAvailable() {
        val network = connectivity.activeNetwork ?: throw ConnectionException()
        val capabilities = connectivity.getNetworkCapabilities(network)
            ?: throw ConnectionException()
        if (!capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
            throw ConnectionException()
        }
    }

    private fun describeConnectionFailure(url: String, failure: Throwable): String = SERVER_MAINTENANCE_MESSAGE

    private fun elapsedMillis(startedNanos: Long): Long =
        TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedNanos).coerceAtLeast(0L)

    private inner class ClientHeadersInterceptor : Interceptor {
        override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
            val original = chain.request()
            val builder = original.newBuilder()
                .header("User-Agent", "MReader-Android/${BuildConfig.VERSION_NAME} Android/${Build.VERSION.SDK_INT}")
                .header("X-MReader-Client", "android")
                .header("X-MReader-Client-Version", BuildConfig.VERSION_NAME)
            if (original.header("X-Request-ID").isNullOrBlank()) {
                builder.header("X-Request-ID", UUID.randomUUID().toString())
            }
            if (original.url.encodedPath.startsWith("/api/") || original.url.encodedPath == "/healthz") {
                builder.header("Accept", "application/json, text/plain;q=0.9")
            }
            return chain.proceed(builder.build())
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
        const val MAX_BINARY_BYTES = 32L * 1024L * 1024L
        const val MAX_COVER_BYTES = 8L * 1024L * 1024L
        private const val MAX_JSON_BYTES = 4L * 1024L * 1024L
    }
}
