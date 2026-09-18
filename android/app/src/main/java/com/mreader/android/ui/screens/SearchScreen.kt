package com.mreader.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.mreader.android.core.model.Genre
import com.mreader.android.core.model.Series
import com.mreader.android.core.model.SeriesSocialMetrics
import com.mreader.android.core.model.Tag
import com.mreader.android.core.repository.MReaderRepository
import com.mreader.android.core.repository.bestEffort
import com.mreader.android.ui.components.MReaderBrand
import com.mreader.android.ui.components.ResponsiveFrame
import com.mreader.android.ui.components.adaptivePosterMinWidth
import com.mreader.android.ui.components.SectionHeading
import com.mreader.android.ui.components.WebSeriesPosterCard
import com.mreader.android.ui.components.MobilePaginationBar
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

private const val SEARCH_PAGE_SIZE = 20

private fun searchDisplayKey(
    query: String,
    genreIds: List<Int>,
    tagIds: List<Int>,
    status: String?,
    minRating: Double?,
    sort: String,
    offset: Int,
): String = listOf(
    query.trim().lowercase(),
    genreIds.sorted().joinToString(","),
    tagIds.sorted().joinToString(","),
    status.orEmpty(),
    minRating?.toString() ?: "any",
    sort,
    offset.coerceAtLeast(0).toString(),
).joinToString("|")

