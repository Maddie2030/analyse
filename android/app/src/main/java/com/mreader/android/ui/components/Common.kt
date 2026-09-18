package com.mreader.android.ui.components

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Book
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.People
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mreader.android.core.model.Series
import com.mreader.android.core.model.SeriesSocialMetrics
import com.mreader.android.core.repository.MReaderRepository
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import java.time.Instant

@Composable
fun NetworkImage(
    repository: MReaderRepository,
    url: String?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop,
) {
    if (url.isNullOrBlank()) {
        Box(modifier.background(Brush.linearGradient(listOf(Ink700, Ink800))), contentAlignment = Alignment.Center) {
            Icon(Icons.Default.Book, contentDescription = null, tint = Ink500, modifier = Modifier.size(30.dp))
        }
        return
    }
    val state by produceState<Any?>(initialValue = repository.coverStore.peek(url), key1 = url) {
        if (value == null) {
            value = try {
                repository.coverStore.load(url, repository.api)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Throwable) {
                failure
            }
        }
    }
    when (val value = state) {
        null -> Box(
            modifier.background(Brush.linearGradient(listOf(Ink800, Ink700, Ink800))),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Book, contentDescription = null, tint = Ink600, modifier = Modifier.size(24.dp))
        }
        is Bitmap -> Image(value.asImageBitmap(), contentDescription, modifier, contentScale = contentScale)
        else -> Box(modifier.background(Ink800), contentAlignment = Alignment.Center) {
            Text("Image unavailable", style = MaterialTheme.typography.labelSmall, color = Ink400)
        }
    }
}

@Composable
fun MReaderBrand(modifier: Modifier = Modifier, compact: Boolean = false) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Icon(Icons.Default.Book, contentDescription = null, tint = Brand400, modifier = Modifier.size(if (compact) 20.dp else 24.dp))
        if (!compact) Text("Mreader", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Ink50)
    }
}

@Composable
fun Eyebrow(text: String, modifier: Modifier = Modifier, color: Color = Brand400) {
    Text(
        text.uppercase(),
        modifier = modifier,
        style = MaterialTheme.typography.labelSmall,
        color = color,
        fontWeight = FontWeight.Bold,
        letterSpacing = MaterialTheme.typography.labelSmall.letterSpacing,
    )
}

