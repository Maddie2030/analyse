package com.mreader.android.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.LibraryBooks
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mreader.android.core.model.*
import com.mreader.android.core.repository.MReaderRepository
import com.mreader.android.ui.components.*
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

private const val LIBRARY_PAGE_SIZE = 30

@Composable
fun LibraryScreen(
    repository: MReaderRepository,
    user: StateFlow<User?>,
    refreshEpoch: Long,
    contentPadding: PaddingValues,
    onSeries: (String) -> Unit,
    onRead: (String, String) -> Unit,
    onLogin: () -> Unit,
    onAccount: () -> Unit,
) {
    val currentUser by user.collectAsStateWithLifecycle()
    val readingView by repository.reading.view.collectAsStateWithLifecycle()
    var recent by remember(currentUser?.id) { mutableStateOf<List<SmartLibraryItem>>(emptyList()) }
    var known by remember(currentUser?.id) { mutableStateOf(false) }
    var nextOffset by remember(currentUser?.id) { mutableIntStateOf(0) }
    var rows by remember(currentUser?.id) { mutableStateOf<List<SmartLibraryItem>>(emptyList()) }
    var summary by remember(currentUser?.id) { mutableStateOf(SmartLibrarySummary()) }
    var total by remember(currentUser?.id) { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var loadingMore by remember { mutableStateOf(false) }
    var hasMore by remember(currentUser?.id) { mutableStateOf(false) }
    var error by remember(currentUser?.id) { mutableStateOf<String?>(null) }
    var loadMoreError by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }
    var scopeFilter by rememberSaveable { mutableStateOf("all") }
    var stateFilter by rememberSaveable { mutableStateOf("all") }
    var sort by rememberSaveable { mutableStateOf("activity") }
    var sortMenu by remember { mutableStateOf(false) }
    var dataGeneration by remember { mutableIntStateOf(0) }
    var displayedLibraryKey by remember(currentUser?.id) { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    LaunchedEffect(scopeFilter, stateFilter, sort) {
        listState.scrollToItem(0)
    }

    LaunchedEffect(currentUser?.id, scopeFilter, stateFilter, sort, refreshEpoch, reloadKey) {
        dataGeneration++
        loadingMore = false
        loadMoreError = null
        val accountId = currentUser?.id
        if (accountId == null) {
            rows = emptyList(); hasMore = false; summary = SmartLibrarySummary(); total = 0
            recent = emptyList(); known = false; nextOffset = 0
            displayedLibraryKey = null
            loading = false
            return@LaunchedEffect
        }

        val requestKey = "$accountId|$scopeFilter|$stateFilter|$sort"
        error = null

        // Account-scoped stale-while-revalidate: when Library is revisited after
        // Reader or another tab, restore the matching personal snapshot first and
        // refresh it quietly. Never show rows from a different filter as current.
        val cached = repository.cachedSmartLibrary(
            accountId = accountId,
            scope = scopeFilter,
            state = stateFilter,
            sort = sort,
            offset = 0,
            limit = LIBRARY_PAGE_SIZE,
        )
        if (cached != null) {
            recent = cached.recentlyOpened
            known = true
            nextOffset = cached.offset + cached.items.size
            rows = cached.items
            summary = cached.summary
            total = cached.total
            hasMore = cached.hasMore
            displayedLibraryKey = requestKey
            loading = false
        } else if (displayedLibraryKey != requestKey) {
            recent = emptyList(); known = false; nextOffset = 0
            rows = emptyList()
            summary = SmartLibrarySummary()
            total = 0
            hasMore = false
            loading = true
        } else {
            loading = false
        }

        try {
            val page = repository.smartLibrary(
                accountId = accountId,
                scope = scopeFilter,
                state = stateFilter,
                sort = sort,
                offset = 0,
                limit = LIBRARY_PAGE_SIZE,
            )
            recent = page.recentlyOpened
            known = true
            nextOffset = page.offset + page.items.size
            rows = page.items
            summary = page.summary
            total = page.total
            hasMore = page.hasMore
            displayedLibraryKey = requestKey
            loading = false
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Throwable) {
            // A cached Smart Library is still useful offline/while the server is
            // recovering. Only replace the content area with an error when there
            // is no matching personal snapshot to render.
            error = failure.message ?: "Server under maintenance."
        } finally {
            loading = false
        }
    }

    if (currentUser == null) {
        Box(Modifier.fillMaxSize().padding(contentPadding).padding(24.dp), contentAlignment = Alignment.Center) {
            Surface(color = Ink900, shape = RoundedCornerShape(22.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(Icons.AutoMirrored.Filled.LibraryBooks, null, tint = Brand400, modifier = Modifier.size(40.dp))
                    Text("Your Smart Library", style = MaterialTheme.typography.titleLarge, color = Ink50)
                    Text("Sign in to sync bookmarks, follows, updates and reading history with the web application.", color = Ink400, style = MaterialTheme.typography.bodyMedium)
                    Button(onClick = onLogin, colors = ButtonDefaults.buttonColors(containerColor = Brand600), shape = RoundedCornerShape(12.dp)) { Text("Sign in") }
                }
            }
        }
        return
    }

    ResponsiveFrame(maxContentWidth = 860.dp) { edgePadding ->
        LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            start = edgePadding,
            top = contentPadding.calculateTopPadding() + 16.dp,
            end = edgePadding,
            bottom = contentPadding.calculateBottomPadding() + 28.dp,
        ),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item(key = "library-heading") {
            SectionHeading(
                "Personal",
                "Smart Library",
                "See unread updates, caught-up series and exactly where to continue—without separate lists.",
                action = { IconButton(onClick = onAccount) { Icon(Icons.Default.Person, "Account", tint = Ink300) } },
            )
        }

        item(key = "reading-sync") { ReadingSyncStatus(repository, readingView) }
        if ((scopeFilter == "all" || scopeFilter == "history") && stateFilter == "all") {
            item(key = "pending-reading") { PendingReadingRail(readingView, onRead) }
            if (recent.isNotEmpty()) item(key = "recently-opened") {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Recently opened", style = MaterialTheme.typography.titleMedium, color = Ink50)
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(recent, key = { it.seriesId }) { item ->
                            Box(Modifier.width(320.dp)) { LibraryRow(repository, item, onSeries, onRead) }
                        }
                    }
                }
            }
        }

        if (known) item(key = "library-summary") {
            BoxWithConstraints(Modifier.fillMaxWidth()) {
                if (maxWidth < 390.dp) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            SummaryStat("Updates", summary.updates, Modifier.weight(1f), Brand400) { scopeFilter = "all"; stateFilter = "updates" }
                            SummaryStat("Caught up", summary.caughtUp, Modifier.weight(1f), Color(0xFF5ED7A1)) { scopeFilter = "all"; stateFilter = "caught_up" }
                        }
                        SummaryStat("Not started", summary.notStarted, Modifier.fillMaxWidth(), Ink300) { scopeFilter = "all"; stateFilter = "not_started" }
                    }
                } else {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        SummaryStat("Updates", summary.updates, Modifier.weight(1f), Brand400) { scopeFilter = "all"; stateFilter = "updates" }
                        SummaryStat("Caught up", summary.caughtUp, Modifier.weight(1f), Color(0xFF5ED7A1)) { scopeFilter = "all"; stateFilter = "caught_up" }
                        SummaryStat("Not started", summary.notStarted, Modifier.weight(1f), Ink300) { scopeFilter = "all"; stateFilter = "not_started" }
                    }
                }
            }
        }

        item(key = "library-scopes") {
            val scopes = listOf(
                LibraryFilter("all", "All", Icons.Default.Layers, summary.all),
                LibraryFilter("bookmarks", "Bookmarks", Icons.Default.Bookmark, summary.bookmarks),
                LibraryFilter("following", "Subscriptions", Icons.Default.Notifications, summary.following),
                LibraryFilter("history", "History", Icons.Default.History, summary.history),
            )
            LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp), contentPadding = PaddingValues(end = 8.dp)) {
                items(scopes, key = { it.key }) { item ->
                    val selected = scopeFilter == item.key
                    TextButton(
                        onClick = { scopeFilter = item.key },
                        colors = ButtonDefaults.textButtonColors(contentColor = if (selected) Brand400 else Ink400),
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp),
                    ) {
                        Icon(item.icon, null, modifier = Modifier.size(17.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(item.label, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium)
                        Spacer(Modifier.width(5.dp))
                        Surface(color = Ink800, shape = RoundedCornerShape(20.dp)) {
                            Text(if (known) item.count.toString() else "—", Modifier.padding(horizontal = 6.dp, vertical = 2.dp), style = MaterialTheme.typography.labelSmall, color = Ink300)
                        }
                    }
                }
            }
        }

        item(key = "library-filters") {
            Surface(color = Ink900.copy(alpha = 0.72f), shape = RoundedCornerShape(14.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(7.dp), contentPadding = PaddingValues(end = 6.dp)) {
                        val states = listOf("all" to "All states", "updates" to "Updates", "caught_up" to "Caught up", "not_started" to "Not started")
                        items(states, key = { it.first }) { option ->
                            FilterChip(
                                selected = stateFilter == option.first,
                                onClick = { stateFilter = option.first },
                                label = { Text(option.second) },
                                colors = FilterChipDefaults.filterChipColors(containerColor = Ink800, labelColor = Ink400, selectedContainerColor = Brand600, selectedLabelColor = Color.White),
                            )
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(if (known) "$total series in this view" else "Reading state unavailable", color = Ink500, style = MaterialTheme.typography.labelSmall, modifier = Modifier.weight(1f))
                        Box {
                            OutlinedButton(onClick = { sortMenu = true }, contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp), colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink300)) {
                                Icon(Icons.Default.Sort, null, modifier = Modifier.size(16.dp)); Spacer(Modifier.width(5.dp)); Text(librarySortLabel(sort), style = MaterialTheme.typography.labelSmall)
                            }
                            DropdownMenu(expanded = sortMenu, onDismissRequest = { sortMenu = false }, containerColor = Ink900) {
                                listOf("activity" to "Recent activity", "updated" to "Newest updates", "unread" to "Most unread", "title" to "Title A–Z").forEach { item ->
                                    DropdownMenuItem(text = { Text(item.second) }, onClick = { sort = item.first; sortMenu = false })
                                }
                            }
                        }
                    }
                }
            }
        }

        error?.let { message ->
            item(key = "library-error") {
                Surface(color = Color(0xFF3A2A11), shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Color(0xFF815C1C))) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(message, color = Color(0xFFFFD58A), style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                        TextButton(onClick = { reloadKey++ }) { Text("Retry") }
                    }
                }
            }
        }

        if (loading && rows.isEmpty()) {
            item(key = "library-loading") { Box(Modifier.fillMaxWidth().padding(vertical = 42.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Brand400) } }
        } else if (rows.isEmpty() && known) {
            item(key = "library-empty") {
                Surface(color = Ink900, shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                    Column(Modifier.fillMaxWidth().padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(7.dp)) {
                        Icon(Icons.AutoMirrored.Filled.LibraryBooks, null, tint = Ink500, modifier = Modifier.size(28.dp))
                        Text(emptyLibraryTitle(stateFilter), color = Ink200, style = MaterialTheme.typography.titleMedium)
                        Text(emptyLibraryBody(stateFilter), color = Ink500, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        } else {
            items(rows, key = { it.seriesId }) { item -> LibraryRow(repository, item, onSeries, onRead) }
            if (hasMore || loadingMore) {
                item(key = "library-more") {
                    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        loadMoreError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                        if (loadingMore) CircularProgressIndicator(modifier = Modifier.size(28.dp), strokeWidth = 2.dp, color = Brand400)
                        else OutlinedButton(
                            onClick = {
                                val generation = dataGeneration
                                val requestedScope = scopeFilter
                                val requestedState = stateFilter
                                val requestedSort = sort
                                val requestedOffset = nextOffset
                                val requestedAccount = currentUser?.id
                                loadingMore = true
                                loadMoreError = null
                                scope.launch {
                                    try {
                                        val accountId = currentUser?.id ?: return@launch
                                        val page = repository.smartLibrary(
                                            accountId = accountId,
                                            scope = requestedScope,
                                            state = requestedState,
                                            sort = requestedSort,
                                            offset = requestedOffset,
                                            limit = LIBRARY_PAGE_SIZE,
                                        )
                                        if (generation == dataGeneration && requestedScope == scopeFilter && requestedState == stateFilter && requestedSort == sort && requestedOffset == nextOffset && currentUser?.id == requestedAccount) {
                                            rows = (rows + page.items).distinctBy { it.seriesId }
                                            nextOffset = page.offset + page.items.size
                                            hasMore = page.hasMore
                                        }
                                    } catch (cancelled: CancellationException) {
                                        throw cancelled
                                    } catch (failure: Throwable) {
                                        if (generation == dataGeneration) loadMoreError = failure.message ?: "Could not load more library items."
                                    } finally {
                                        if (generation == dataGeneration) loadingMore = false
                                    }
                                }
                            },
                        ) { Text("Load more") }
                    }
                }
            }
        }
    }
    }
}

