package com.mreader.android.ui.screens

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mreader.android.core.codec.ProtectedPageDecoder
import com.mreader.android.core.model.ReaderManifest
import com.mreader.android.core.model.ReaderPage
import com.mreader.android.core.network.ApiException
import com.mreader.android.core.repository.ReaderProgressMath
import com.mreader.android.core.repository.ReaderLayoutPolicy
import com.mreader.android.core.repository.ReaderVariantPolicy
import com.mreader.android.core.repository.ProgressSelectionPolicy
import com.mreader.android.ui.AppViewModel
import com.mreader.android.ui.components.ReadingSyncStatus
import com.mreader.android.ui.components.CommentSection
import com.mreader.android.ui.components.formatChapterNumber
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import java.io.IOException
import kotlin.math.abs

private const val READER_PAGE_START_INDEX = 2

private sealed interface PageLoadState {
    data object Loading : PageLoadState
    data class Ready(val bitmap: Bitmap) : PageLoadState
    data class Failed(val message: String) : PageLoadState
}

private data class ReaderSnapshot(
    val lastPage: Int,
    val scrollPosition: Double,
    val completed: Boolean = false,
)

private data class PageVariant(
    val path: String,
    val width: Int?,
    val height: Int?,
)

private data class EncodedPageLoad(
    val bytes: ByteArray,
    val servedFromCache: Boolean,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReaderScreen(
    appViewModel: AppViewModel,
    seriesSlug: String,
    chapterSlug: String,
    onBack: () -> Unit,
    onChapter: (String, String) -> Unit,
    onLogin: () -> Unit,
    onWebFallback: () -> Unit,
) {
    val repository = appViewModel.repository
    val currentUser by appViewModel.user.collectAsStateWithLifecycle()
    val readingView by appViewModel.reading.collectAsStateWithLifecycle()
    val configuration = LocalConfiguration.current
    val density = LocalDensity.current.density
    val screenWidthDp = configuration.screenWidthDp
    val screenWidthPx = screenWidthDp * density
    var manifest by remember(seriesSlug, chapterSlug) { mutableStateOf<ReaderManifest?>(null) }
    var chapterToken by remember(seriesSlug, chapterSlug) { mutableStateOf("") }
    var loading by remember(seriesSlug, chapterSlug) { mutableStateOf(true) }
    var error by remember(seriesSlug, chapterSlug) { mutableStateOf<String?>(null) }
    var loadAttempt by remember(seriesSlug, chapterSlug) { mutableIntStateOf(0) }
    var progressReady by remember(seriesSlug, chapterSlug) { mutableStateOf(false) }
    var lastCheckpointSnapshot by remember(seriesSlug, chapterSlug) { mutableStateOf<ReaderSnapshot?>(null) }
    var chapterEndReached by remember(seriesSlug, chapterSlug) { mutableStateOf(false) }
    val listState = key(seriesSlug, chapterSlug) { rememberLazyListState() }
    var visitId by remember(seriesSlug, chapterSlug, currentUser?.id) { mutableStateOf<String?>(null) }
    var userInteracted by remember(seriesSlug, chapterSlug, currentUser?.id) { mutableStateOf(false) }
    val decodedPages = remember(seriesSlug, chapterSlug) { mutableStateMapOf<Int, Boolean>() }
    val interactionObserver = remember(seriesSlug, chapterSlug, currentUser?.id) {
        object : NestedScrollConnection {
            override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                if (source == NestedScrollSource.UserInput && available.y != 0f) userInteracted = true
                return Offset.Zero
            }
        }
    }

    val progressUnits = remember(manifest?.chapterId, screenWidthDp, screenWidthPx) {
        manifest?.pages.orEmpty().map { page ->
            val variant = selectVariant(page, screenWidthDp, screenWidthPx)
            ReaderProgressMath.PageUnit(
                pageNumber = page.pageNumber,
                relativeHeight = ReaderLayoutPolicy.pageRelativeHeight(variant.width, variant.height, screenWidthDp),
            )
        }
    }

    val readerProgress by remember(manifest?.chapterId, progressUnits, listState) {
        derivedStateOf {
            val loaded = manifest
            if (loaded == null || loaded.pages.isEmpty()) 0f
            else (currentReaderSnapshot(loaded, listState, progressUnits)?.scrollPosition ?: 0.0)
                .toFloat()
                .coerceIn(0f, 1f)
        }
    }
    val currentReaderPage by remember(manifest?.chapterId, progressUnits, listState) {
        derivedStateOf {
            val loaded = manifest
            if (loaded == null || loaded.pages.isEmpty()) null
            else currentReaderSnapshot(loaded, listState, progressUnits)?.lastPage ?: loaded.pages.first().pageNumber
        }
    }
    val showJumpToTop by remember(listState) { derivedStateOf { listState.firstVisibleItemIndex > 4 } }
    val readerScope = rememberCoroutineScope()

    // Chapter availability is intentionally independent from both Auth profile
    // initialization and reading-progress restoration. Reader manifests support
    // guest access, so the chapter starts loading immediately after navigation.
    LaunchedEffect(seriesSlug, chapterSlug, loadAttempt) {
        loading = true
        error = null
        progressReady = false
        manifest = null
        lastCheckpointSnapshot = null
        try {
            val loaded = repository.reader(seriesSlug, chapterSlug)
            manifest = loaded
            chapterToken = loaded.chapterToken
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Throwable) {
            error = failure.message ?: "Could not open this chapter."
        } finally {
            loading = false
        }
    }

    // Signed-in users get a best-effort 24-hour encoded chapter download. The
    // work is owned by AppViewModel, so navigating back to Browse does not cancel
    // it. Guests keep memory-only streaming/prefetch and never receive persistent
    // chapter cache privileges.
    LaunchedEffect(manifest?.chapterId, currentUser?.id, screenWidthDp, screenWidthPx) {
        val loaded = manifest ?: return@LaunchedEffect
        if (currentUser != null) {
            appViewModel.cacheChapterFor24Hours(loaded, screenWidthDp, screenWidthPx)
        }
    }

    // The local open exists before any network read. Capture keeps running while
    // restoration waits, and a user gesture permanently fences late restoration.
    LaunchedEffect(manifest?.chapterId, currentUser?.id, readingView.resetEpoch) {
        val loaded = manifest ?: return@LaunchedEffect
        val openedVisit = appViewModel.recordChapterOpen(loaded) ?: return@LaunchedEffect
        visitId = openedVisit
        progressReady = false
        userInteracted = false
        chapterEndReached = false
        suspend fun restore(saved: com.mreader.android.core.model.ReadingProgress?) {
            if (saved == null || userInteracted || visitId != openedVisit || loaded.pages.isEmpty()) return
            val units = loaded.pages.map { page ->
                val variant = selectVariant(page, screenWidthDp, screenWidthPx)
                ReaderProgressMath.PageUnit(page.pageNumber,
                    ReaderLayoutPolicy.pageRelativeHeight(variant.width, variant.height, screenWidthDp))
            }
            val location = ReaderProgressMath.locationFromChapterFraction(units, saved.scrollPosition)
            val index = loaded.pages.indexOfFirst { it.pageNumber == location?.pageNumber }
                .let { if (it < 0) loaded.pages.indexOfFirst { page -> page.pageNumber >= saved.lastPage } else it }
                .let { if (it < 0) loaded.pages.lastIndex else it }
            val page = loaded.pages[index]
            val variant = selectVariant(page, screenWidthDp, screenWidthPx)
            val within = location?.takeIf { it.pageNumber == page.pageNumber }?.withinPageFraction
                ?: ReaderProgressMath.pageFractionFromChapterFraction(units, page.pageNumber, saved.scrollPosition)
            val height = ReaderLayoutPolicy.pageRelativeHeight(variant.width, variant.height, screenWidthDp) * screenWidthPx
            if (!userInteracted) {
                listState.scrollToItem(index + READER_PAGE_START_INDEX, (height * within).toInt().coerceAtLeast(0))
                if (!userInteracted) lastCheckpointSnapshot = ReaderSnapshot(saved.lastPage, saved.scrollPosition)
            }
        }
        try {
            coroutineScope {
                val remote = async {
                    withTimeoutOrNull(4_000L) {
                        try { repository.reading.serverCheckpoint(openedVisit) }
                        catch (cancelled: CancellationException) { throw cancelled }
                        catch (_: Exception) { null }
                    }
                }
                val local = repository.reading.localCheckpoint(openedVisit)
                if (local != null) {
                    restore(ProgressSelectionPolicy.choose(local, null))
                    chapterEndReached = local.completed
                    progressReady = true
                }
                val server = remote.await()
                if (local == null) restore(server)
            }
        } catch (cancelled: CancellationException) { throw cancelled
        } catch (_: Exception) {
            // Failure to restore a checkpoint does not stop protected media.
        } finally {
            if (visitId == openedVisit) progressReady = true
        }
    }

    LaunchedEffect(manifest?.chapterId, visitId, progressUnits) {
        val loaded = manifest ?: return@LaunchedEffect
        val openedVisit = visitId ?: return@LaunchedEffect
        snapshotFlow {
            val snapshot = currentReaderSnapshot(loaded, listState, progressUnits)
            val mediaReady = loaded.pageCount > 0 && loaded.pages.size == loaded.pageCount &&
                loaded.pages.all { decodedPages[it.pageNumber] == true }
            if (userInteracted || (snapshot?.completed == true && mediaReady)) snapshot?.copy(completed = snapshot.completed && mediaReady) else null
        }.filterNotNull().collect { snapshot ->
            val newlyCompleted = snapshot.completed && !chapterEndReached
            chapterEndReached = chapterEndReached || snapshot.completed
            val checkpoint = snapshot.copy(completed = chapterEndReached)
            lastCheckpointSnapshot = checkpoint
            appViewModel.checkpointProgress(openedVisit, checkpoint.lastPage, checkpoint.scrollPosition,
                checkpoint.completed, commitServer = newlyCompleted)
        }
    }

    // Network-only prefetch. Encoded bytes are warmed around the viewport,
    // while bitmap reconstruction remains demand-driven to protect Android heap.
    LaunchedEffect(manifest?.chapterId, currentReaderPage, chapterToken, screenWidthDp) {
        val loaded = manifest ?: return@LaunchedEffect
        val activePage = currentReaderPage ?: loaded.pages.firstOrNull()?.pageNumber ?: return@LaunchedEffect
        try {
            repository.prefetchReaderWindow(
                manifest = loaded,
                centerPageNumber = activePage,
                chapterToken = chapterToken,
                screenWidthDp = screenWidthDp,
                screenWidthPx = screenWidthPx,
                persistentCacheEnabled = currentUser != null,
                ahead = 3,
                behind = 2,
            )
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Throwable) {
            // Prefetch is an optimization only; visible-page loading remains authoritative.
        }
    }

    // The repository owns the dirty-only interval. Exit only captures the final
    // local position and asks the same queue to flush; no second commit path.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, visitId) {
        val leavingVisit = visitId
        val leavingManifest = manifest
        fun finishVisit() {
            if (leavingVisit != null && leavingManifest != null && userInteracted) {
                val snapshot = currentReaderSnapshot(leavingManifest, listState, progressUnits) ?: lastCheckpointSnapshot
                if (snapshot != null) appViewModel.checkpointProgress(leavingVisit, snapshot.lastPage,
                    snapshot.scrollPosition, chapterEndReached, commitServer = true)
            }
            repository.reading.flush()
        }
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) finishVisit()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            finishVisit()
        }
    }

    Scaffold(
        containerColor = Ink950,
        topBar = {
            Column {
                TopAppBar(
                    title = {
                        val m = manifest
                        Column {
                            Text(
                                if (m == null) "Reader" else m.seriesTitle,
                                maxLines = 1,
                                style = MaterialTheme.typography.titleMedium,
                            )
                            if (m != null) {
                                Text(
                                    "Chapter ${formatChapterNumber(m.chapterNumber)}",
                                    maxLines = 1,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = Ink500,
                                )
                            }
                        }
                    },
                    navigationIcon = {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back to chapters")
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Ink900,
                        titleContentColor = Ink50,
                        navigationIconContentColor = Ink200,
                    ),
                )
                if (manifest?.pages?.isNotEmpty() == true) {
                    LinearProgressIndicator(
                        progress = { readerProgress },
                        modifier = Modifier.fillMaxWidth().height(3.dp),
                        color = Brand400,
                        trackColor = Ink800,
                    )
                }
            }
        },
        floatingActionButton = {
            if (showJumpToTop && manifest != null) {
                SmallFloatingActionButton(
                    onClick = { userInteracted = true; readerScope.launch { listState.animateScrollToItem(0) } },
                    containerColor = Brand600,
                    contentColor = androidx.compose.ui.graphics.Color.White,
                ) {
                    Icon(Icons.Default.KeyboardArrowUp, contentDescription = "Back to top")
                }
            }
        },
    ) { padding ->
        when {
            loading -> Box(
                Modifier.fillMaxSize().padding(padding),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(color = Brand400)
                    Text("Opening chapter…", style = MaterialTheme.typography.bodySmall, color = Ink500)
                }
            }

            error != null -> Box(
                Modifier.fillMaxSize().padding(padding).padding(24.dp),
                contentAlignment = Alignment.Center,
            ) {
                Surface(
                    color = Ink900,
                    shape = androidx.compose.foundation.shape.RoundedCornerShape(18.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
                ) {
                    Column(
                        Modifier.padding(20.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text("This chapter could not be opened", style = MaterialTheme.typography.titleMedium, color = Ink50)
                        Text(error.orEmpty(), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = onBack) { Text("Chapters") }
                            TextButton(onClick = onWebFallback) { Text("Web reader") }
                            Button(onClick = { loadAttempt++ }, colors = ButtonDefaults.buttonColors(containerColor = Brand600)) {
                                Icon(Icons.Default.Refresh, null)
                                Spacer(Modifier.width(6.dp))
                                Text("Retry")
                            }
                        }
                    }
                }
            }

            manifest != null -> {
                val m = requireNotNull(manifest)
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize().background(Ink950).nestedScroll(interactionObserver),
                    contentPadding = PaddingValues(
                        top = padding.calculateTopPadding(),
                        bottom = padding.calculateBottomPadding() + 28.dp,
                    ),
                ) {
                    item(key = "reader-intro") {
                        Column(
                            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Text(
                                "CHAPTER ${formatChapterNumber(m.chapterNumber)}",
                                style = MaterialTheme.typography.labelSmall,
                                color = Brand400,
                            )
                            Text(m.seriesTitle, style = MaterialTheme.typography.headlineSmall, color = Ink50)
                            ReadingSyncStatus(repository, readingView, m.seriesId)
                            Text(
                                "Native protected reader",
                                style = MaterialTheme.typography.bodySmall,
                                color = Ink500,
                            )
                        }
                    }
                    item(key = "top-nav") {
                        ChapterNavigation(m, onBack, onChapter, Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
                    }
                    if (m.pages.isEmpty()) {
                        item(key = "empty-pages") {
                            Box(Modifier.fillParentMaxHeight(0.65f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                                Text("This chapter does not contain any published pages.", color = Ink400)
                            }
                        }
                    } else {
                        items(
                            count = m.pages.size,
                            key = { index -> "${m.chapterId}:${m.pages[index].pageNumber}" },
                        ) { index ->
                            ProtectedPage(
                                appViewModel = appViewModel,
                                manifest = m,
                                page = m.pages[index],
                                chapterToken = chapterToken,
                                screenWidthDp = screenWidthDp,
                                screenWidthPx = screenWidthPx,
                                persistentCacheEnabled = currentUser != null,
                                onTokenRefreshed = { chapterToken = it },
                                onWebFallback = onWebFallback,
                                onDecoded = { decodedPages[m.pages[index].pageNumber] = true },
                            )
                        }
                    }
                    if (m.pages.isNotEmpty() && m.nextChapter == null) {
                        item(key = "caught-up") {
                            Surface(
                                modifier = Modifier.fillMaxWidth().padding(12.dp),
                                color = Brand950.copy(alpha = 0.42f),
                                shape = androidx.compose.foundation.shape.RoundedCornerShape(18.dp),
                                border = androidx.compose.foundation.BorderStroke(1.dp, Brand800),
                            ) {
                                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                                    Text("YOU’RE CAUGHT UP", style = MaterialTheme.typography.labelSmall, color = Gold400)
                                    Text("That’s the latest published chapter.", style = MaterialTheme.typography.titleMedium, color = Ink50)
                                    Text("Return to the series page to bookmark, follow, rate, or choose another chapter.", style = MaterialTheme.typography.bodySmall, color = Ink400)
                                }
                            }
                        }
                    }
                    item(key = "bottom-nav") {
                        ChapterNavigation(m, onBack, onChapter, Modifier.padding(12.dp))
                    }
                    item(key = "chapter-discussion") {
                        CommentSection(
                            repository = repository,
                            currentUser = currentUser,
                            seriesId = m.seriesId,
                            chapterId = m.chapterId,
                            title = "Chapter discussion",
                            onLogin = onLogin,
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 12.dp),
                        )
                    }
                }
            }
        }
    }

}