@Composable
fun StatusPill(status: String, modifier: Modifier = Modifier) {
    val normalized = status.trim().ifBlank { "ongoing" }.lowercase()
    val color = when (normalized) {
        "ongoing" -> Color(0xFF35A854)
        "completed" -> Color(0xFF3478D4)
        "cancelled" -> Color(0xFFC63A3A)
        else -> Color(0xFFD09A2E)
    }
    Surface(modifier = modifier, color = color.copy(alpha = 0.82f), contentColor = Color.White, shape = CircleShape) {
        Text(
            normalized.replace('_', ' ').replaceFirstChar { it.uppercase() },
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
fun TagChip(label: String, modifier: Modifier = Modifier, accent: Boolean = false) {
    Surface(
        modifier = modifier,
        color = if (accent) Brand600.copy(alpha = 0.16f) else Ink800,
        contentColor = if (accent) Brand300 else Ink300,
        shape = CircleShape,
        border = androidx.compose.foundation.BorderStroke(1.dp, if (accent) Brand600.copy(alpha = 0.32f) else Ink700),
    ) {
        Text(label, Modifier.padding(horizontal = 9.dp, vertical = 5.dp), style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
fun WebSeriesPosterCard(
    repository: MReaderRepository,
    series: Series,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    metrics: SeriesSocialMetrics? = null,
    rank: Int? = null,
    dense: Boolean = false,
) {
    Column(
        modifier = modifier.clickable(onClick = onClick),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .aspectRatio(2f / 3f)
                .clip(RoundedCornerShape(13.dp))
                .background(Ink800),
        ) {
            NetworkImage(
                repository = repository,
                url = series.coverImagePath?.let(repository.api::coverUrl),
                contentDescription = series.title,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(62.dp)
                    .align(Alignment.BottomCenter)
                    .background(Brush.verticalGradient(listOf(Color.Transparent, Ink950.copy(alpha = 0.88f)))),
            )
            StatusPill(series.status, Modifier.align(Alignment.BottomStart).padding(8.dp))
            if (rank != null) {
                Surface(
                    modifier = Modifier.align(Alignment.TopStart).padding(8.dp),
                    color = Ink950.copy(alpha = 0.90f),
                    contentColor = Color.White,
                    shape = CircleShape,
                    border = androidx.compose.foundation.BorderStroke(1.dp, Color.White.copy(alpha = 0.10f)),
                ) { Text("#$rank", Modifier.padding(horizontal = 8.dp, vertical = 5.dp), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold) }
            }
        }
        Text(
            series.title,
            modifier = Modifier.heightIn(min = if (dense) 36.dp else 40.dp),
            style = if (dense) MaterialTheme.typography.bodySmall else MaterialTheme.typography.titleSmall,
            color = Ink50,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            fontWeight = FontWeight.Medium,
        )
        metrics?.let {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Star, null, tint = Gold400, modifier = Modifier.size(13.dp))
                    Text(it.ratingAverage?.let { value -> "%.1f".format(value) } ?: "—", color = Ink400, style = MaterialTheme.typography.labelSmall)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Bookmark, null, tint = Brand400, modifier = Modifier.size(13.dp))
                    Text(it.bookmarkCount.toString(), color = Ink400, style = MaterialTheme.typography.labelSmall)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.People, null, tint = Brand400, modifier = Modifier.size(13.dp))
                    Text(it.subscriptionCount.toString(), color = Ink400, style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}

@Composable
fun SectionHeading(
    eyebrow: String,
    title: String,
    supporting: String? = null,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null,
) {
    BoxWithConstraints(modifier.fillMaxWidth()) {
        val compactAction = action != null && maxWidth < 380.dp
        if (compactAction) {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(eyebrow.uppercase(), style = MaterialTheme.typography.labelSmall, color = Ink500, fontWeight = FontWeight.Bold)
                    Text(title, style = MaterialTheme.typography.headlineSmall, color = Ink50)
                    if (!supporting.isNullOrBlank()) Text(supporting, style = MaterialTheme.typography.bodySmall, color = Ink400)
                }
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) { action?.invoke() }
            }
        } else {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(eyebrow.uppercase(), style = MaterialTheme.typography.labelSmall, color = Ink500, fontWeight = FontWeight.Bold)
                    Text(title, style = MaterialTheme.typography.headlineSmall, color = Ink50)
                    if (!supporting.isNullOrBlank()) Text(supporting, style = MaterialTheme.typography.bodySmall, color = Ink400)
                }
                action?.invoke()
            }
        }
    }
}

