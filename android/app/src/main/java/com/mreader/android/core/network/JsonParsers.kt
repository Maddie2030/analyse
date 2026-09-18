package com.mreader.android.core.network

import com.mreader.android.core.model.*
import com.mreader.android.core.repository.ReaderTokenPolicy
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant

private val PROFILE_AVATAR_KEYS = setOf(
    "skull", "bard", "cleric", "fire_wielder", "king", "paladin",
    "shadow_rogue", "sorcerer", "swordsman",
)

private fun normalizedAvatarKey(value: String?): String =
    value?.takeIf { it in PROFILE_AVATAR_KEYS } ?: "skull"

internal fun JSONObject.nullableString(name: String): String? =
    if (has(name) && !isNull(name)) optString(name).takeIf { it.isNotBlank() } else null

internal fun JSONObject.nullableInt(name: String): Int? =
    if (has(name) && !isNull(name)) optInt(name) else null

internal fun JSONObject.nullableDouble(name: String): Double? =
    if (has(name) && !isNull(name)) optDouble(name) else null

internal fun parseUser(obj: JSONObject) = User(
    id = obj.getString("id"),
    username = obj.getString("username"),
    email = obj.optString("email"),
    role = obj.optString("role", "user"),
    avatarKey = normalizedAvatarKey(obj.optString("avatar_key", "skull")),
)

internal fun parseSeriesArray(array: JSONArray): List<Series> = buildList {
    for (index in 0 until array.length()) add(parseSeries(array.getJSONObject(index)))
}

internal fun parseSeries(obj: JSONObject): Series {
    val genres = obj.optJSONArray("genres")?.let { array ->
        buildList {
            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                add(Genre(item.optInt("id"), item.optString("name")))
            }
        }
    }.orEmpty()
    val tags = obj.optJSONArray("tags")?.let { array ->
        buildList {
            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                add(Tag(item.optInt("id"), item.optString("name")))
            }
        }
    }.orEmpty()
    val chapters = obj.optJSONArray("chapters")?.let { array ->
        buildList {
            for (i in 0 until array.length()) add(parseChapter(array.getJSONObject(i)))
        }
    }.orEmpty()
    return Series(
        id = obj.getString("id"),
        title = obj.getString("title"),
        slug = obj.getString("slug"),
        description = obj.nullableString("description"),
        coverImagePath = obj.nullableString("cover_image_path"),
        status = obj.optString("status", "ongoing"),
        genres = genres,
        tags = tags,
        chapters = chapters,
        chapterOffset = obj.optInt("chapter_offset", 0),
        chapterLimit = obj.optInt("chapter_limit", chapters.size),
        chapterHasMore = obj.optBoolean("chapter_has_more", false),
        firstChapter = parseChapterLink(obj.optJSONObject("first_chapter")),
    )
}

internal fun parseChapter(obj: JSONObject) = Chapter(
    id = obj.getString("id"),
    seriesId = obj.getString("series_id"),
    chapterNumber = obj.optDouble("chapter_number"),
    title = obj.nullableString("title"),
    slug = obj.getString("slug"),
    status = obj.optString("status"),
    pageCount = obj.optInt("page_count"),
)

internal fun parseChapterLink(obj: JSONObject?): ChapterLink? = obj?.let {
    ChapterLink(
        slug = it.getString("slug"),
        chapterNumber = it.optDouble("chapter_number"),
    )
}

internal fun parseDiscovery(obj: JSONObject): DiscoveryResponse {
    val popular = parseSeriesArray(obj.optJSONArray("popular") ?: JSONArray())
    val fresh = parseSeriesArray(obj.optJSONArray("new") ?: JSONArray())
    val recentArray = obj.optJSONArray("recent") ?: JSONArray()
    val recent = buildList {
        for (i in 0 until recentArray.length()) {
            val item = recentArray.getJSONObject(i)
            val latest = item.optJSONArray("latest_chapters") ?: JSONArray()
            val chapters = buildList {
                for (j in 0 until latest.length()) {
                    val chapter = latest.getJSONObject(j)
                    add(
                        LatestChapterSummary(
                            chapterNumber = chapter.optDouble("chapter_number"),
                            title = chapter.nullableString("title"),
                            slug = chapter.optString("slug"),
                            publishedAt = chapter.nullableString("published_at"),
                        )
                    )
                }
            }
            add(DiscoverySeries(parseSeries(item), chapters))
        }
    }
    return DiscoveryResponse(popular = popular, recent = recent, newReleases = fresh)
}