private fun currentReaderSnapshot(
    manifest: ReaderManifest,
    listState: LazyListState,
    progressUnits: List<ReaderProgressMath.PageUnit>,
): ReaderSnapshot? {
    val layout = listState.layoutInfo
    val pages = manifest.pages
    val pageEndExclusive = READER_PAGE_START_INDEX + pages.size
    val visiblePages = layout.visibleItemsInfo.filter { it.index in READER_PAGE_START_INDEX until pageEndExclusive }
    if (visiblePages.isEmpty()) {
        if (pages.isNotEmpty() && layout.visibleItemsInfo.any { it.index >= pageEndExclusive }) {
            return ReaderSnapshot(pages.last().pageNumber, 1.0, completed = true)
        }
        return null
    }

    val center = (layout.viewportStartOffset + layout.viewportEndOffset) / 2
    val active = visiblePages.minByOrNull { info -> abs((info.offset + info.size / 2) - center) } ?: return null
    val activePage = pages[active.index - READER_PAGE_START_INDEX].pageNumber

    val top = visiblePages.minByOrNull { it.index } ?: active
    val topPage = pages[top.index - READER_PAGE_START_INDEX].pageNumber
    val withinTop = if (top.size <= 0) {
        0.0
    } else {
        (layout.viewportStartOffset - top.offset).toDouble().div(top.size).coerceIn(0.0, 1.0)
    }
    val chapterFraction = ReaderProgressMath.chapterFraction(progressUnits, topPage, withinTop)
    val completed = layout.visibleItemsInfo.any { it.index >= pageEndExclusive }
    return ReaderSnapshot(activePage, chapterFraction, completed)
}