@Composable
fun SummaryStat(
    label: String,
    value: Int,
    modifier: Modifier = Modifier,
    accent: Color = Brand400,
    onClick: (() -> Unit)? = null,
) {
    val shape = RoundedCornerShape(13.dp)
    val base = modifier
        .clip(shape)
        .border(1.dp, accent.copy(alpha = 0.22f), shape)
        .background(accent.copy(alpha = 0.08f))
        .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
        .padding(10.dp)
    Column(base.heightIn(min = 58.dp), verticalArrangement = Arrangement.SpaceBetween) {
        Text(label.uppercase(), color = accent, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, maxLines = 1)
        Text(value.toString(), color = Ink50, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    }
}


/**
 * Shared horizontally scrolling shelf for phones/tablets. Consistent spacing and
 * edge padding keep the next card visible without allowing individual screens to
 * invent slightly different carousel geometry.
 */
@Composable
fun StableHorizontalShelf(
    modifier: Modifier = Modifier,
    spacing: androidx.compose.ui.unit.Dp = 10.dp,
    content: LazyListScope.() -> Unit,
) {
    LazyRow(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(spacing),
        contentPadding = PaddingValues(start = 2.dp, end = 14.dp),
        content = content,
    )
}

@Composable
fun adaptiveCarouselPosterWidth(): androidx.compose.ui.unit.Dp {
    val configuration = androidx.compose.ui.platform.LocalConfiguration.current
    return when {
        configuration.screenWidthDp < 350 -> 124.dp
        configuration.screenWidthDp < 600 -> 142.dp
        else -> 156.dp
    }
}

/**
 * Compact page navigation used by the catalog, advanced search and chapter list.
 * Buttons retain a 48dp touch target and collapse their labels on very narrow
 * phones instead of wrapping or pushing the page indicator off screen.
 */
@Composable
fun MobilePaginationBar(
    pageIndex: Int,
    canGoPrevious: Boolean,
    canGoNext: Boolean,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier,
    previousLabel: String = "Previous",
    nextLabel: String = "Next",
    busy: Boolean = false,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = Ink900.copy(alpha = 0.72f),
        shape = RoundedCornerShape(14.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Ink800),
    ) {
        BoxWithConstraints(Modifier.fillMaxWidth().padding(8.dp)) {
            val compact = maxWidth < 340.dp
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onPrevious,
                    enabled = canGoPrevious && !busy,
                    modifier = Modifier.weight(1f).heightIn(min = 48.dp),
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink200),
                ) {
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, null, modifier = Modifier.size(18.dp))
                    if (!compact) { Spacer(Modifier.width(3.dp)); Text(previousLabel, maxLines = 1) }
                }
                Surface(color = Ink800, shape = RoundedCornerShape(10.dp)) {
                    Text(
                        if (busy) "…" else "Page ${pageIndex.coerceAtLeast(0) + 1}",
                        modifier = Modifier.padding(horizontal = if (compact) 9.dp else 12.dp, vertical = 9.dp),
                        color = Ink300,
                        style = MaterialTheme.typography.labelMedium,
                        maxLines = 1,
                    )
                }
                OutlinedButton(
                    onClick = onNext,
                    enabled = canGoNext && !busy,
                    modifier = Modifier.weight(1f).heightIn(min = 48.dp),
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Ink200),
                ) {
                    if (!compact) { Text(nextLabel, maxLines = 1); Spacer(Modifier.width(3.dp)) }
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, modifier = Modifier.size(18.dp))
                }
            }
        }
    }
}

fun formatChapterNumber(value: Double?): String {
    if (value == null) return "—"
    val whole = value.toLong()
    return if (value == whole.toDouble()) whole.toString() else value.toString().trimEnd('0').trimEnd('.')
}

fun relativeTime(value: String?): String {
    val then = value?.let { runCatching { Instant.parse(it) }.getOrNull() } ?: return ""
    val seconds = ((System.currentTimeMillis() - then.toEpochMilli()).coerceAtLeast(0L) / 1000L)
    if (seconds < 60) return "just now"
    val minutes = seconds / 60
    if (minutes < 60) return "${minutes}m ago"
    val hours = minutes / 60
    if (hours < 24) return "${hours}h ago"
    val days = hours / 24
    if (days < 30) return "${days}d ago"
    val months = days / 30
    return if (months < 12) "${months}mo ago" else "${months / 12}y ago"
}

/**
 * Centers mobile/tablet content in a bounded column while still using the full
 * height. It prevents cards/rows from becoming awkwardly stretched on tablets
 * and keeps edge spacing proportional on narrow phones.
 */
@Composable
fun ResponsiveFrame(
    modifier: Modifier = Modifier,
    maxContentWidth: androidx.compose.ui.unit.Dp = 960.dp,
    content: @Composable BoxScope.(edgePadding: androidx.compose.ui.unit.Dp) -> Unit,
) {
    BoxWithConstraints(modifier.fillMaxSize()) {
        val edge = when {
            maxWidth < 360.dp -> 10.dp
            maxWidth < 600.dp -> 14.dp
            maxWidth < 840.dp -> 20.dp
            else -> 28.dp
        }
        val contentWidth = if (maxWidth > maxContentWidth) maxContentWidth else maxWidth
        Box(
            Modifier
                .width(contentWidth)
                .fillMaxHeight()
                .align(Alignment.TopCenter),
        ) {
            content(edge)
        }
    }
}

@Composable
fun adaptivePosterMinWidth(): androidx.compose.ui.unit.Dp {
    val configuration = androidx.compose.ui.platform.LocalConfiguration.current
    return when {
        configuration.screenWidthDp < 350 -> 112.dp
        configuration.screenWidthDp < 600 -> 132.dp
        else -> 148.dp
    }
}