@Composable
fun SearchScreen(
    repository: MReaderRepository,
    refreshEpoch: Long,
    contentPadding: PaddingValues,
    onSeries: (String) -> Unit,
    onAccount: () -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var selectedGenres by rememberSaveable { mutableStateOf(emptyList<Int>()) }
    var selectedTags by rememberSaveable { mutableStateOf(emptyList<Int>()) }
    var status by rememberSaveable { mutableStateOf("") }
    var minRating by rememberSaveable { mutableStateOf<Double?>(null) }
    var sort by rememberSaveable { mutableStateOf("relevance") }
    var searchOffset by rememberSaveable { mutableIntStateOf(0) }
    var genres by remember { mutableStateOf(repository.peekGenres().orEmpty()) }
    var tags by remember { mutableStateOf(repository.peekTags().orEmpty()) }
    val initialEffectiveSort = if (query.isBlank() && sort == "relevance") "updated" else sort
    val initialSearch = remember {
        repository.peekAdvancedSearch(
            query, selectedGenres, selectedTags, status.takeIf { it.isNotBlank() },
            minRating, initialEffectiveSort, searchOffset, SEARCH_PAGE_SIZE,
        )
    }
    var results by remember { mutableStateOf(initialSearch.orEmpty()) }
    var displayedSearchKey by remember {
        mutableStateOf(
            initialSearch?.let {
                searchDisplayKey(
                    query, selectedGenres, selectedTags, status.takeIf { it.isNotBlank() },
                    minRating, initialEffectiveSort, searchOffset,
                )
            }
        )
    }
    var metrics by remember { mutableStateOf<Map<String, SeriesSocialMetrics>>(emptyMap()) }
    var loading by remember { mutableStateOf(false) }
    var taxonomyLoading by remember { mutableStateOf(genres.isEmpty() && tags.isEmpty()) }
    var hasSearched by rememberSaveable { mutableStateOf(initialSearch != null) }
    var hasMore by remember { mutableStateOf(initialSearch?.size == SEARCH_PAGE_SIZE) }
    var lastRequestedOffset by rememberSaveable { mutableIntStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    var filtersExpanded by rememberSaveable { mutableStateOf(true) }
    var sortMenu by remember { mutableStateOf(false) }
    var requestGeneration by remember { mutableIntStateOf(0) }
    var searchJob by remember { mutableStateOf<Job?>(null) }
    val scope = rememberCoroutineScope()
    val gridState = rememberLazyGridState()

    LaunchedEffect(refreshEpoch) {
        if (genres.isEmpty()) repository.cachedGenres()?.let { genres = it }
        if (tags.isEmpty()) repository.cachedTags()?.let { tags = it }
        taxonomyLoading = genres.isEmpty() && tags.isEmpty()
        try {
            coroutineScope {
                val genresDeferred = async { bestEffort(genres) { repository.genres() } }
                val tagsDeferred = async { bestEffort(tags) { repository.tags() } }
                genres = genresDeferred.await()
                tags = tagsDeferred.await()
            }
        } finally {
            taxonomyLoading = false
        }
    }

    fun execute(offset: Int = 0) {
        val generation = requestGeneration + 1
        requestGeneration = generation
        searchJob?.cancel()

        val requestedOffset = offset.coerceAtLeast(0)
        lastRequestedOffset = requestedOffset
        val requestedQuery = query
        val requestedGenres = selectedGenres
        val requestedTags = selectedTags
        val requestedStatus = status
        val requestedRating = minRating
        val requestedSort = sort

        loading = true
        error = null
        scope.launch { gridState.scrollToItem(0) }
        searchJob = scope.launch {
            try {
                val effectiveSort = if (requestedQuery.isBlank() && requestedSort == "relevance") "updated" else requestedSort
                val requestKey = searchDisplayKey(
                    requestedQuery,
                    requestedGenres,
                    requestedTags,
                    requestedStatus.takeIf { it.isNotBlank() },
                    requestedRating,
                    effectiveSort,
                    requestedOffset,
                )
                val cached = repository.cachedAdvancedSearch(
                    search = requestedQuery,
                    genreIds = requestedGenres,
                    tagIds = requestedTags,
                    status = requestedStatus.takeIf { it.isNotBlank() },
                    minRating = requestedRating,
                    sort = effectiveSort,
                    offset = requestedOffset,
                    limit = SEARCH_PAGE_SIZE,
                )
                if (generation == requestGeneration && cached != null) {
                    searchOffset = requestedOffset
                    results = cached
                    displayedSearchKey = requestKey
                    metrics = emptyMap()
                    hasMore = cached.size == SEARCH_PAGE_SIZE
                    hasSearched = true
                    loading = false
                } else if (generation == requestGeneration && displayedSearchKey != requestKey) {
                    // Never label a previous query/page as the newly requested one.
                    // The matching cache, when present, still renders immediately.
                    results = emptyList()
                    metrics = emptyMap()
                    hasMore = false
                }

                val page = repository.advancedSearch(
                    search = requestedQuery,
                    genreIds = requestedGenres,
                    tagIds = requestedTags,
                    status = requestedStatus.takeIf { it.isNotBlank() },
                    minRating = requestedRating,
                    sort = effectiveSort,
                    offset = requestedOffset,
                    limit = SEARCH_PAGE_SIZE,
                )
                if (generation != requestGeneration) return@launch
                searchOffset = requestedOffset
                results = page
                displayedSearchKey = requestKey
                metrics = emptyMap()
                hasMore = page.size == SEARCH_PAGE_SIZE
                hasSearched = true
                // Do not make navigation wait for optional social enrichment. Cards
                // become usable as soon as the Catalog response arrives.
                loading = false

                val loadedMetrics = bestEffort(emptyMap()) { repository.socialMetricsBatch(page.map { it.id }) }
                if (generation != requestGeneration) return@launch
                metrics = loadedMetrics
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Throwable) {
                if (generation == requestGeneration) error = failure.message ?: "Search failed."
            } finally {
                if (generation == requestGeneration) loading = false
            }
        }
    }

    LaunchedEffect(refreshEpoch) {
        if (hasSearched && !loading) execute(searchOffset)
    }

    DisposableEffect(Unit) {
        onDispose { searchJob?.cancel() }
    }

    val activeFilters = selectedGenres.size + selectedTags.size + (if (status.isBlank()) 0 else 1) + (if (minRating == null) 0 else 1)

    val posterMinWidth = adaptivePosterMinWidth()
    ResponsiveFrame(
        modifier = Modifier.background(Ink950),
        maxContentWidth = 1180.dp,
    ) { edgePadding ->
        LazyVerticalGrid(
        columns = GridCells.Adaptive(posterMinWidth),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            start = edgePadding,
            top = contentPadding.calculateTopPadding() + 10.dp,
            end = edgePadding,
            bottom = contentPadding.calculateBottomPadding() + 30.dp,
        ),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }, key = "search-brand") {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                MReaderBrand(Modifier.weight(1f))
                IconButton(onClick = onAccount) { Icon(Icons.Default.Person, "Account", tint = Ink200) }
            }
        }

        item(span = { GridItemSpan(maxLineSpan) }, key = "search-hero") {
            Box(
                Modifier.fillMaxWidth()
                    .border(1.dp, Ink800, RoundedCornerShape(24.dp))
                    .background(Brush.linearGradient(listOf(Ink900, Ink900, Brand950.copy(alpha = .55f))), RoundedCornerShape(24.dp))
                    .padding(17.dp),
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Surface(color = Brand600.copy(alpha = .16f), shape = RoundedCornerShape(12.dp)) {
                            Icon(Icons.Default.Tune, null, tint = Brand400, modifier = Modifier.padding(9.dp).size(20.dp))
                        }
                        Column {
                            Text("Advanced Search", style = MaterialTheme.typography.headlineSmall, color = Ink50)
                            Text("Title, genres, tags, status, rating and popularity.", style = MaterialTheme.typography.bodySmall, color = Ink400)
                        }
                    }
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it.take(120) },
                        modifier = Modifier.fillMaxWidth(),
                        placeholder = { Text("Search by title…") },
                        leadingIcon = { Icon(Icons.Default.Search, null) },
                        trailingIcon = if (query.isNotBlank()) ({ IconButton(onClick = { query = "" }) { Icon(Icons.Default.Close, "Clear") } }) else null,
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                        keyboardActions = KeyboardActions(onSearch = { execute() }),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = Brand500,
                            unfocusedBorderColor = Ink700,
                            focusedContainerColor = Ink950.copy(alpha = .78f),
                            unfocusedContainerColor = Ink950.copy(alpha = .78f),
                        ),
                    )
                    BoxWithConstraints(Modifier.fillMaxWidth()) {
                        val compactActions = maxWidth < 380.dp
                        if (compactActions) {
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(
                                    onClick = { execute() }, enabled = !loading, modifier = Modifier.fillMaxWidth(),
                                    colors = ButtonDefaults.buttonColors(containerColor = Brand600), shape = RoundedCornerShape(12.dp),
                                ) { Icon(Icons.Default.Search, null, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text(if (loading) "Searching…" else "Search catalog") }
                                OutlinedButton(
                                    onClick = { filtersExpanded = !filtersExpanded }, modifier = Modifier.fillMaxWidth(),
                                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink300), shape = RoundedCornerShape(12.dp),
                                ) { Icon(if (filtersExpanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore, null, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(4.dp)); Text("Filters${if (activeFilters > 0) " · $activeFilters" else ""}") }
                            }
                        } else {
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                                Button(
                                    onClick = { execute() }, enabled = !loading,
                                    colors = ButtonDefaults.buttonColors(containerColor = Brand600), shape = RoundedCornerShape(12.dp),
                                ) { Icon(Icons.Default.Search, null, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text(if (loading) "Searching…" else "Search catalog") }
                                OutlinedButton(
                                    onClick = { filtersExpanded = !filtersExpanded },
                                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink300), shape = RoundedCornerShape(12.dp),
                                ) { Icon(if (filtersExpanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore, null, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(4.dp)); Text("Filters${if (activeFilters > 0) " · $activeFilters" else ""}") }
                            }
                        }
                    }
                }
            }
        }

        if (filtersExpanded) {
            item(span = { GridItemSpan(maxLineSpan) }, key = "search-filters") {
                Surface(color = Ink900.copy(alpha = .76f), shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                    Column(Modifier.padding(13.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("Refine results", style = MaterialTheme.typography.titleMedium, color = Ink50, modifier = Modifier.weight(1f))
                            if (activeFilters > 0) TextButton(onClick = { selectedGenres = emptyList(); selectedTags = emptyList(); status = ""; minRating = null }) { Text("Clear", color = Brand300) }
                        }
                        if (taxonomyLoading) LinearProgressIndicator(Modifier.fillMaxWidth(), color = Brand400, trackColor = Ink800)
                        if (genres.isNotEmpty()) {
                            Text("Genres", style = MaterialTheme.typography.labelMedium, color = Ink300, fontWeight = FontWeight.SemiBold)
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(7.dp), contentPadding = PaddingValues(end = 6.dp)) {
                                items(genres, key = { it.id }) { genre ->
                                    FilterChip(
                                        selected = genre.id in selectedGenres,
                                        onClick = { selectedGenres = if (genre.id in selectedGenres) selectedGenres - genre.id else selectedGenres + genre.id },
                                        label = { Text(genre.name) },
                                        colors = webFilterColors(),
                                    )
                                }
                            }
                        }
                        if (tags.isNotEmpty()) {
                            Text("Tags", style = MaterialTheme.typography.labelMedium, color = Ink300, fontWeight = FontWeight.SemiBold)
                            LazyRow(horizontalArrangement = Arrangement.spacedBy(7.dp), contentPadding = PaddingValues(end = 6.dp)) {
                                items(tags, key = { it.id }) { tag ->
                                    FilterChip(
                                        selected = tag.id in selectedTags,
                                        onClick = { selectedTags = if (tag.id in selectedTags) selectedTags - tag.id else selectedTags + tag.id },
                                        label = { Text(tag.name) },
                                        colors = webFilterColors(),
                                    )
                                }
                            }
                        }
                        Text("Status", style = MaterialTheme.typography.labelMedium, color = Ink300, fontWeight = FontWeight.SemiBold)
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                            items(listOf("" to "Any", "ongoing" to "Ongoing", "completed" to "Completed", "hiatus" to "Hiatus")) { option ->
                                FilterChip(selected = status == option.first, onClick = { status = option.first }, label = { Text(option.second) }, colors = webFilterColors())
                            }
                        }
                        Text("Rating", style = MaterialTheme.typography.labelMedium, color = Ink300, fontWeight = FontWeight.SemiBold)
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                            items(listOf<Double?>(null, 4.5, 4.0, 3.5, 3.0)) { value ->
                                FilterChip(
                                    selected = minRating == value,
                                    onClick = { minRating = value },
                                    label = { Text(value?.let { "$it+ ★" } ?: "Any rating") },
                                    colors = webFilterColors(),
                                )
                            }
                        }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("Sort", color = Ink300, style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f))
                            Box {
                                OutlinedButton(onClick = { sortMenu = true }, colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink300)) {
                                    Icon(Icons.Default.Sort, null, modifier = Modifier.size(16.dp)); Spacer(Modifier.width(5.dp)); Text(searchSortLabel(sort))
                                }
                                DropdownMenu(expanded = sortMenu, onDismissRequest = { sortMenu = false }, containerColor = Ink900) {
                                    searchSortOptions().forEach { option -> DropdownMenuItem(text = { Text(option.second) }, onClick = { sort = option.first; sortMenu = false }) }
                                }
                            }
                        }
                    }
                }
            }
        }

        error?.let { message ->
            item(span = { GridItemSpan(maxLineSpan) }, key = "search-error") {
                Surface(color = Brand950.copy(alpha = .48f), shape = RoundedCornerShape(13.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Brand700)) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.ErrorOutline, null, tint = Brand300); Spacer(Modifier.width(8.dp)); Text(message, color = Brand100, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                        TextButton(onClick = { execute(lastRequestedOffset) }) { Text("Retry") }
                    }
                }
            }
        }

        item(span = { GridItemSpan(maxLineSpan) }, key = "search-results-heading") {
            when {
                !hasSearched -> SectionHeading("Catalog", "Build a search", "Choose any combination of filters, then search the same Catalog index used by the web application.")
                results.isEmpty() && !loading -> SectionHeading("Search results", "No matching series", "Try removing one of the filters or search with a broader title.")
                else -> SectionHeading("Search results", "${results.size}${if (hasMore) "+" else ""} series", "Results are filtered server-side; rating/bookmark metrics are display-only.")
            }
        }

        if (loading && results.isEmpty()) {
            items(6, span = { GridItemSpan(1) }, key = { "search-skeleton-$it" }) {
                Box(Modifier.fillMaxWidth().aspectRatio(2f / 3f).background(Ink800, RoundedCornerShape(13.dp)))
            }
        } else {
            gridItems(results, key = { it.id }) { series ->
                WebSeriesPosterCard(repository, series, { onSeries(series.slug) }, Modifier.fillMaxWidth(), metrics = metrics[series.id])
            }
        }

        if ((results.isNotEmpty() || searchOffset > 0) && !loading) {
            item(span = { GridItemSpan(maxLineSpan) }, key = "search-pagination") {
                MobilePaginationBar(
                    pageIndex = searchOffset / SEARCH_PAGE_SIZE,
                    canGoPrevious = searchOffset > 0,
                    canGoNext = hasMore,
                    onPrevious = { execute((searchOffset - SEARCH_PAGE_SIZE).coerceAtLeast(0)) },
                    onNext = { execute(searchOffset + SEARCH_PAGE_SIZE) },
                    busy = loading,
                )
            }
        }
    }
    }
}

@Composable
private fun webFilterColors() = FilterChipDefaults.filterChipColors(
    containerColor = Ink800,
    labelColor = Ink400,
    selectedContainerColor = Brand600,
    selectedLabelColor = androidx.compose.ui.graphics.Color.White,
)

private fun searchSortOptions() = listOf(
    "relevance" to "Best match",
    "updated" to "Recently updated",
    "newest" to "Newest series",
    "rating" to "Highest rated",
    "popular" to "Most bookmarked",
    "title" to "Title A–Z",
)

private fun searchSortLabel(value: String): String = searchSortOptions().firstOrNull { it.first == value }?.second ?: "Best match"