private fun selectVariants(page: ReaderPage, screenWidthDp: Int, screenWidthPx: Float): List<PageVariant> {
    val primary = PageVariant(page.imagePath, page.width, page.height)
    val responsive = if (
        !page.responsiveImagePath.isNullOrBlank() &&
        page.responsiveWidth != null && page.responsiveHeight != null
    ) {
        PageVariant(requireNotNull(page.responsiveImagePath), page.responsiveWidth, page.responsiveHeight)
    } else null

    // Select derivatives from the full edge-to-edge reader width. High-DPR
    // devices still keep primary assets whenever the responsive derivative would
    // undersupply physical pixels.
    val contentWidthDp = ReaderLayoutPolicy.contentWidthDp(screenWidthDp)
    val contentWidthPx = ReaderLayoutPolicy.contentWidthPx(screenWidthDp, screenWidthPx)
    return if (ReaderVariantPolicy.preferResponsive(contentWidthDp, contentWidthPx, responsive?.width)) {
        listOfNotNull(responsive, primary).distinctBy { it.path }
    } else {
        listOfNotNull(primary, responsive).distinctBy { it.path }
    }
}

private fun selectVariant(page: ReaderPage, screenWidthDp: Int, screenWidthPx: Float): PageVariant =
    selectVariants(page, screenWidthDp, screenWidthPx).first()


