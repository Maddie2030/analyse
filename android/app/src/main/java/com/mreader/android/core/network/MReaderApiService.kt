package com.mreader.android.core.network

import okhttp3.RequestBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

/** Declarative MReader HTTP contract used by Retrofit. */
interface MReaderApiService {
    @GET("healthz")
    suspend fun health(): Response<ResponseBody>

    @GET("api/auth/profile")
    suspend fun profile(): Response<ResponseBody>

    @PUT("api/auth/profile")
    suspend fun updateProfile(@Body body: RequestBody): Response<ResponseBody>

    @POST("api/auth/register")
    suspend fun register(@Body body: RequestBody): Response<ResponseBody>

    @POST("api/auth/login")
    suspend fun login(@Body body: RequestBody): Response<ResponseBody>

    @POST("api/auth/logout")
    suspend fun logout(): Response<ResponseBody>

    @GET("api/catalog/series")
    suspend fun listSeries(
        @Query("search") search: String?,
        @Query("sort") sort: String,
        @Query("genre") genre: Int?,
        @Query("offset") offset: Int,
        @Query("limit") limit: Int,
    ): Response<ResponseBody>

    @GET("api/catalog/genres")
    suspend fun genres(): Response<ResponseBody>

    @GET("api/catalog/tags")
    suspend fun tags(): Response<ResponseBody>

    @GET("api/catalog/discover")
    suspend fun discovery(): Response<ResponseBody>

    @GET("api/catalog/trending")
    suspend fun trending(
        @Query("window") window: String,
        @Query("limit") limit: Int,
    ): Response<ResponseBody>

    @GET("api/catalog/curation")
    suspend fun curation(): Response<ResponseBody>

    @GET("api/catalog/series")
    suspend fun advancedSeries(
        @Query("search") search: String?,
        @Query("sort") sort: String,
        @Query("genre") genre: String?,
        @Query("tag") tag: String?,
        @Query("status") status: String?,
        @Query("min_rating") minRating: Double?,
        @Query("offset") offset: Int,
        @Query("limit") limit: Int,
    ): Response<ResponseBody>

    @GET("api/catalog/series/{slug}")
    suspend fun series(
        @Path("slug") slug: String,
        @Query("chapter_offset") chapterOffset: Int,
        @Query("chapter_limit") chapterLimit: Int,
        @Query("chapter_search") chapterSearch: String?,
    ): Response<ResponseBody>

    @GET("api/mobile/v1/health")
    suspend fun mobileHealth(): Response<ResponseBody>

    @GET("api/mobile/v1/reader/{seriesSlug}/{chapterSlug}/page/{pageNumber}")
    suspend fun mobileReaderPage(
        @Path("seriesSlug") seriesSlug: String,
        @Path("chapterSlug") chapterSlug: String,
        @Path("pageNumber") pageNumber: Int,
        @Query("variant") variant: String,
        @Query("token") token: String,
    ): Response<ResponseBody>

    @GET("api/reader/{seriesSlug}/{chapterSlug}")
    suspend fun reader(
        @Path("seriesSlug") seriesSlug: String,
        @Path("chapterSlug") chapterSlug: String,
        @Header("X-MReader-Visitor") visitorId: String,
    ): Response<ResponseBody>

    @GET("api/token/chapter/{seriesSlug}/{chapterSlug}")
    suspend fun refreshChapterToken(
        @Path("seriesSlug") seriesSlug: String,
        @Path("chapterSlug") chapterSlug: String,
    ): Response<ResponseBody>

    @GET("api/progress/{seriesSlug}/{chapterSlug}")
    suspend fun progress(
        @Path("seriesSlug") seriesSlug: String,
        @Path("chapterSlug") chapterSlug: String,
        @Header("X-MReader-Account-ID") accountId: String,
    ): Response<ResponseBody>

    @POST("api/progress/{seriesSlug}/{chapterSlug}/open")
    suspend fun recordChapterOpen(
        @Path("seriesSlug") seriesSlug: String,
        @Path("chapterSlug") chapterSlug: String,
        @Header("X-MReader-Account-ID") accountId: String,
        @Body body: RequestBody,
    ): Response<ResponseBody>

    @GET("api/progress/history")
    suspend fun history(
        @Query("offset") offset: Int,
        @Query("limit") limit: Int,
    ): Response<ResponseBody>

    @GET("api/progress/series/{seriesSlug}/state")
    suspend fun seriesReadingState(
        @Path("seriesSlug") seriesSlug: String,
        @Header("X-MReader-Account-ID") accountId: String,
    ): Response<ResponseBody>

    @POST("api/progress/{seriesSlug}/{chapterSlug}/commit")
    suspend fun commitProgress(
        @Path("seriesSlug") seriesSlug: String,
        @Path("chapterSlug") chapterSlug: String,
        @Header("X-MReader-Account-ID") accountId: String,
        @Body body: RequestBody,
    ): Response<ResponseBody>

    @GET("api/social/library")
    suspend fun smartLibrary(
        @Query("scope") scope: String,
        @Query("state") state: String,
        @Query("sort") sort: String,
        @Query("offset") offset: Int,
        @Query("limit") limit: Int,
    ): Response<ResponseBody>

    @POST("api/social/bookmarks/{seriesId}")
    suspend fun bookmark(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @DELETE("api/social/bookmarks/{seriesId}")
    suspend fun unbookmark(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @GET("api/social/bookmarks/{seriesId}/status")
    suspend fun bookmarkStatus(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @POST("api/social/subscriptions/{seriesId}")
    suspend fun subscribe(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @DELETE("api/social/subscriptions/{seriesId}")
    suspend fun unsubscribe(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @GET("api/social/series/{seriesId}/viewer-state")
    suspend fun viewerState(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @POST("api/social/series/metrics-batch")
    suspend fun seriesMetricsBatch(@Body body: RequestBody): Response<ResponseBody>

    @GET("api/social/series/{seriesId}/metrics")
    suspend fun seriesMetrics(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @PUT("api/social/series/{seriesId}/rating")
    suspend fun setRating(
        @Path("seriesId") seriesId: String,
        @Body body: RequestBody,
    ): Response<ResponseBody>

    @DELETE("api/social/series/{seriesId}/rating")
    suspend fun clearRating(@Path("seriesId") seriesId: String): Response<ResponseBody>

    @GET("api/social/comments")
    suspend fun comments(
        @Query("seriesId") seriesId: String,
        @Query("chapterId") chapterId: String?,
        @Query("offset") offset: Int,
        @Query("limit") limit: Int,
    ): Response<ResponseBody>

    @POST("api/social/comments")
    suspend fun createComment(@Body body: RequestBody): Response<ResponseBody>

    @DELETE("api/social/comments/{commentId}")
    suspend fun deleteComment(@Path("commentId") commentId: String): Response<ResponseBody>

    @GET("api/notifications")
    suspend fun notifications(
        @Query("unread_only") unreadOnly: Boolean?,
        @Query("offset") offset: Int,
        @Query("limit") limit: Int,
    ): Response<ResponseBody>

    @GET("api/notifications/count")
    suspend fun notificationCount(): Response<ResponseBody>

    @POST("api/notifications/{notificationId}/read")
    suspend fun markNotificationRead(@Path("notificationId") notificationId: String): Response<ResponseBody>

    @POST("api/notifications/read-all")
    suspend fun markAllNotificationsRead(): Response<ResponseBody>
}
