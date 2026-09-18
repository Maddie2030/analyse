package com.mreader.android.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mreader.android.core.model.NotificationItem
import com.mreader.android.ui.AppViewModel
import com.mreader.android.ui.components.ResponsiveFrame
import com.mreader.android.ui.components.SectionHeading
import com.mreader.android.ui.components.formatChapterNumber
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.temporal.ChronoUnit

@Composable
fun NotificationsScreen(
    appViewModel: AppViewModel,
    refreshEpoch: Long,
    contentPadding: PaddingValues,
    onReadChapter: (String, String) -> Unit,
    onLogin: () -> Unit,
    onAccount: () -> Unit,
) {
    val repository = appViewModel.repository
    val currentUser by appViewModel.user.collectAsStateWithLifecycle()
    val currentAccountId by rememberUpdatedState(currentUser?.id)
    var unreadOnly by rememberSaveable { mutableStateOf(false) }
    var rows by remember(currentUser?.id, unreadOnly) { mutableStateOf<List<NotificationItem>>(emptyList()) }
    var known by remember(currentUser?.id, unreadOnly) { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }
    var marking by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    LaunchedEffect(unreadOnly) { listState.scrollToItem(0) }

    LaunchedEffect(currentUser?.id, unreadOnly, refreshEpoch, reloadKey) {
        if (currentUser == null) { rows = emptyList(); known = false; loading = false; return@LaunchedEffect }
        loading = true; error = null
        try {
            rows = repository.notifications(unreadOnly = unreadOnly, limit = 50)
            known = true
            appViewModel.refreshNotificationCount()
        }
        catch (cancelled: CancellationException) { throw cancelled }
        catch (failure: Throwable) { error = failure.message ?: "Notifications are temporarily unavailable." }
        finally { loading = false }
    }

    if (currentUser == null) {
        Box(Modifier.fillMaxSize().background(Ink950).padding(contentPadding).padding(24.dp), contentAlignment = Alignment.Center) {
            Surface(color = Ink900, shape = RoundedCornerShape(22.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(Icons.Default.Notifications, null, tint = Brand400, modifier = Modifier.size(40.dp))
                    Text("Alerts follow your account", style = MaterialTheme.typography.titleLarge, color = Ink50)
                    Text("Sign in to see chapter-release notifications and updates from followed series.", color = Ink400, style = MaterialTheme.typography.bodyMedium)
                    Button(onClick = onLogin, colors = ButtonDefaults.buttonColors(containerColor = Brand600)) { Text("Sign in") }
                }
            }
        }
        return
    }

    ResponsiveFrame(modifier = Modifier.background(Ink950), maxContentWidth = 760.dp) { edgePadding ->
        LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = edgePadding, top = contentPadding.calculateTopPadding() + 14.dp, end = edgePadding, bottom = contentPadding.calculateBottomPadding() + 30.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "alerts-heading") {
            SectionHeading(
                "Personal",
                "Notifications",
                "Chapter alerts from the same notification feed as the web application.",
                action = { IconButton(onClick = onAccount) { Icon(Icons.Default.Person, "Account", tint = Ink300) } },
            )
        }
        item(key = "alerts-controls") {
            Surface(color = Ink900.copy(alpha = .72f), shape = RoundedCornerShape(15.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                BoxWithConstraints(Modifier.fillMaxWidth().padding(10.dp)) {
                    val compact = maxWidth < 360.dp
                    val markAll: () -> Unit = {
                        val accountId = currentUser?.id
                        marking = true
                        scope.launch {
                            try {
                                repository.markAllNotificationsRead()
                                if (currentAccountId != accountId) return@launch
                                rows = if (unreadOnly) emptyList() else rows.map { it.copy(isRead = true) }
                                appViewModel.setUnreadNotificationCount(0)
                            } catch (cancelled: CancellationException) {
                                throw cancelled
                            } catch (failure: Throwable) {
                                error = failure.message ?: "Could not mark alerts as read."
                            } finally {
                                marking = false
                            }
                        }
                    }
                    if (compact) {
                        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            NotificationUnreadFilter(unreadOnly) { unreadOnly = !unreadOnly }
                            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
                                NotificationMarkAllButton(!marking && rows.any { !it.isRead }, markAll)
                            }
                        }
                    } else {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            NotificationUnreadFilter(unreadOnly) { unreadOnly = !unreadOnly }
                            Spacer(Modifier.weight(1f))
                            NotificationMarkAllButton(!marking && rows.any { !it.isRead }, markAll)
                        }
                    }
                }
            }
        }

        error?.let { message -> item(key = "alerts-error") {
            Surface(color = Color(0xFF3A2A11), shape = RoundedCornerShape(12.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Color(0xFF815C1C))) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(message, color = Gold400, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f)); TextButton(onClick = { reloadKey++ }) { Text("Retry") }
                }
            }
        } }

        NotificationFeedItems(
            loading = loading,
            rows = rows,
            known = known,
            unreadOnly = unreadOnly,
            onRowsChanged = { rows = it },
            onMarkRead = appViewModel::markNotificationRead,
            onReadChapter = onReadChapter,
        )
    }
    }
}