private data class LibraryFilter(val key: String, val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector, val count: Int)

@Composable
private fun LibraryRow(repository: MReaderRepository, item: SmartLibraryItem, onSeries: (String) -> Unit, onRead: (String, String) -> Unit) {
    val view by repository.reading.view.collectAsStateWithLifecycle()
    val pending = view.pending(item.seriesId)
    val primary = pending?.let { Triple(it.target.chapterSlug, it.target.chapterNumber as Double?, "Continue") }
        ?: item.readingAction?.takeIf { item.readingAvailable }?.let { action ->
            val number = when (action.chapterId) {
                item.nextChapterId -> item.nextChapterNumber
                item.resumeChapterId -> item.resumeChapterNumber
                item.firstChapterId -> item.firstChapterNumber
                else -> item.latestChapterNumber
            }
            Triple(action.chapterSlug, number, when (action.kind) { "next" -> "Read next"; "start" -> "Start"; else -> "Continue" })
        }

    Surface(
        modifier = Modifier.fillMaxWidth().clickable { onSeries(item.seriesSlug) },
        color = Ink900,
        shape = RoundedCornerShape(16.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
    ) {
        Row(Modifier.padding(11.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            NetworkImage(
                repository,
                item.seriesCover?.let(repository.api::coverUrl),
                item.seriesTitle,
                Modifier.width(88.dp).aspectRatio(2f / 3f).clip(RoundedCornerShape(11.dp)),
                ContentScale.Crop,
            )
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        item.seriesTitle,
                        modifier = Modifier.weight(1f),
                        style = MaterialTheme.typography.titleMedium,
                        color = Ink50,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(item.seriesStatus.replaceFirstChar { it.uppercase() }, color = Ink500, style = MaterialTheme.typography.labelSmall)
                }

                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (item.readingAvailable) LibraryStatePill(item)
                    else Text("No published chapter", style = MaterialTheme.typography.labelSmall)
                    if (pending != null) Text("Pending sync", style = MaterialTheme.typography.labelSmall, color = Brand400)
                    if (item.bookmarked) Icon(Icons.Default.Bookmark, "Saved", tint = Brand400, modifier = Modifier.size(15.dp))
                    if (item.followed) Icon(Icons.Default.Notifications, "Subscribed", tint = Gold400, modifier = Modifier.size(15.dp))
                }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    LibraryChapterStat(
                        label = "Reached",
                        value = item.furthestChapterNumber?.let { "Ch. ${formatChapterNumber(it)}" } ?: "Not started",
                        modifier = Modifier.weight(1f),
                    )
                    LibraryChapterStat(
                        label = "Latest",
                        value = item.latestChapterNumber?.let { "Ch. ${formatChapterNumber(it)}" } ?: "No chapters",
                        modifier = Modifier.weight(1f),
                    )
                }

                val activityText = when (item.readState) {
                    "updates" -> "${item.unreadChapterCount} chapter${if (item.unreadChapterCount == 1) "" else "s"} waiting"
                    "not_started" -> "${item.publishedChapterCount} chapter${if (item.publishedChapterCount == 1) "" else "s"} available"
                    else -> item.readAt?.let { "Last opened ${relativeTime(it)}" }
                }
                val updatedText = item.latestPublishedAt
                    ?.takeIf { item.readState != "caught_up" }
                    ?.let { "Updated ${relativeTime(it)}" }
                if (!activityText.isNullOrBlank() || !updatedText.isNullOrBlank()) {
                    Text(
                        listOfNotNull(activityText, updatedText).filter { it.isNotBlank() }.joinToString(" · "),
                        color = Ink500,
                        style = MaterialTheme.typography.labelSmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }

                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (primary != null) {
                        Button(
                            onClick = { onRead(item.seriesSlug, primary.first) },
                            colors = ButtonDefaults.buttonColors(containerColor = Brand600),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                            shape = RoundedCornerShape(10.dp),
                        ) {
                            Icon(Icons.Default.PlayArrow, null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("${primary.third} · Ch. ${formatChapterNumber(primary.second)}")
                        }
                    } else {
                        OutlinedButton(onClick = { onSeries(item.seriesSlug) }) { Text("Open series") }
                    }
                }

                if (
                    pending == null && item.readingAvailable && item.readState == "updates" &&
                    item.resumeChapterSlug != null &&
                    item.resumeChapterSlug != item.nextChapterSlug
                ) {
                    TextButton(
                        onClick = { onRead(item.seriesSlug, item.resumeChapterSlug) },
                        contentPadding = PaddingValues(horizontal = 0.dp, vertical = 0.dp),
                    ) {
                        Text("Resume Ch. ${formatChapterNumber(item.resumeChapterNumber)}", color = Ink400, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}

@Composable
private fun LibraryStatePill(item: SmartLibraryItem) {
    val (label, icon, color) = when (item.readState) {
        "updates" -> Triple("${item.unreadChapterCount} new", Icons.Default.AutoAwesome, Brand400)
        "caught_up" -> Triple("Caught up", Icons.Default.CheckCircle, Color(0xFF5ED7A1))
        else -> Triple("Not started", Icons.AutoMirrored.Filled.LibraryBooks, Ink300)
    }
    Surface(color = color.copy(alpha = 0.14f), shape = RoundedCornerShape(20.dp)) {
        Row(
            Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Icon(icon, null, tint = color, modifier = Modifier.size(13.dp))
            Text(label, color = color, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun LibraryChapterStat(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(1.dp)) {
        Text(label, color = Ink500, style = MaterialTheme.typography.labelSmall)
        Text(value, color = Ink300, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

private fun librarySortLabel(value: String) = when (value) { "updated" -> "Newest"; "unread" -> "Unread"; "title" -> "A–Z"; else -> "Activity" }
private fun emptyLibraryTitle(state: String) = when (state) { "updates" -> "No unread updates"; "caught_up" -> "Nothing caught up here"; "not_started" -> "Nothing waiting to start"; else -> "Your Library is empty" }
private fun emptyLibraryBody(state: String) = when (state) { "updates" -> "New chapters will surface here automatically."; "caught_up" -> "Keep reading and caught-up series will collect here."; "not_started" -> "Save or follow a series before reading it and it will appear here."; else -> "Bookmark, follow, or start reading a series and it becomes part of your Smart Library." }
