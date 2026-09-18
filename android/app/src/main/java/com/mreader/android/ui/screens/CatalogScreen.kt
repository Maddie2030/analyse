package com.mreader.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mreader.android.core.model.*
import com.mreader.android.core.repository.MReaderRepository
import com.mreader.android.core.repository.bestEffort
import com.mreader.android.core.repository.bestEffortOrNull
import com.mreader.android.ui.components.*
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlin.random.Random

private const val CATALOG_PAGE_SIZE = 20

@Composable
fun CatalogScreen(
    repository: MReaderRepository,
    user: StateFlow<User?>,
    refreshEpoch: Long,
    contentPadding: PaddingValues,
    onSeries: (String) -> Unit,
    onRead: (String, String) -> Unit,
    onLogin: () -> Unit,
    onAnnouncementLink: (String) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var catalogOffset by rememberSaveable { mutableIntStateOf(0) }
    var selectedGenre by rememberSaveable { mutableStateOf<Int?>(null) }
    var sort by rememberSaveable { mutableStateOf("updated") }
    var rows by remember {
        mutableStateOf(repository.peekListSeries("", 0, CATALOG_PAGE_SIZE, "updated", null).orEmpty())
    }
    var initialLoading by remember { mutableStateOf(rows.isEmpty()) }
    var hasMore by remember { mutableStateOf(rows.size == CATALOG_PAGE_SIZE) }
    var error by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }
    var genres by remember { mutableStateOf(repository.peekGenres().orEmpty()) }
    var sortMenu by remember { mutableStateOf(false) }
    var discovery by remember { mutableStateOf(repository.peekDiscovery()) }
    var curation by remember { mutableStateOf(repository.peekCuration()) }
    var dismissedAnnouncementIds by remember { mutableStateOf<Set<String>>(emptySet()) }
    var discoveryLoading by remember { mutableStateOf(discovery == null) }
    var history by remember { mutableStateOf<List<HistoryItem>>(emptyList()) }
    var publicMetrics by remember { mutableStateOf<Map<String, SeriesSocialMetrics>>(emptyMap()) }
    var trendingWindow by rememberSaveable { mutableStateOf("24h") }
    var trending by remember { mutableStateOf(repository.peekTrending("24h", 10)) }
    var trendingLoading by remember { mutableStateOf(trending == null) }
    var browseJumpRequest by remember { mutableIntStateOf(0) }
    val currentUser by user.collectAsStateWithLifecycle()
    val readingView by repository.reading.view.collectAsStateWithLifecycle()
    var historyOwner by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val gridState = rememberLazyGridState()
    var displayedCatalogKey by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(query, selectedGenre, sort) {
        if (catalogOffset != 0) catalogOffset = 0
        gridState.scrollToItem(0)
    }

    LaunchedEffect(currentUser?.id, refreshEpoch, reloadKey) {
        if (historyOwner != currentUser?.id) { history = emptyList(); historyOwner = currentUser?.id }
        // Stale-while-revalidate: restore public browse data immediately from the
        // bounded local cache, then refresh it quietly from the gateway.
        if (discovery == null) repository.cachedDiscovery()?.let { discovery = it }
        if (genres.isEmpty()) repository.cachedGenres()?.let { genres = it }
        if (curation == null) repository.cachedCuration()?.let { curation = it }
        discoveryLoading = discovery == null
        try {
            coroutineScope {
                val discoveryDeferred = async { bestEffortOrNull { repository.discovery() } }
                val genresDeferred = async { bestEffort(genres) { repository.genres() } }
                val historyDeferred = async {
                    if (currentUser == null) emptyList() else bestEffort(history) {
                        repository.history(limit = 8, scope = currentUser?.id)
                    }
                }
                val curationDeferred = async { bestEffortOrNull { repository.curation() } }
                discoveryDeferred.await()?.let { discovery = it }
                genres = genresDeferred.await()
                history = historyDeferred.await()
                curationDeferred.await()?.let { curation = it }
            }
        } finally {
            discoveryLoading = false
        }
    }

    LaunchedEffect(trendingWindow, refreshEpoch, reloadKey) {
        if (trending?.window != trendingWindow) {
            repository.peekTrending(trendingWindow, 10)?.let { trending = it }
                ?: repository.cachedTrending(trendingWindow, 10)?.let { trending = it }
        }
        trendingLoading = trending?.window != trendingWindow
        try {
            bestEffortOrNull { repository.trending(trendingWindow, 10) }?.let { trending = it }
        } finally {
            trendingLoading = false
        }
    }

    LaunchedEffect(query, selectedGenre, sort, catalogOffset, refreshEpoch, reloadKey) {
        error = null
        val requestKey = "${query.trim().lowercase()}|${selectedGenre ?: "all"}|$sort|$catalogOffset"
        val cached = repository.cachedListSeries(
            search = query,
            offset = catalogOffset,
            limit = CATALOG_PAGE_SIZE,
            sort = sort,
            genreId = selectedGenre,
        )
        if (cached != null) {
            rows = cached
            hasMore = cached.size == CATALOG_PAGE_SIZE
            displayedCatalogKey = requestKey
            initialLoading = false
        } else if (displayedCatalogKey != requestKey) {
            // Never label rows from the previous page/filter as the new request.
            // Returning to a previously visited page remains instant through cache;
            // a genuinely new page gets a bounded loader until its first response.
            rows = emptyList()
            hasMore = false
            initialLoading = true
        }

        // Debounce only the network request. Cached matching data is shown before
        // this delay, so an already-known search/page remains instantaneous.
        if (query.isNotBlank()) delay(250)
        try {
            val result = repository.listSeries(
                search = query,
                offset = catalogOffset,
                limit = CATALOG_PAGE_SIZE,
                sort = sort,
                genreId = selectedGenre,
            )
            rows = result
            hasMore = result.size == CATALOG_PAGE_SIZE
            displayedCatalogKey = requestKey
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Throwable) {
            error = failure.message ?: "Could not refresh catalog."
        } finally {
            initialLoading = false
        }
    }

    fun catalogHeadingItemIndex(): Int {
        var index = 2 // brand + discovery hero
        if (query.isBlank()) {
            index += curation?.announcements.orEmpty().take(2).size
            if (currentUser != null && readingView.scope?.accountId == currentUser?.id) index += 2
            if (history.isNotEmpty() && historyOwner == currentUser?.id) index += 2
            if (trending?.items.orEmpty().isNotEmpty()) index += 2
            if (discovery?.recent.orEmpty().isNotEmpty()) index += 2
            if (curation?.editorPicks.orEmpty().isNotEmpty()) index += 2
            if (discovery?.newReleases.orEmpty().isNotEmpty()) index += 2
            else if (discoveryLoading) index += 1
        }
        return index
    }

    fun browseCatalog() {
        query = ""
        selectedGenre = null
        catalogOffset = 0
        // Defer the jump until discovery/trending shelves have settled. Otherwise
        // shelves inserted during the animation can move the catalog anchor away
        // from the viewport and make the Browse action appear broken.
        browseJumpRequest++
    }

    LaunchedEffect(
        browseJumpRequest, query, selectedGenre, discoveryLoading, trendingLoading,
        history.size, historyOwner, currentUser?.id, readingView.scope, trending?.items?.size, discovery?.recent?.size,
        curation?.editorPicks?.size, discovery?.newReleases?.size, curation?.announcements?.size,
    ) {
        if (browseJumpRequest <= 0 || query.isNotBlank() || selectedGenre != null) return@LaunchedEffect
        if (discoveryLoading || trendingLoading) return@LaunchedEffect
        delay(60L)
        gridState.animateScrollToItem(catalogHeadingItemIndex())
        browseJumpRequest = 0
    }

    val metricSeriesIds = remember(rows, discovery, trending, curation) {
        buildList {
            addAll(rows.map { it.id })
            addAll(discovery?.popular.orEmpty().map { it.id })
            addAll(discovery?.recent.orEmpty().map { it.series.id })
            addAll(discovery?.newReleases.orEmpty().map { it.id })
            addAll(trending?.items.orEmpty().map { it.series.id })
            addAll(curation?.editorPicks.orEmpty().map { it.series.id })
        }.distinct().take(100)
    }

    LaunchedEffect(metricSeriesIds, refreshEpoch) {
        if (metricSeriesIds.isNotEmpty()) {
            bestEffortOrNull { repository.socialMetricsBatch(metricSeriesIds) }?.let { loaded ->
                publicMetrics = publicMetrics + loaded
            }
        }
    }

    val posterMinWidth = adaptivePosterMinWidth()
    val carouselPosterWidth = adaptiveCarouselPosterWidth()
    ResponsiveFrame(
        modifier = Modifier.background(Ink950),
        maxContentWidth = 1180.dp,
    ) { edgePadding ->
        LazyVerticalGrid(
        modifier = Modifier.fillMaxSize(),
        columns = GridCells.Adaptive(posterMinWidth),
        contentPadding = PaddingValues(
            start = edgePadding,
            top = contentPadding.calculateTopPadding() + 10.dp,
            end = edgePadding,
            bottom = contentPadding.calculateBottomPadding() + 28.dp,
        ),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }, key = "browse-brand") {
            Row(Modifier.fillMaxWidth().padding(horizontal = 2.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                MReaderBrand(Modifier.weight(1f))
                IconButton(onClick = onLogin) { Icon(Icons.Default.Person, contentDescription = "Account", tint = Ink200) }
            }
        }

        item(span = { GridItemSpan(maxLineSpan) }, key = "browse-hero") {
            Box(
                Modifier.fillMaxWidth()
                    .border(1.dp, Ink800, RoundedCornerShape(26.dp))
                    .background(Brush.linearGradient(listOf(Ink900, Ink900, Brand950.copy(alpha = 0.72f))), RoundedCornerShape(26.dp))
                    .padding(18.dp),
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                        Icon(Icons.Default.Explore, null, tint = Brand400, modifier = Modifier.size(17.dp))
                        Text("BROWSE & DISCOVER", style = MaterialTheme.typography.labelSmall, color = Brand400, fontWeight = FontWeight.Bold)
                    }
                    Text("Find the next series worth losing sleep over.", style = MaterialTheme.typography.headlineMedium, color = Ink50)
                    Text(
                        "Trending reads, fresh chapters, new releases, and your full catalog in one reader-first experience.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Ink400,
                    )
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        placeholder = { Text("Search series by title…") },
                        leadingIcon = { Icon(Icons.Default.Search, null) },
                        trailingIcon = if (query.isNotBlank()) {
                            { IconButton(onClick = { query = "" }) { Icon(Icons.Default.Close, "Clear search") } }
                        } else null,
                        shape = RoundedCornerShape(13.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Brand500,
                            unfocusedBorderColor = Ink700,
                            focusedContainerColor = Ink950.copy(alpha = 0.78f),
                            unfocusedContainerColor = Ink950.copy(alpha = 0.78f),
                        ),
                    )
                    BoxWithConstraints(Modifier.fillMaxWidth()) {
                        val compactActions = maxWidth < 360.dp
                        if (compactActions) {
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                DiscoveryPrimaryAction(rows, discovery, onSeries, Modifier.fillMaxWidth())
                                DiscoveryBrowseAction(onBrowse = ::browseCatalog, modifier = Modifier.fillMaxWidth())
                            }
                        } else {
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                DiscoveryPrimaryAction(rows, discovery, onSeries, Modifier)
                                DiscoveryBrowseAction(onBrowse = ::browseCatalog, modifier = Modifier)
                            }
                        }
                    }
                }
            }
        }

        if (query.isBlank()) {
            curation?.announcements.orEmpty()
                .filterNot { announcement ->
                    announcement.id in dismissedAnnouncementIds || repository.isAnnouncementDismissed(announcement.id)
                }
                .take(2)
                .forEach { announcement ->
                    item(span = { GridItemSpan(maxLineSpan) }, key = "announcement-${announcement.id}") {
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            color = if (announcement.tone.equals("warning", true)) Gold400.copy(alpha = 0.10f) else Brand950.copy(alpha = 0.46f),
                            shape = RoundedCornerShape(15.dp),
                            border = androidx.compose.foundation.BorderStroke(
                                1.dp,
                                if (announcement.tone.equals("warning", true)) Gold400.copy(alpha = 0.42f) else Brand700,
                            ),
                        ) {
                            Row(Modifier.padding(13.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.Top) {
                                Icon(
                                    if (announcement.tone.equals("warning", true)) Icons.Default.Campaign else Icons.Default.AutoAwesome,
                                    contentDescription = null,
                                    tint = if (announcement.tone.equals("warning", true)) Gold400 else Brand400,
                                    modifier = Modifier.size(19.dp),
                                )
                                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                    Text(announcement.title, style = MaterialTheme.typography.titleSmall, color = Ink50)
                                    Text(announcement.body, style = MaterialTheme.typography.bodySmall, color = Ink400)
                                    announcement.linkUrl?.takeIf { it.isNotBlank() }?.let { link ->
                                        TextButton(
                                            onClick = { onAnnouncementLink(link) },
                                            contentPadding = PaddingValues(0.dp),
                                        ) {
                                            Text(announcement.linkLabel?.takeIf { it.isNotBlank() } ?: "Learn more")
                                        }
                                    }
                                }
                                if (announcement.dismissible) {
                                    IconButton(
                                        onClick = {
                                            repository.dismissAnnouncement(announcement.id)
                                            dismissedAnnouncementIds = dismissedAnnouncementIds + announcement.id
                                        },
                                        modifier = Modifier.size(32.dp),
                                    ) {
                                        Icon(Icons.Default.Close, contentDescription = "Dismiss ${announcement.title}", tint = Ink400)
                                    }
                                }
                            }
                        }
                    }
                }

            if (readingView.scope?.accountId == currentUser?.id && currentUser != null) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "reading-sync") { ReadingSyncStatus(repository, readingView) }
                item(span = { GridItemSpan(maxLineSpan) }, key = "pending-reading") { PendingReadingRail(readingView, onRead) }
            }
            if (history.isNotEmpty() && historyOwner == currentUser?.id) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "continue-heading") {
                    SectionHeading("Personal", "Continue reading", "Pick up exactly where you left off on the web or Android app.")
                }
                item(span = { GridItemSpan(maxLineSpan) }, key = "continue-row") {
                    StableHorizontalShelf(spacing = 10.dp) {
                        items(history, key = { it.seriesId }) { item ->
                            val pending = readingView.pending(item.seriesId)
                            val actionSlug = pending?.target?.chapterSlug ?: item.chapterSlug
                            val actionNumber = pending?.target?.chapterNumber ?: item.chapterNumber
                            Surface(
                                modifier = Modifier.width(238.dp).height(158.dp).clickable { onRead(item.seriesSlug, actionSlug) },
                                color = Ink900,
                                shape = RoundedCornerShape(15.dp),
                                border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
                            ) {
                                Column(Modifier.padding(13.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                                        Icon(Icons.Default.History, null, tint = Brand400, modifier = Modifier.size(17.dp))
                                        Text("CONTINUE", color = Brand400, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
                                    }
                                    Text(item.seriesTitle, modifier = Modifier.heightIn(min = 38.dp), color = Ink50, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    Text(
                                        buildString {
                                            append("Continue chapter ").append(formatChapterNumber(actionNumber))
                                            if (pending == null && !item.chapterTitle.isNullOrBlank()) append(" · ").append(item.chapterTitle)
                                        },
                                        color = Ink300,
                                        style = MaterialTheme.typography.bodySmall,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    if (pending != null) Text("Pending sync", color = Brand400, style = MaterialTheme.typography.labelSmall)
                                    else if (!item.readAt.isNullOrBlank()) {
                                        Text("Last opened ${relativeTime(item.readAt)}", color = Ink500, style = MaterialTheme.typography.labelSmall)
                                    }
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text("Resume", color = Brand300, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                                        Spacer(Modifier.weight(1f))
                                        Icon(Icons.Default.ArrowForward, null, tint = Brand400, modifier = Modifier.size(16.dp))
                                    }
                                }
                            }
                        }
                    }
                }
            }

            val trendingItems = trending?.items.orEmpty()
            if (trendingItems.isNotEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "trending-heading") {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        SectionHeading("Discovery", "Trending now", "Ranked from recent chapter opens, just like the web application.")
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            listOf("24h", "7d", "30d").forEach { window ->
                                FilterChip(
                                    selected = trendingWindow == window,
                                    onClick = { trendingWindow = window },
                                    label = { Text(window) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = Brand600,
                                        selectedLabelColor = androidx.compose.ui.graphics.Color.White,
                                        containerColor = Ink900,
                                        labelColor = Ink400,
                                    ),
                                )
                            }
                        }
                    }
                }
                item(span = { GridItemSpan(maxLineSpan) }, key = "trending-row") {
                    StableHorizontalShelf(spacing = 12.dp) {
                        items(trendingItems, key = { it.series.id }) { item ->
                            WebSeriesPosterCard(
                                repository = repository,
                                series = item.series,
                                onClick = { onSeries(item.series.slug) },
                                modifier = Modifier.width(carouselPosterWidth),
                                metrics = publicMetrics[item.series.id],
                                rank = trendingItems.indexOf(item) + 1,
                                dense = true,
                            )
                        }
                    }
                }
            }

            val recent = discovery?.recent.orEmpty()
            if (recent.isNotEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "latest-heading") {
                    SectionHeading("Fresh chapters", "Latest updates", "Jump directly into one of the newest published chapters.")
                }
                item(span = { GridItemSpan(maxLineSpan) }, key = "latest-row") {
                    StableHorizontalShelf(spacing = 10.dp) {
                        items(recent, key = { it.series.id }) { entry ->
                            LatestUpdateCard(repository, entry, publicMetrics[entry.series.id], onSeries, onRead)
                        }
                    }
                }
            }

            val editorPicks = curation?.editorPicks.orEmpty()
            if (editorPicks.isNotEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "picks-heading") {
                    SectionHeading("Curated", "Editor’s picks", "Hand-picked series surfaced by the same curation feed as the web application.")
                }
                item(span = { GridItemSpan(maxLineSpan) }, key = "picks-row") {
                    StableHorizontalShelf(spacing = 12.dp) {
                        items(editorPicks, key = { it.id }) { pick ->
                            Column(Modifier.width(carouselPosterWidth), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                WebSeriesPosterCard(repository, pick.series, { onSeries(pick.series.slug) }, Modifier.fillMaxWidth(), metrics = publicMetrics[pick.series.id], dense = true)
                                Text(
                                    pick.label?.uppercase().orEmpty(),
                                    modifier = Modifier.heightIn(min = 14.dp),
                                    color = Gold400,
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    pick.note.orEmpty(),
                                    modifier = Modifier.heightIn(min = 36.dp),
                                    color = Ink500,
                                    style = MaterialTheme.typography.bodySmall,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                    }
                }
            }

            val newReleases = discovery?.newReleases.orEmpty()
            if (newReleases.isNotEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "new-heading") {
                    SectionHeading("Discovery", "New releases", "Recently added series from the same catalog.")
                }
                item(span = { GridItemSpan(maxLineSpan) }, key = "new-row") {
                    StableHorizontalShelf(spacing = 12.dp) {
                        items(newReleases, key = { it.id }) { item ->
                            WebSeriesPosterCard(repository, item, { onSeries(item.slug) }, Modifier.width(carouselPosterWidth), metrics = publicMetrics[item.id], dense = true)
                        }
                    }
                }
            } else if (discoveryLoading) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "discovery-loading") {
                    LinearProgressIndicator(Modifier.fillMaxWidth(), color = Brand400, trackColor = Ink800)
                }
            }
        }

        item(span = { GridItemSpan(maxLineSpan) }, key = "catalog-heading") {
            Column(verticalArrangement = Arrangement.spacedBy(11.dp), modifier = Modifier.padding(top = 10.dp)) {
                SectionHeading(
                    eyebrow = if (query.isBlank()) "Catalog" else "Search results",
                    title = if (query.isBlank()) "Explore all series" else "Results for “${query.trim()}”",
                    supporting = if (query.isBlank()) "Use genre chips and sorting to narrow the catalog without leaving Browse." else null,
                    action = {
                        Box {
                            OutlinedButton(onClick = { sortMenu = true }, colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink300), contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp)) {
                                Icon(Icons.Default.Sort, null, modifier = Modifier.size(16.dp))
                                Spacer(Modifier.width(5.dp))
                                Text(sortLabel(sort), style = MaterialTheme.typography.labelMedium)
                            }
                            DropdownMenu(expanded = sortMenu, onDismissRequest = { sortMenu = false }, containerColor = Ink900) {
                                listOf(
                                    "updated" to "Recently updated",
                                    "newest" to "Newest series",
                                    "rating" to "Highest rated",
                                    "popular" to "Most bookmarked",
                                    "title" to "Title A–Z",
                                ).forEach { option ->
                                    DropdownMenuItem(
                                        text = { Text(option.second) },
                                        onClick = { sort = option.first; sortMenu = false },
                                    )
                                }
                            }
                        }
                    },
                )
                if (genres.isNotEmpty() && query.isBlank()) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(7.dp), contentPadding = PaddingValues(end = 8.dp)) {
                        item {
                            FilterChip(
                                selected = selectedGenre == null,
                                onClick = { selectedGenre = null },
                                label = { Text("All genres") },
                                colors = catalogChipColors(),
                            )
                        }
                        items(genres, key = { it.id }) { genre ->
                            FilterChip(
                                selected = selectedGenre == genre.id,
                                onClick = { selectedGenre = if (selectedGenre == genre.id) null else genre.id },
                                label = { Text(genre.name) },
                                colors = catalogChipColors(),
                            )
                        }
                    }
                }
            }
        }

        if (error != null && rows.isEmpty() && !initialLoading && catalogOffset == 0) {
            item(span = { GridItemSpan(maxLineSpan) }, key = "catalog-error") {
                Column(Modifier.fillMaxWidth().padding(vertical = 34.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(error.orEmpty(), color = MaterialTheme.colorScheme.error)
                    OutlinedButton(onClick = { reloadKey++ }) { Text("Retry") }
                }
            }
        } else if (initialLoading && rows.isEmpty()) {
            item(span = { GridItemSpan(maxLineSpan) }, key = "catalog-loading") {
                Box(Modifier.fillMaxWidth().padding(vertical = 42.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Brand400) }
            }
        } else {
            if (initialLoading) item(span = { GridItemSpan(maxLineSpan) }, key = "catalog-refresh") { LinearProgressIndicator(Modifier.fillMaxWidth(), color = Brand400, trackColor = Ink800) }
            error?.let { message ->
                item(span = { GridItemSpan(maxLineSpan) }, key = "catalog-warning") {
                    Surface(color = Brand950.copy(alpha = 0.55f), shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Brand700)) {
                        Text(message, Modifier.padding(12.dp), color = Brand100, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            if (!initialLoading && error == null && rows.isEmpty()) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "catalog-empty") {
                    Box(Modifier.fillMaxWidth().padding(34.dp), contentAlignment = Alignment.Center) {
                        Text(if (query.isBlank()) "No series are available in this view." else "No matching series found.", color = Ink400)
                    }
                }
            }
            gridItems(rows, key = { it.id }) { series ->
                WebSeriesPosterCard(repository = repository, series = series, onClick = { onSeries(series.slug) }, metrics = publicMetrics[series.id])
            }
            if ((rows.isNotEmpty() || catalogOffset > 0) && !initialLoading) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "catalog-pagination") {
                    MobilePaginationBar(
                        pageIndex = catalogOffset / CATALOG_PAGE_SIZE,
                        canGoPrevious = catalogOffset > 0,
                        canGoNext = hasMore,
                        onPrevious = {
                            catalogOffset = (catalogOffset - CATALOG_PAGE_SIZE).coerceAtLeast(0)
                            scope.launch { gridState.animateScrollToItem(0) }
                        },
                        onNext = {
                            catalogOffset += CATALOG_PAGE_SIZE
                            scope.launch { gridState.animateScrollToItem(0) }
                        },
                        busy = initialLoading,
                    )
                }
            }
        }
    }
    }
}