private fun androidx.compose.foundation.lazy.LazyListScope.NotificationFeedItems(
    loading: Boolean,
    rows: List<NotificationItem>,
    known: Boolean,
    unreadOnly: Boolean,
    onRowsChanged: (List<NotificationItem>) -> Unit,
    onMarkRead: (String) -> Unit,
    onReadChapter: (String, String) -> Unit,
) {
    if (loading) {
        items(5, key = { "notification-skeleton-$it" }) { Box(Modifier.fillMaxWidth().height(82.dp).background(Ink900, RoundedCornerShape(14.dp))) }
    } else if (rows.isEmpty() && known) {
        item(key = "alerts-empty") {
            Surface(color = Ink900.copy(alpha = .55f), shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.fillMaxWidth().padding(30.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Default.NotificationsNone, null, tint = Ink500, modifier = Modifier.size(34.dp))
                    Text(if (unreadOnly) "No unread notifications" else "No notifications yet", color = Ink200, style = MaterialTheme.typography.titleMedium)
                    Text("Follow a series to receive new-chapter alerts.", color = Ink500, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    } else if (rows.isEmpty()) {
        item(key = "alerts-unavailable") {
            Surface(color = Ink900.copy(alpha = .55f), shape = RoundedCornerShape(18.dp), border = androidx.compose.foundation.BorderStroke(1.dp, Ink800)) {
                Column(Modifier.fillMaxWidth().padding(30.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Default.CloudOff, null, tint = Ink500, modifier = Modifier.size(34.dp))
                    Text("Notifications are unavailable", color = Ink200, style = MaterialTheme.typography.titleMedium)
                    Text("Retry when the notification service is reachable. No empty inbox is being inferred.", color = Ink500, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    } else {
        items(rows, key = { it.id }) { item ->
            NotificationCard(
                item = item,
                onClick = {
                    if (!item.isRead) {
                        val updatedRows = if (unreadOnly) rows.filterNot { it.id == item.id }
                        else rows.map { if (it.id == item.id) it.copy(isRead = true) else it }
                        onRowsChanged(updatedRows)
                        onMarkRead(item.id)
                    }
                    val seriesSlug = item.seriesSlug
                    val chapterSlug = item.chapterSlug
                    if (!seriesSlug.isNullOrBlank() && !chapterSlug.isNullOrBlank()) onReadChapter(seriesSlug, chapterSlug)
                },
            )
        }
    }
}

@Composable
private fun NotificationCard(item: NotificationItem, onClick: () -> Unit) {
    val unreadAccent = if (item.isRead) Ink800 else Brand600.copy(alpha = .56f)
    Surface(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        color = if (item.isRead) Ink900.copy(alpha = .68f) else Brand950.copy(alpha = .34f),
        shape = RoundedCornerShape(14.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, unreadAccent),
    ) {
        Row(Modifier.padding(13.dp), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(11.dp)) {
            Surface(color = if (item.isRead) Ink800 else Brand600.copy(alpha = .16f), shape = CircleShape) {
                Icon(Icons.Default.Notifications, null, tint = if (item.isRead) Ink400 else Brand400, modifier = Modifier.padding(9.dp).size(18.dp))
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(item.seriesTitle ?: "Mreader", color = Ink50, style = MaterialTheme.typography.titleSmall, fontWeight = if (item.isRead) FontWeight.Medium else FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    if (!item.isRead) Box(Modifier.size(7.dp).background(Brand400, CircleShape))
                }
                Text(item.message, color = Ink300, style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (item.chapterNumber != null) Text("Chapter ${formatChapterNumber(item.chapterNumber)}", color = Brand300, style = MaterialTheme.typography.labelSmall)
                    Text(relativeTime(item.createdAt), color = Ink500, style = MaterialTheme.typography.labelSmall)
                }
            }
            if (!item.seriesSlug.isNullOrBlank() && !item.chapterSlug.isNullOrBlank()) Icon(Icons.Default.ChevronRight, null, tint = Ink600)
        }
    }
}

@Composable
private fun NotificationUnreadFilter(selected: Boolean, onToggle: () -> Unit) {
    FilterChip(
        selected = selected,
        onClick = onToggle,
        label = { Text("Unread only") },
        leadingIcon = { Icon(Icons.Default.MarkEmailUnread, null, modifier = Modifier.size(16.dp)) },
        colors = FilterChipDefaults.filterChipColors(
            containerColor = Ink800,
            labelColor = Ink400,
            selectedContainerColor = Brand600,
            selectedLabelColor = Color.White,
        ),
    )
}

@Composable
private fun NotificationMarkAllButton(enabled: Boolean, onClick: () -> Unit) {
    TextButton(enabled = enabled, onClick = onClick) {
        Icon(Icons.Default.DoneAll, null, modifier = Modifier.size(17.dp))
        Spacer(Modifier.width(5.dp))
        Text("Mark all read")
    }
}


private fun relativeTime(value: String): String {
    val then = runCatching { Instant.parse(value) }.getOrNull() ?: return ""
    val now = Instant.now()
    val minutes = ChronoUnit.MINUTES.between(then, now).coerceAtLeast(0)
    return when {
        minutes < 1 -> "just now"
        minutes < 60 -> "${minutes}m ago"
        minutes < 1440 -> "${minutes / 60}h ago"
        minutes < 43_200 -> "${minutes / 1440}d ago"
        else -> "${minutes / 43_200}mo ago"
    }
}
