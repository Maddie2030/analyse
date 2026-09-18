package com.mreader.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mreader.android.core.model.*
import com.mreader.android.core.repository.MReaderRepository
import com.mreader.android.core.repository.bestEffortOrNull
import com.mreader.android.ui.components.*
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val CHAPTER_PAGE_SIZE = 20

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SeriesScreen(
    repository: MReaderRepository,
    user: StateFlow<User?>,
    refreshEpoch: Long,
    slug: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onRead: (String, String) -> Unit,
    onLogin: () -> Unit,
    onContentChanged: () -> Unit,
) {
    val currentUser by user.collectAsStateWithLifecycle()
    val initialSeries = remember(slug) { repository.peekSeries(slug, 0, CHAPTER_PAGE_SIZE, "") }
    var series by remember(slug) { mutableStateOf(initialSeries) }
    var socialMetrics by remember(slug) { mutableStateOf<SeriesSocialMetrics?>(null) }
    var viewerState by remember(slug, currentUser?.id) { mutableStateOf<SeriesViewerState?>(null) }
    var readingState by remember(slug, currentUser?.id) { mutableStateOf<SeriesReadingState?>(null) }
    var loading by remember(slug) { mutableStateOf(initialSeries == null) }
    var chapterLoading by remember(slug) { mutableStateOf(false) }
    var relationshipBusy by remember(slug) { mutableStateOf(false) }
    var ratingBusy by remember(slug) { mutableStateOf(false) }
    var error by remember(slug) { mutableStateOf<String?>(null) }
    var actionError by remember(slug) { mutableStateOf<String?>(null) }
    var chapterPageError by remember(slug) { mutableStateOf<String?>(null) }
    var reloadKey by remember(slug) { mutableIntStateOf(0) }
    var chapterQuery by rememberSaveable(slug) { mutableStateOf("") }
    var chapterSearchQuery by rememberSaveable(slug) { mutableStateOf("") }
    var chapterOffset by rememberSaveable(slug) { mutableIntStateOf(0) }
    val readingView by repository.reading.view.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()
    var displayedChapterKey by remember(slug) {
        mutableStateOf(if (initialSeries != null) "$slug||0" else null)
    }

    LaunchedEffect(chapterQuery) {
        delay(250L)
        val normalized = chapterQuery.trim()
        chapterOffset = 0
        chapterSearchQuery = normalized
    }

    LaunchedEffect(slug, chapterOffset, chapterSearchQuery, refreshEpoch, reloadKey) {
        val requestKey = "$slug|${chapterSearchQuery.trim().lowercase()}|$chapterOffset"
        val cached = repository.cachedSeries(
            slug = slug,
            chapterOffset = chapterOffset,
            chapterLimit = CHAPTER_PAGE_SIZE,
            chapterSearch = chapterSearchQuery,
        )

        if (cached != null) {
            series = cached
            displayedChapterKey = requestKey
            loading = false
            chapterLoading = false
        } else if (series == null) {
            loading = true
        } else if (displayedChapterKey != requestKey) {
            // Keep the series hero/social context, but never show chapters from
            // the previous page/search under a newly selected page number.
            series = series?.copy(
                chapters = emptyList(),
                chapterOffset = chapterOffset,
                chapterLimit = CHAPTER_PAGE_SIZE,
                chapterHasMore = false,
            )
            chapterLoading = true
        }

        error = null
        chapterPageError = null
        try {
            val loaded = repository.getSeries(
                slug = slug,
                chapterOffset = chapterOffset,
                chapterLimit = CHAPTER_PAGE_SIZE,
                chapterSearch = chapterSearchQuery,
            )
            series = loaded
            displayedChapterKey = requestKey
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Throwable) {
            if (series == null) error = failure.message ?: "Could not load this series."
            else chapterPageError = failure.message ?: "Could not refresh this chapter page."
        } finally {
            loading = false
            chapterLoading = false
        }
    }

    LaunchedEffect(series?.id, currentUser?.id, refreshEpoch, reloadKey) {
        val item = series ?: return@LaunchedEffect
        coroutineScope {
            // Public aggregate metrics never depend on an authenticated session.
            // Personal relationship/rating state is an independent enrichment.
            val publicMetricsDeferred = async { bestEffortOrNull { repository.publicSeriesMetrics(item.id) } }
            val viewerDeferred = async {
                if (currentUser == null) null else bestEffortOrNull { repository.viewerState(item.id) }
            }
            val readingDeferred = async {
                if (currentUser == null) null else bestEffortOrNull { repository.seriesReadingState(item.slug) }
            }
            val personal = viewerDeferred.await()
            viewerState = personal
            socialMetrics = personal?.metrics ?: publicMetricsDeferred.await()
            readingState = readingDeferred.await()
        }
    }

    Scaffold(
        containerColor = Ink950,
        topBar = {
            TopAppBar(
                title = { Text(series?.title ?: "Series", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Ink900.copy(alpha = 0.97f), titleContentColor = Ink50, navigationIconContentColor = Ink200),
            )
        },
    ) { inner ->
        val bottom = contentPadding.calculateBottomPadding()
        when {
            loading -> Box(Modifier.fillMaxSize().padding(inner), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Brand400) }
            error != null -> Box(Modifier.fillMaxSize().padding(inner).padding(24.dp), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(error.orEmpty(), color = MaterialTheme.colorScheme.error)
                    OutlinedButton(onClick = { reloadKey++ }) { Text("Retry") }
                }
            }
            series != null -> {
                val item = requireNotNull(series)
                // The Catalog service owns chapter filtering and pagination. Keeping the
                // returned page intact avoids Android applying a second filter to stale rows
                // while the debounced server request is in flight.
                val visibleChapters = item.chapters
                val pending = readingView.pending(item.id)
                val resume = pending?.let { ChapterLink(it.target.chapterSlug, it.target.chapterNumber) }
                    ?: readingState?.resumeChapterSlug?.let { slugValue -> ChapterLink(slugValue, readingState?.resumeChapterNumber ?: 0.0) }
                val start = resume ?: item.firstChapter ?: item.chapters.minByOrNull { it.chapterNumber }?.let { ChapterLink(it.slug, it.chapterNumber) }

                ResponsiveFrame(modifier = Modifier.background(Ink950), maxContentWidth = 900.dp) { edgePadding ->
                    LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(start = edgePadding, top = inner.calculateTopPadding() + 14.dp, end = edgePadding, bottom = bottom + 30.dp),
                    verticalArrangement = Arrangement.spacedBy(13.dp),
                ) {
                    item(key = "reading-sync") {
                        ReadingSyncStatus(repository, readingView, item.id)
                        if (currentUser != null && readingState == null) Text("Saved reading state is unavailable.", style = MaterialTheme.typography.bodySmall)
                    }
                    item(key = "series-hero") {
                        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            NetworkImage(
                                repository,
                                item.coverImagePath?.let(repository.api::coverUrl),
                                item.title,
                                Modifier.width(160.dp).aspectRatio(2f / 3f).clip(RoundedCornerShape(14.dp)),
                                ContentScale.Crop,
                            )
                            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                                Text(item.title, style = MaterialTheme.typography.headlineMedium, color = Ink50)
                                StableHorizontalShelf(spacing = 7.dp) {
                                    item { StatusPill(item.status) }
                                    items(item.genres, key = { "genre-${it.id}" }) { genre -> TagChip(genre.name) }
                                }
                                if (item.tags.isNotEmpty()) LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    items(item.tags, key = { "tag-${it.id}" }) { TagChip(it.name, accent = true) }
                                }
                                if (!item.description.isNullOrBlank()) Text(item.description, style = MaterialTheme.typography.bodyMedium, color = Ink300)
                                Button(
                                    onClick = { start?.let { onRead(item.slug, it.slug) } },
                                    enabled = start != null,
                                    colors = ButtonDefaults.buttonColors(containerColor = Brand600),
                                    shape = RoundedCornerShape(12.dp),
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Icon(Icons.Default.PlayArrow, null); Spacer(Modifier.width(6.dp))
                                    Text(if (start == null) "No chapters" else if (resume != null) "CONTINUE CH. ${formatChapterNumber(resume.chapterNumber)}" else if (currentUser != null && readingState == null) "READ FIRST CHAPTER" else "START READING")
                                }
                            }
                        }
                    }

                    socialMetrics?.let { metrics ->
                        item(key = "social-metrics") {
                            val state = viewerState
                            SocialMetricsPanel(
                                metrics = metrics,
                                viewerState = state,
                                signedIn = currentUser != null,
                                relationshipBusy = relationshipBusy,
                                ratingBusy = ratingBusy,
                                onBookmark = {
                                    if (currentUser == null) onLogin() else if (state != null && !relationshipBusy) {
                                        relationshipBusy = true; actionError = null
                                        scope.launch {
                                            try {
                                                if (state.bookmarked) repository.unbookmark(item.id) else repository.bookmark(item.id)
                                                val refreshed = repository.viewerState(item.id)
                                                viewerState = refreshed
                                                socialMetrics = refreshed.metrics
                                                onContentChanged()
                                            } catch (cancelled: CancellationException) { throw cancelled }
                                            catch (failure: Throwable) { actionError = failure.message ?: "Bookmark update failed." }
                                            finally { relationshipBusy = false }
                                        }
                                    }
                                },
                                onFollow = {
                                    if (currentUser == null) onLogin() else if (state != null && !relationshipBusy) {
                                        relationshipBusy = true; actionError = null
                                        scope.launch {
                                            try {
                                                if (state.subscribed) repository.unsubscribe(item.id) else repository.subscribe(item.id)
                                                val refreshed = repository.viewerState(item.id)
                                                viewerState = refreshed
                                                socialMetrics = refreshed.metrics
                                                onContentChanged()
                                            } catch (cancelled: CancellationException) { throw cancelled }
                                            catch (failure: Throwable) { actionError = failure.message ?: "Follow update failed." }
                                            finally { relationshipBusy = false }
                                        }
                                    }
                                },
                                onRate = { rating ->
                                    if (currentUser == null) onLogin() else if (state != null && !ratingBusy) {
                                        ratingBusy = true; actionError = null
                                        scope.launch {
                                            try {
                                                repository.rateSeries(item.id, rating)
                                                val refreshed = repository.viewerState(item.id)
                                                viewerState = refreshed
                                                socialMetrics = refreshed.metrics
                                                onContentChanged()
                                            } catch (cancelled: CancellationException) { throw cancelled }
                                            catch (failure: Throwable) { actionError = failure.message ?: "Rating update failed." }
                                            finally { ratingBusy = false }
                                        }
                                    }
                                },
                            )
                        }
                    }

                    actionError?.let { message ->
                        item(key = "action-error") {
                            Surface(color = Brand950.copy(alpha = 0.55f), shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Brand700)) {
                                Text(message, Modifier.padding(11.dp), color = Brand100, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }

                    item(key = "chapters-header") {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            SectionHeading("Chapters", "Read the series", "Search published chapter numbers and move through the same Newer / Older pages as the web application.")
                            OutlinedTextField(
                                value = chapterQuery,
                                onValueChange = { value -> chapterQuery = value.filter { ch -> ch.isDigit() || ch == '.' }.take(12) },
                                modifier = Modifier.fillMaxWidth(),
                                placeholder = { Text("Search chapter number…") },
                                leadingIcon = { Icon(Icons.Default.Search, null) },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                singleLine = true,
                                shape = RoundedCornerShape(12.dp),
                                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Brand500, unfocusedBorderColor = Ink700, focusedContainerColor = Ink900, unfocusedContainerColor = Ink900),
                            )
                        }
                    }

                    if (chapterLoading) {
                        item(key = "chapters-refreshing") {
                            LinearProgressIndicator(
                                modifier = Modifier.fillMaxWidth(),
                                color = Brand400,
                                trackColor = Ink800,
                            )
                        }
                    }

                    chapterPageError?.let { message ->
                        item(key = "chapter-page-error") {
                            Surface(color = Brand950.copy(alpha = 0.42f), shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Brand700)) {
                                Row(Modifier.fillMaxWidth().padding(11.dp), verticalAlignment = Alignment.CenterVertically) {
                                    Text(message, modifier = Modifier.weight(1f), color = Brand100, style = MaterialTheme.typography.bodySmall)
                                    TextButton(onClick = { reloadKey++ }) { Text("Retry") }
                                }
                            }
                        }
                    }

                    if (visibleChapters.isEmpty() && !chapterLoading) {
                        item(key = "chapters-empty") { Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { Text("No chapter number matches this filter.", color = Ink400) } }
                    } else {
                        items(visibleChapters, key = { it.id }) { chapter ->
                            val read = readingState?.readChapterIds?.contains(chapter.id) == true
                            val completed = readingState?.completedChapterIds?.contains(chapter.id) == true
                            Surface(
                                onClick = { onRead(item.slug, chapter.slug) },
                                modifier = Modifier.fillMaxWidth(),
                                color = Ink900,
                                shape = RoundedCornerShape(13.dp),
                                border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
                            ) {
                                Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
                                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                                            Text("Chapter ${formatChapterNumber(chapter.chapterNumber)}", fontWeight = FontWeight.SemiBold, color = Ink50)
                                            if (completed) Icon(Icons.Default.CheckCircle, "Completed", tint = Color(0xFF5ED7A1), modifier = Modifier.size(16.dp))
                                            else if (read) Icon(Icons.Default.History, "Read", tint = Ink500, modifier = Modifier.size(15.dp))
                                        }
                                        if (!chapter.title.isNullOrBlank()) Text(chapter.title, style = MaterialTheme.typography.bodySmall, color = Ink400, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    }
                                    Spacer(Modifier.width(4.dp)); Icon(Icons.Default.ChevronRight, null, tint = Ink600)
                                }
                            }
                        }
                    }

                    if ((item.chapters.isNotEmpty() || chapterOffset > 0) && !chapterLoading) {
                        item(key = "chapter-pagination") {
                            MobilePaginationBar(
                                pageIndex = chapterOffset / CHAPTER_PAGE_SIZE,
                                canGoPrevious = chapterOffset > 0,
                                canGoNext = item.chapterHasMore,
                                onPrevious = {
                                    chapterOffset = (chapterOffset - CHAPTER_PAGE_SIZE).coerceAtLeast(0)
                                    scope.launch { listState.animateScrollToItem(0) }
                                },
                                onNext = {
                                    chapterOffset += CHAPTER_PAGE_SIZE
                                    scope.launch { listState.animateScrollToItem(0) }
                                },
                                previousLabel = "Newer",
                                nextLabel = "Older",
                                busy = chapterLoading,
                            )
                        }
                    }

                    item(key = "series-discussion") {
                        CommentSection(
                            repository = repository,
                            currentUser = currentUser,
                            seriesId = item.id,
                            title = "Series discussion",
                            onLogin = onLogin,
                            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        )
                    }
                }
                }
            }
        }
    }
}

