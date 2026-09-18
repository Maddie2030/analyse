package com.mreader.android.core.model

data class User(
    val id: String,
    val username: String,
    val email: String,
    val role: String,
    val avatarKey: String,
)

data class Genre(val id: Int, val name: String)
data class Tag(val id: Int, val name: String)

data class Chapter(
    val id: String,
    val seriesId: String,
    val chapterNumber: Double,
    val title: String?,
    val slug: String,
    val status: String,
    val pageCount: Int,
)

data class ChapterLink(val slug: String, val chapterNumber: Double)

data class Series(
    val id: String,
    val title: String,
    val slug: String,
    val description: String?,
    val coverImagePath: String?,
    val status: String,
    val genres: List<Genre> = emptyList(),
    val tags: List<Tag> = emptyList(),
    val chapters: List<Chapter> = emptyList(),
    val chapterOffset: Int = 0,
    val chapterLimit: Int = 0,
    val chapterHasMore: Boolean = false,
    val firstChapter: ChapterLink? = null,
)

data class LatestChapterSummary(
    val chapterNumber: Double,
    val title: String?,
    val slug: String,
    val publishedAt: String?,
)

data class DiscoverySeries(
    val series: Series,
    val latestChapters: List<LatestChapterSummary>,
)

data class DiscoveryResponse(
    val popular: List<Series>,
    val recent: List<DiscoverySeries>,
    val newReleases: List<Series>,
)

data class TrendingSeries(
    val series: Series,
    val trendScore: Int,
)

data class TrendingResponse(
    val window: String,
    val items: List<TrendingSeries>,
)


data class EditorPick(
    val id: String,
    val series: Series,
    val label: String?,
    val note: String?,
)

data class Announcement(
    val id: String,
    val title: String,
    val body: String,
    val tone: String,
    val linkUrl: String?,
    val linkLabel: String?,
    val dismissible: Boolean,
)

data class CurationResponse(
    val editorPicks: List<EditorPick>,
    val announcements: List<Announcement>,
)

data class HistoryItem(
    val seriesId: String,
    val seriesTitle: String,
    val seriesSlug: String,
    val chapterId: String,
    val chapterNumber: Double,
    val chapterTitle: String?,
    val chapterSlug: String,
    val readAt: String?,
)

data class SeriesSocialMetrics(
    val seriesId: String,
    val bookmarkCount: Int,
    val subscriptionCount: Int,
    val commentCount: Int,
    val ratingAverage: Double?,
    val ratingCount: Int,
    val userRating: Int?,
)

data class SeriesViewerState(
    val metrics: SeriesSocialMetrics,
    val bookmarked: Boolean,
    val subscribed: Boolean,
)

data class SeriesReadingState(
    val resumeChapterSlug: String?,
    val resumeChapterNumber: Double?,
    val revision: Long,
    val readChapterIds: Set<String>,
    val completedChapterIds: Set<String>,
)

data class ReaderPage(
    val pageNumber: Int,
    val imagePath: String,
    val width: Int?,
    val height: Int?,
    val responsiveImagePath: String?,
    val responsiveWidth: Int?,
    val responsiveHeight: Int?,
    val encodingVersion: Int,
    val encodingRows: Int?,
    val encodingColumns: Int?,
    val encodingSeed: String?,
)

data class ReaderManifest(
    val seriesId: String,
    val seriesTitle: String,
    val seriesSlug: String,
    val chapterId: String,
    val chapterNumber: Double,
    val chapterTitle: String?,
    val chapterSlug: String,
    val pageCount: Int,
    val chapterToken: String,
    val chapterEncodingSeed: String?,
    val pages: List<ReaderPage>,
    val prevChapter: ChapterLink?,
    val nextChapter: ChapterLink?,
)

data class ReadingProgress(
    val lastPage: Int,
    val scrollPosition: Double,
    val updatedAtMillis: Long = 0L,
    val revision: Long = 0L,
    val accepted: Boolean = true,
    val seriesId: String? = null,
    val chapterId: String? = null,
    val sessionGeneration: Long = 0L,
    val commandSequence: Long = 0L,
    val duplicate: Boolean = false,
    val code: String? = null,
    val commandId: String? = null,
)

data class LocalProgressCheckpoint(
    val lastPage: Int,
    val scrollPosition: Double,
    val updatedAtMillis: Long,
    val completed: Boolean = false,
    val generation: Long = 0L,
)



data class CommentItem(
    val id: String,
    val userId: String,
    val authorUsername: String,
    val seriesId: String,
    val chapterId: String?,
    val parentId: String?,
    val content: String,
    val createdAt: String,
    val updatedAt: String,
)

data class CommentPage(
    val items: List<CommentItem>,
    val total: Int,
    val offset: Int,
    val limit: Int,
)

data class NotificationItem(
    val id: String,
    val kind: String,
    val seriesId: String?,
    val chapterId: String?,
    val message: String,
    val isRead: Boolean,
    val createdAt: String,
    val seriesTitle: String?,
    val seriesSlug: String?,
    val chapterNumber: Double?,
    val chapterSlug: String?,
)

data class Bookmark(
    val id: String?,
    val seriesId: String,
)

data class SmartLibraryItem(
    val seriesId: String,
    val seriesTitle: String,
    val seriesSlug: String,
    val seriesCover: String?,
    val seriesStatus: String,
    val bookmarked: Boolean,
    val followed: Boolean,
    val hasHistory: Boolean,
    val bookmarkCreatedAt: String?,
    val followedAt: String?,
    val readAt: String?,
    val resumeChapterId: String?,
    val resumeChapterSlug: String?,
    val resumeChapterNumber: Double?,
    val resumeChapterTitle: String?,
    val furthestChapterId: String?,
    val furthestChapterSlug: String?,
    val furthestChapterNumber: Double?,
    val furthestChapterTitle: String?,
    val nextChapterId: String?,
    val nextChapterSlug: String?,
    val nextChapterNumber: Double?,
    val nextChapterTitle: String?,
    val latestChapterId: String?,
    val latestChapterSlug: String?,
    val latestChapterNumber: Double?,
    val latestChapterTitle: String?,
    val latestPublishedAt: String?,
    val firstChapterId: String?,
    val firstChapterSlug: String?,
    val firstChapterNumber: Double?,
    val firstChapterTitle: String?,
    val publishedChapterCount: Int,
    val unreadChapterCount: Int,
    val readState: String,
    val activityAt: String?,
    val readingRevision: Long = 0,
    val readingAvailable: Boolean = false,
    val readingAction: ReadingAction? = null,
)

data class ReadingAction(val kind: String, val chapterId: String, val chapterSlug: String)
data class LibraryRequest(val scope: String, val state: String, val sort: String, val offset: Int, val limit: Int)

data class SmartLibrarySummary(
    val all: Int = 0,
    val bookmarks: Int = 0,
    val following: Int = 0,
    val history: Int = 0,
    val updates: Int = 0,
    val caughtUp: Int = 0,
    val notStarted: Int = 0,
)

data class SmartLibraryPage(
    val items: List<SmartLibraryItem>,
    val total: Int,
    val offset: Int,
    val limit: Int,
    val hasMore: Boolean,
    val summary: SmartLibrarySummary = SmartLibrarySummary(),
    val contractVersion: Int = 1,
    val generatedAt: String? = null,
    val requestIdentity: LibraryRequest? = null,
    val recentlyOpened: List<SmartLibraryItem> = emptyList(),
    val recentTotal: Int = 0,
)