internal fun parseTrending(obj: JSONObject): TrendingResponse {
    val array = obj.optJSONArray("items") ?: JSONArray()
    val items = buildList {
        for (i in 0 until array.length()) {
            val item = array.getJSONObject(i)
            add(TrendingSeries(parseSeries(item), item.optInt("trend_score")))
        }
    }
    return TrendingResponse(window = obj.optString("window", "24h"), items = items)
}

internal fun parseCuration(obj: JSONObject): CurationResponse {
    val picksArray = obj.optJSONArray("editor_picks") ?: JSONArray()
    val picks = buildList {
        for (i in 0 until picksArray.length()) {
            val item = picksArray.getJSONObject(i)
            val seriesObj = item.optJSONObject("series") ?: continue
            add(
                EditorPick(
                    id = item.optString("id"),
                    series = parseSeries(seriesObj),
                    label = item.nullableString("label"),
                    note = item.nullableString("note"),
                )
            )
        }
    }
    val announcementsArray = obj.optJSONArray("announcements") ?: JSONArray()
    val announcements = buildList {
        for (i in 0 until announcementsArray.length()) {
            val item = announcementsArray.getJSONObject(i)
            add(
                Announcement(
                    id = item.optString("id"),
                    title = item.optString("title"),
                    body = item.optString("body"),
                    tone = item.optString("tone", "info"),
                    linkUrl = item.nullableString("link_url"),
                    linkLabel = item.nullableString("link_label"),
                    dismissible = item.optBoolean("dismissible", true),
                )
            )
        }
    }
    return CurationResponse(editorPicks = picks, announcements = announcements)
}

internal fun parseGenres(array: JSONArray): List<Genre> = buildList {
    for (i in 0 until array.length()) {
        val item = array.getJSONObject(i)
        add(Genre(item.optInt("id"), item.optString("name")))
    }
}

internal fun parseTags(array: JSONArray): List<Tag> = buildList {
    for (i in 0 until array.length()) {
        val item = array.getJSONObject(i)
        add(Tag(item.optInt("id"), item.optString("name")))
    }
}

internal fun parseHistory(array: JSONArray): List<HistoryItem> = buildList {
    for (i in 0 until array.length()) {
        val item = array.getJSONObject(i)
        add(
            HistoryItem(
                seriesId = item.getString("series_id"),
                seriesTitle = item.getString("series_title"),
                seriesSlug = item.getString("series_slug"),
                chapterId = item.getString("chapter_id"),
                chapterNumber = item.optDouble("chapter_number"),
                chapterTitle = item.nullableString("chapter_title"),
                chapterSlug = item.getString("chapter_slug"),
                readAt = item.nullableString("read_at"),
            )
        )
    }
}

internal fun parseSocialMetrics(obj: JSONObject): SeriesSocialMetrics = SeriesSocialMetrics(
    seriesId = obj.optString("series_id"),
    bookmarkCount = obj.optInt("bookmark_count"),
    subscriptionCount = obj.optInt("subscription_count"),
    commentCount = obj.optInt("comment_count"),
    ratingAverage = obj.nullableDouble("rating_average"),
    ratingCount = obj.optInt("rating_count"),
    userRating = obj.nullableInt("user_rating"),
)

internal fun parseSocialMetricsBatch(obj: JSONObject): Map<String, SeriesSocialMetrics> {
    val array = obj.optJSONArray("items") ?: JSONArray()
    return buildMap {
        for (i in 0 until array.length()) {
            val metric = parseSocialMetrics(array.getJSONObject(i))
            if (metric.seriesId.isNotBlank()) put(metric.seriesId, metric)
        }
    }
}

internal fun parseViewerState(obj: JSONObject): SeriesViewerState = SeriesViewerState(
    metrics = parseSocialMetrics(obj),
    bookmarked = obj.optBoolean("bookmarked"),
    subscribed = obj.optBoolean("subscribed"),
)

internal fun parseSeriesReadingState(obj: JSONObject): SeriesReadingState {
    fun ids(name: String): Set<String> {
        val array = obj.optJSONArray(name) ?: JSONArray()
        return buildSet {
            for (i in 0 until array.length()) add(array.optString(i))
        }
    }
    return SeriesReadingState(
        resumeChapterSlug = obj.nullableString("resume_chapter_slug"),
        resumeChapterNumber = obj.nullableDouble("resume_chapter_number"),
        revision = obj.optLong("revision", 0L).coerceAtLeast(0L),
        readChapterIds = ids("read_chapter_ids"),
        completedChapterIds = ids("completed_chapter_ids"),
    )
}