@Composable
private fun SocialMetricsPanel(
    metrics: SeriesSocialMetrics,
    viewerState: SeriesViewerState?,
    signedIn: Boolean,
    relationshipBusy: Boolean,
    ratingBusy: Boolean,
    onBookmark: () -> Unit,
    onFollow: () -> Unit,
    onRate: (Int) -> Unit,
) {
    Surface(color = Ink900.copy(alpha = 0.72f), shape = RoundedCornerShape(16.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
        BoxWithConstraints(Modifier.fillMaxWidth().padding(13.dp)) {
            val compact = maxWidth < 380.dp
            Column(verticalArrangement = Arrangement.spacedBy(11.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Metric(Icons.Default.Star, metrics.ratingAverage?.let { "%.1f".format(it) } ?: "—", "ratings", Gold400, Modifier.weight(1f))
                    Metric(Icons.Default.Bookmark, metrics.bookmarkCount.toString(), "bookmarks", Brand400, Modifier.weight(1f))
                    Metric(Icons.Default.People, metrics.subscriptionCount.toString(), "followers", Brand400, Modifier.weight(1f))
                }
                if (compact) {
                    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("Your rating", color = Ink500, style = MaterialTheme.typography.labelSmall)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            (1..5).forEach { value ->
                                IconButton(onClick = { onRate(value) }, enabled = !ratingBusy && (!signedIn || viewerState != null), modifier = Modifier.size(34.dp)) {
                                    Icon(Icons.Default.Star, "Rate $value stars", tint = if (value <= (viewerState?.metrics?.userRating ?: 0)) Gold400 else Ink600, modifier = Modifier.size(20.dp))
                                }
                            }
                        }
                        if (!signedIn) Text("Sign in to rate", color = Ink500, style = MaterialTheme.typography.labelSmall)
                    }
                } else {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("Your rating", color = Ink500, style = MaterialTheme.typography.labelSmall)
                        (1..5).forEach { value ->
                            IconButton(onClick = { onRate(value) }, enabled = !ratingBusy && (!signedIn || viewerState != null), modifier = Modifier.size(30.dp)) {
                                Icon(Icons.Default.Star, "Rate $value stars", tint = if (value <= (viewerState?.metrics?.userRating ?: 0)) Gold400 else Ink600, modifier = Modifier.size(20.dp))
                            }
                        }
                        if (!signedIn) Text("Sign in to rate", color = Ink500, style = MaterialTheme.typography.labelSmall)
                    }
                }
                if (compact) {
                    Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                        RelationshipButton(viewerState?.bookmarked == true, true, relationshipBusy || (signedIn && viewerState == null), onBookmark, Modifier.fillMaxWidth())
                        RelationshipButton(viewerState?.subscribed == true, false, relationshipBusy || (signedIn && viewerState == null), onFollow, Modifier.fillMaxWidth())
                    }
                } else {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        RelationshipButton(viewerState?.bookmarked == true, true, relationshipBusy || (signedIn && viewerState == null), onBookmark, Modifier.weight(1f))
                        RelationshipButton(viewerState?.subscribed == true, false, relationshipBusy || (signedIn && viewerState == null), onFollow, Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun RelationshipButton(active: Boolean, bookmark: Boolean, busy: Boolean, onClick: () -> Unit, modifier: Modifier) {
    OutlinedButton(onClick = onClick, enabled = !busy, modifier = modifier, colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink200)) {
        val icon = if (bookmark) {
            if (active) Icons.Default.Bookmark else Icons.Default.BookmarkBorder
        } else {
            if (active) Icons.Default.Notifications else Icons.Default.NotificationsNone
        }
        Icon(icon, null, tint = if (active) Brand400 else Ink300)
        Spacer(Modifier.width(5.dp))
        Text(if (bookmark) { if (active) "Bookmarked" else "Bookmark" } else { if (active) "Following" else "Follow" })
    }
}

@Composable
private fun Metric(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    value: String,
    label: String,
    tint: Color,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Icon(icon, null, tint = tint, modifier = Modifier.size(17.dp))
            Text(value, color = Ink50, fontWeight = FontWeight.SemiBold, maxLines = 1)
        }
        Text(label, color = Ink500, style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}