@Composable
private fun ChapterNavigation(
    manifest: ReaderManifest,
    onBackToSeries: () -> Unit,
    onChapter: (String, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = Ink900,
        shape = androidx.compose.foundation.shape.RoundedCornerShape(14.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
    ) {
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val compact = maxWidth < 390.dp
            Row(
                Modifier.fillMaxWidth().padding(horizontal = if (compact) 6.dp else 10.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedButton(
                    onClick = { manifest.prevChapter?.let { onChapter(manifest.seriesSlug, it.slug) } },
                    enabled = manifest.prevChapter != null,
                    contentPadding = PaddingValues(horizontal = if (compact) 8.dp else 12.dp, vertical = 7.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink200),
                ) {
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, null)
                    if (!compact) Text("Previous")
                }
                TextButton(
                    onClick = onBackToSeries,
                    contentPadding = PaddingValues(horizontal = if (compact) 7.dp else 10.dp, vertical = 7.dp),
                    colors = ButtonDefaults.textButtonColors(contentColor = Ink400),
                ) {
                    Icon(Icons.Default.List, contentDescription = null, modifier = Modifier.size(16.dp))
                    if (!compact) { Spacer(Modifier.width(4.dp)); Text("Chapters", style = MaterialTheme.typography.labelMedium) }
                }
                OutlinedButton(
                    onClick = { manifest.nextChapter?.let { onChapter(manifest.seriesSlug, it.slug) } },
                    enabled = manifest.nextChapter != null,
                    contentPadding = PaddingValues(horizontal = if (compact) 8.dp else 12.dp, vertical = 7.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink200),
                ) {
                    if (!compact) Text("Next")
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
                }
            }
        }
    }
}

