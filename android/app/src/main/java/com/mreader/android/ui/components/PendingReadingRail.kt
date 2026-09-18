package com.mreader.android.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mreader.android.core.repository.ReadingView

/** A preview of unsynced intent; it never changes Library membership or counts. */
@Composable
fun PendingReadingRail(view: ReadingView, onRead: (String, String) -> Unit) {
    if (view.scope?.accountId == null) return
    val pending = view.visits.asReversed().filter { it.pending }.distinctBy { it.target.seriesId }.take(12)
    if (pending.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Pending reading", style = MaterialTheme.typography.titleMedium)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(pending, key = { it.id }) { visit ->
                OutlinedCard(modifier = Modifier.width(240.dp), onClick = { onRead(visit.target.seriesSlug, visit.target.chapterSlug) }) {
                    Column(Modifier.padding(12.dp)) {
                        Text(visit.target.seriesTitle, maxLines = 2)
                        Text("Continue chapter ${formatChapterNumber(visit.target.chapterNumber)}", style = MaterialTheme.typography.bodySmall)
                        Text(if (visit.pauseCode == null) "Pending sync" else "Sync paused", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}