internal fun parseReaderManifest(obj: JSONObject): ReaderManifest {
    val chapterSeed = obj.nullableString("chapter_encoding_seed")
    val array = obj.getJSONArray("pages")
    val manifestToken = ReaderTokenPolicy.choose(obj.nullableString("chapter_token"))
    val pages = buildList {
        for (i in 0 until array.length()) {
            val page = array.getJSONObject(i)
            add(
                ReaderPage(
                    pageNumber = page.getInt("page_number"),
                    imagePath = page.getString("image_path"),
                    width = page.nullableInt("width"),
                    height = page.nullableInt("height"),
                    responsiveImagePath = page.nullableString("responsive_image_path"),
                    responsiveWidth = page.nullableInt("responsive_width"),
                    responsiveHeight = page.nullableInt("responsive_height"),
                    encodingVersion = page.optInt("encoding_version"),
                    encodingRows = page.nullableInt("encoding_rows"),
                    encodingColumns = page.nullableInt("encoding_columns"),
                    encodingSeed = page.nullableString("encoding_seed") ?: chapterSeed,
                )
            )
        }
    }
    return ReaderManifest(
        seriesId = obj.getString("series_id"),
        seriesTitle = obj.getString("series_title"),
        seriesSlug = obj.getString("series_slug"),
        chapterId = obj.getString("chapter_id"),
        chapterNumber = obj.optDouble("chapter_number"),
        chapterTitle = obj.nullableString("chapter_title"),
        chapterSlug = obj.getString("chapter_slug"),
        pageCount = obj.optInt("page_count", pages.size),
        chapterToken = manifestToken,
        chapterEncodingSeed = chapterSeed,
        pages = pages,
        prevChapter = parseChapterLink(obj.optJSONObject("prev_chapter")),
        nextChapter = parseChapterLink(obj.optJSONObject("next_chapter")),
    )
}

internal fun parseProgress(obj: JSONObject) = ReadingProgress(
    lastPage = obj.optInt("last_page", 1),
    scrollPosition = obj.optDouble("scroll_position", 0.0).coerceIn(0.0, 1.0),
    updatedAtMillis = obj.nullableString("updated_at")?.let { raw ->
        runCatching { Instant.parse(raw).toEpochMilli() }.getOrDefault(0L)
    } ?: 0L,
    revision = obj.getLong("revision").also { require(it in 0L..9_007_199_254_740_991L) },
    accepted = obj.optBoolean("accepted", true),
    seriesId = obj.nullableString("series_id"),
    chapterId = obj.nullableString("chapter_id"),
    sessionGeneration = obj.getLong("session_generation").also { require(it in 0L..9_007_199_254_740_991L) },
    commandSequence = obj.getLong("command_sequence").also { require(it in 0L..9_007_199_254_740_991L) },
    duplicate = obj.optBoolean("duplicate", false),
    code = obj.nullableString("code"),
    commandId = obj.nullableString("command_id"),
)

internal fun parseLibraryItem(item: JSONObject): SmartLibraryItem = SmartLibraryItem(
    seriesId = item.getString("series_id"),
    seriesTitle = item.getString("series_title"),
    seriesSlug = item.getString("series_slug"),
    seriesCover = item.nullableString("series_cover"),
    seriesStatus = item.optString("series_status", "ongoing"),
    bookmarked = item.optBoolean("bookmarked"),
    followed = item.optBoolean("followed"),
    hasHistory = item.optBoolean("has_history"),
    bookmarkCreatedAt = item.nullableString("bookmark_created_at"),
    followedAt = item.nullableString("followed_at"),
    readAt = item.nullableString("read_at"),
    resumeChapterId = item.nullableString("resume_chapter_id"),
    resumeChapterSlug = item.nullableString("resume_chapter_slug"),
    resumeChapterNumber = item.nullableDouble("resume_chapter_number"),
    resumeChapterTitle = item.nullableString("resume_chapter_title"),
    furthestChapterId = item.nullableString("furthest_chapter_id"),
    furthestChapterSlug = item.nullableString("furthest_chapter_slug"),
    furthestChapterNumber = item.nullableDouble("furthest_chapter_number"),
    furthestChapterTitle = item.nullableString("furthest_chapter_title"),
    nextChapterId = item.nullableString("next_chapter_id"),
    nextChapterSlug = item.nullableString("next_chapter_slug"),
    nextChapterNumber = item.nullableDouble("next_chapter_number"),
    nextChapterTitle = item.nullableString("next_chapter_title"),
    latestChapterId = item.nullableString("latest_chapter_id"),
    latestChapterSlug = item.nullableString("latest_chapter_slug"),
    latestChapterNumber = item.nullableDouble("latest_chapter_number"),
    latestChapterTitle = item.nullableString("latest_chapter_title"),
    latestPublishedAt = item.nullableString("latest_published_at"),
    firstChapterId = item.nullableString("first_chapter_id"),
    firstChapterSlug = item.nullableString("first_chapter_slug"),
    firstChapterNumber = item.nullableDouble("first_chapter_number"),
    firstChapterTitle = item.nullableString("first_chapter_title"),
    publishedChapterCount = item.optInt("published_chapter_count"),
    unreadChapterCount = item.optInt("unread_chapter_count"),
    readState = item.optString("read_state", "not_started"),
    activityAt = item.nullableString("activity_at"),
    readingRevision = item.getLong("reading_revision"),
    readingAvailable = item.getBoolean("reading_available"),
    readingAction = item.optJSONObject("reading_action")?.let {
        ReadingAction(it.getString("kind"), it.getString("chapter_id"), it.getString("chapter_slug"))
    },
)