@Composable
private fun ProtectedPage(
    appViewModel: AppViewModel,
    manifest: ReaderManifest,
    page: ReaderPage,
    chapterToken: String,
    screenWidthDp: Int,
    screenWidthPx: Float,
    persistentCacheEnabled: Boolean,
    onTokenRefreshed: (String) -> Unit,
    onWebFallback: () -> Unit,
    onDecoded: () -> Unit,
) {
    val repository = appViewModel.repository
    val variants = remember(page, screenWidthDp, screenWidthPx) { selectVariants(page, screenWidthDp, screenWidthPx) }
    val preferred = variants.first()
    val aspect = if (preferred.width != null && preferred.height != null && preferred.width > 0 && preferred.height > 0) {
        preferred.width.toFloat() / preferred.height.toFloat()
    } else 0.7f
    val decodeWidthPx = ReaderLayoutPolicy.decodeWidthPx(screenWidthDp, screenWidthPx)
    var retry by remember(page.pageNumber) { mutableIntStateOf(0) }

    val state by produceState<PageLoadState>(PageLoadState.Loading, page.pageNumber, preferred.path, retry) {
        value = PageLoadState.Loading
        value = try {
            var activeToken = chapterToken
            val failures = mutableListOf<String>()

            suspend fun ensureToken(): String {
                if (activeToken.isNotBlank()) return activeToken
                activeToken = repository.refreshChapterToken(
                    manifest.seriesSlug, manifest.chapterSlug, "",
                )
                onTokenRefreshed(activeToken)
                return activeToken
            }

            suspend fun fetchAuthorized(variantKind: String): ByteArray {
                suspend fun fetch(token: String): ByteArray {
                    val response = repository.api.mobileReaderPage(
                        manifest.seriesSlug,
                        manifest.chapterSlug,
                        page.pageNumber,
                        variantKind,
                        token,
                    )
                    val type = response.contentType.orEmpty().lowercase()
                    if (type.startsWith("text/") || type.contains("json") || response.bytes.isEmpty()) {
                        throw IOException("Mobile reader adapter returned invalid protected page data.")
                    }
                    return response.bytes
                }

                var token = ensureToken()
                return try {
                    fetch(token)
                } catch (api: ApiException) {
                    if (api.status != 401 && api.status != 403) throw api
                    activeToken = repository.refreshChapterToken(
                        manifest.seriesSlug, manifest.chapterSlug, token,
                    )
                    onTokenRefreshed(activeToken)
                    token = activeToken
                    fetch(token)
                }
            }

            suspend fun loadVariant(variant: PageVariant): Bitmap {
                val path = variant.path
                val width = variant.width
                val height = variant.height
                if (page.encodingVersion != 4) {
                    throw IOException("Unsupported page encoding v${page.encodingVersion}; MReader requires v4.")
                }

                // Possessing the current chapter grant is required before the
                // token-independent encrypted bytes are reused from app cache. The
                // shared per-object lock deduplicates this visible fetch against both
                // viewport prefetch and the signed-in background chapter download.
                val encodedLoad = repository.withProtectedAssetLock(path) { lockedIdentity ->
                    ensureToken()
                    val cacheableProtected = page.encodingVersion == 4 && activeToken.isNotBlank()
                    val persistThisPage = persistentCacheEnabled && cacheableProtected
                    var servedFromCache = false
                    var encoded = if (cacheableProtected) {
                        repository.assetStore.read(lockedIdentity, persistent = persistThisPage)
                            ?.also { servedFromCache = true }
                    } else null

                    if (encoded == null) {
                        encoded = fetchAuthorized(if (variant.path == page.responsiveImagePath) "responsive" else "primary")
                        if (cacheableProtected) repository.assetStore.write(lockedIdentity, encoded, persistent = persistThisPage)
                    }
                    EncodedPageLoad(requireNotNull(encoded), servedFromCache)
                }
                val encoded = encodedLoad.bytes
                val servedFromCache = encodedLoad.servedFromCache
                val cacheableProtected = page.encodingVersion == 4 && activeToken.isNotBlank()
                val persistThisPage = persistentCacheEnabled && cacheableProtected

                val finalWidth = width ?: throw IOException("Page width is missing from the reader manifest.")
                val finalHeight = height ?: throw IOException("Page height is missing from the reader manifest.")
                val rows = page.encodingRows ?: throw IOException("Protected-page rows are missing.")
                val columns = page.encodingColumns ?: throw IOException("Protected-page columns are missing.")
                val seed = page.encodingSeed ?: manifest.chapterEncodingSeed
                    ?: throw IOException("Protected-page seed is missing.")
                val encoding = ProtectedPageDecoder.Encoding(
                    version = page.encodingVersion,
                    width = finalWidth,
                    height = finalHeight,
                    rows = rows,
                    columns = columns,
                    seed = seed,
                    pageNumber = page.pageNumber,
                )

                return try {
                    repository.decodeProtectedPage(encoded, encoding, decodeWidthPx)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (decodeFailure: Throwable) {
                    if (!servedFromCache) throw decodeFailure
                    val fresh = repository.withProtectedAssetLock(path) { lockedIdentity ->
                        repository.assetStore.evict(lockedIdentity)
                        val downloaded = fetchAuthorized(if (variant.path == page.responsiveImagePath) "responsive" else "primary")
                        if (cacheableProtected) repository.assetStore.write(lockedIdentity, downloaded, persistent = persistThisPage)
                        downloaded
                    }
                    repository.decodeProtectedPage(fresh, encoding, decodeWidthPx)
                }
            }

            var bitmap: Bitmap? = null
            for ((index, variant) in variants.withIndex()) {
                try {
                    bitmap = loadVariant(variant)
                    break
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (failure: Throwable) {
                    failures += "${if (index == 0) "preferred" else "fallback"} ${variant.width ?: "?"}px: ${failure.message ?: failure::class.java.simpleName}"
                }
            }
            if (bitmap == null) {
                throw IOException(
                    buildString {
                        append("Could not load page ${page.pageNumber}.")
                        if (failures.isNotEmpty()) append(" ").append(failures.joinToString(" • ").take(520))
                    },
                )
            }
            PageLoadState.Ready(requireNotNull(bitmap))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Throwable) {
            PageLoadState.Failed(failure.message ?: "Could not load page ${page.pageNumber}.")
        }
    }


    LaunchedEffect(state) {
        if (state is PageLoadState.Ready) onDecoded()
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(aspect)
            .background(Ink950),
        contentAlignment = Alignment.Center,
    ) {
        when (val pageState = state) {
            PageLoadState.Loading -> Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(color = Brand400, strokeWidth = 2.dp, modifier = Modifier.size(30.dp))
                Text("Loading page ${page.pageNumber}…", style = MaterialTheme.typography.labelSmall, color = Ink500)
            }
            is PageLoadState.Ready -> Image(
                bitmap = pageState.bitmap.asImageBitmap(),
                contentDescription = "Page ${page.pageNumber}",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.FillWidth,
            )
            is PageLoadState.Failed -> Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("Page ${page.pageNumber} could not be displayed", style = MaterialTheme.typography.titleSmall, color = Ink200)
                Text(pageState.message, style = MaterialTheme.typography.bodySmall, color = Ink400)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { retry++ }) {
                        Icon(Icons.Default.Refresh, null)
                        Spacer(Modifier.width(4.dp))
                        Text("Retry")
                    }
                    TextButton(onClick = onWebFallback) { Text("Web fallback") }
                }
            }
        }
    }
}