@Composable
private fun DiscoveryPrimaryAction(
    rows: List<Series>,
    discovery: DiscoveryResponse?,
    onSeries: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val pool = remember(rows, discovery) {
        buildList {
            addAll(discovery?.popular.orEmpty())
            addAll(discovery?.newReleases.orEmpty())
            addAll(rows)
        }.distinctBy { it.id }
    }
    Button(
        onClick = {
            if (pool.isNotEmpty()) onSeries(pool[Random.nextInt(pool.size)].slug)
        },
        enabled = pool.isNotEmpty(),
        colors = ButtonDefaults.buttonColors(containerColor = Brand600),
        shape = RoundedCornerShape(12.dp),
        modifier = modifier,
    ) {
        Icon(Icons.Default.Shuffle, null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(6.dp))
        Text("Surprise me")
    }
}

@Composable
private fun DiscoveryBrowseAction(onBrowse: () -> Unit, modifier: Modifier = Modifier) {
    OutlinedButton(
        onClick = onBrowse,
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink200),
    ) {
        Icon(Icons.Default.Tune, null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(6.dp))
        Text("Browse")
    }
}

@Composable
private fun LatestUpdateCard(
    repository: MReaderRepository,
    entry: DiscoverySeries,
    metrics: SeriesSocialMetrics?,
    onSeries: (String) -> Unit,
    onRead: (String, String) -> Unit,
) {
    val configuration = LocalConfiguration.current
    val compact = configuration.screenWidthDp < 350
    val cardWidth = (configuration.screenWidthDp.dp - 24.dp).coerceIn(300.dp, 356.dp)
    val cardHeight = if (compact) 214.dp else 226.dp
    val thumbnailWidth = if (compact) 114.dp else 130.dp
    val chapterRowHeight = if (compact) 38.dp else 42.dp

    Surface(
        modifier = Modifier.width(cardWidth).height(cardHeight),
        color = Ink900,
        shape = RoundedCornerShape(16.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
    ) {
        Row(
            Modifier.fillMaxSize().padding(horizontal = 10.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            NetworkImage(
                repository,
                entry.series.coverImagePath?.let(repository.api::coverUrl),
                entry.series.title,
                Modifier
                    .width(thumbnailWidth)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(11.dp))
                    .clickable { onSeries(entry.series.slug) },
                ContentScale.Crop,
            )
            Column(
                Modifier.weight(1f).fillMaxHeight(),
                verticalArrangement = Arrangement.spacedBy(3.dp),
            ) {
                Text(
                    entry.series.title,
                    color = Ink50,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.heightIn(min = 38.dp).clickable { onSeries(entry.series.slug) },
                )
                Text(
                    entry.series.status.replaceFirstChar { it.uppercase() },
                    color = Ink500,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                )
                metrics?.let { aggregate ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(9.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Star, null, tint = Gold400, modifier = Modifier.size(12.dp))
                            Text(aggregate.ratingAverage?.let { "%.1f".format(it) } ?: "—", color = Ink400, fontSize = 10.sp)
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Bookmark, null, tint = Brand400, modifier = Modifier.size(12.dp))
                            Text(aggregate.bookmarkCount.toString(), color = Ink400, fontSize = 10.sp)
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.People, null, tint = Brand400, modifier = Modifier.size(12.dp))
                            Text(aggregate.subscriptionCount.toString(), color = Ink400, fontSize = 10.sp)
                        }
                    }
                }
                Spacer(Modifier.height(2.dp))
                entry.latestChapters.take(2).forEach { chapter ->
                    Surface(
                        onClick = { onRead(entry.series.slug, chapter.slug) },
                        color = Ink950.copy(alpha = 0.72f),
                        shape = RoundedCornerShape(9.dp),
                        modifier = Modifier.fillMaxWidth().height(chapterRowHeight),
                    ) {
                        Row(
                            Modifier.fillMaxSize().padding(horizontal = 9.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                "Ch. ${formatChapterNumber(chapter.chapterNumber)}",
                                modifier = Modifier.width(60.dp),
                                color = Brand300,
                                fontSize = 11.sp,
                                lineHeight = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                                maxLines = 1,
                            )
                            Spacer(Modifier.width(4.dp))
                            Text(
                                chapter.title?.takeIf { it.isNotBlank() } ?: "Latest chapter",
                                modifier = Modifier.weight(1f),
                                color = Ink300,
                                style = MaterialTheme.typography.bodySmall,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Spacer(Modifier.width(6.dp))
                            Icon(Icons.Default.ArrowForward, null, tint = Ink500, modifier = Modifier.size(13.dp))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun catalogChipColors() = FilterChipDefaults.filterChipColors(
    containerColor = Ink800,
    labelColor = Ink300,
    selectedContainerColor = Brand600,
    selectedLabelColor = androidx.compose.ui.graphics.Color.White,
)

private fun sortLabel(value: String): String = when (value) {
    "newest" -> "Newest"
    "rating" -> "Rated"
    "popular" -> "Popular"
    "title" -> "A–Z"
    else -> "Updated"
}