internal fun parseSmartLibrary(obj: JSONObject): SmartLibraryPage {
    require(obj.getInt("contract_version") == 1) { "Library contract is unavailable. Update the app and server together." }
    val array = obj.getJSONArray("items")
    val recent = obj.getJSONObject("recently_opened")
    val recentItems = recent.getJSONArray("items")
    require(recentItems.length() <= 12)
    val identity = obj.getJSONObject("request_identity")
    val summaryObj = obj.getJSONObject("summary")
    return SmartLibraryPage(
        items = (0 until array.length()).map { parseLibraryItem(array.getJSONObject(it)) },
        total = obj.getInt("total"), offset = obj.getInt("offset"), limit = obj.getInt("limit"),
        hasMore = obj.getBoolean("has_more"),
        summary = SmartLibrarySummary(
            all = summaryObj.getInt("all"), bookmarks = summaryObj.getInt("bookmarks"),
            following = summaryObj.getInt("following"), history = summaryObj.getInt("history"),
            updates = summaryObj.getInt("updates"), caughtUp = summaryObj.getInt("caught_up"),
            notStarted = summaryObj.getInt("not_started"),
        ),
        contractVersion = 1, generatedAt = obj.getString("generated_at"),
        requestIdentity = LibraryRequest(identity.getString("scope"), identity.getString("state"),
            identity.getString("sort"), identity.getInt("offset"), identity.getInt("limit")),
        recentlyOpened = (0 until recentItems.length()).map { parseLibraryItem(recentItems.getJSONObject(it)) },
        recentTotal = recent.getInt("total"),
    )
}


internal fun parseComment(obj: JSONObject): CommentItem = CommentItem(
    id = obj.getString("id"),
    userId = obj.getString("user_id"),
    authorUsername = obj.optString("author_username", "Reader"),
    seriesId = obj.getString("series_id"),
    chapterId = obj.nullableString("chapter_id"),
    parentId = obj.nullableString("parent_id"),
    content = obj.optString("content"),
    createdAt = obj.optString("created_at"),
    updatedAt = obj.optString("updated_at"),
)

internal fun parseCommentPage(obj: JSONObject): CommentPage {
    val array = obj.optJSONArray("items") ?: JSONArray()
    val items = buildList {
        for (i in 0 until array.length()) add(parseComment(array.getJSONObject(i)))
    }
    return CommentPage(
        items = items,
        total = obj.optInt("total", items.size),
        offset = obj.optInt("offset", 0),
        limit = obj.optInt("limit", items.size),
    )
}


internal fun parseNotifications(array: JSONArray): List<NotificationItem> = buildList {
    for (i in 0 until array.length()) {
        val item = array.getJSONObject(i)
        add(
            NotificationItem(
                id = item.getString("id"),
                kind = item.optString("kind", "notification"),
                seriesId = item.nullableString("series_id"),
                chapterId = item.nullableString("chapter_id"),
                message = item.optString("message"),
                isRead = item.optBoolean("is_read"),
                createdAt = item.optString("created_at"),
                seriesTitle = item.nullableString("series_title"),
                seriesSlug = item.nullableString("series_slug"),
                chapterNumber = item.nullableDouble("chapter_number"),
                chapterSlug = item.nullableString("chapter_slug"),
            )
        )
    }
}
