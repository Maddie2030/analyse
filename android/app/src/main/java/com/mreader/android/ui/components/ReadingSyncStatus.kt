package com.mreader.android.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import com.mreader.android.core.repository.ReadingView
import com.mreader.android.core.repository.MReaderRepository

@Composable
fun ReadingSyncStatus(repository: MReaderRepository, view: ReadingView, seriesId: String? = null) {
    val pending = if (seriesId == null) view.visits.filter { it.pending }
        else view.visits.filter { it.target.seriesId == seriesId && it.pending }
    val paused = pending.filter { it.pauseCode != null }
    var confirmDiscard by remember { mutableStateOf(false) }
    val message = when {
        view.storageProblem -> "Reading changes are only in memory. Free some storage and retry."
        view.suspendedUnsaved -> "An earlier account has unsaved reading changes. Sign back into that account to save them."
        view.needsSignIn -> "Progress sync is paused. Sign in again to save your reading changes."
        paused.isNotEmpty() -> "Progress sync is paused. Your local position is kept; saved progress has changed."
        pending.isNotEmpty() && view.scope?.accountId != null -> "Reading changes pending sync"
        else -> null
    }
    if (message != null) Column {
        Text(message, style = MaterialTheme.typography.bodySmall)
        Row {
            TextButton(onClick = { repository.reading.retryTransport() }) { Text("Retry sync") }
            if (paused.isNotEmpty()) TextButton(onClick = { confirmDiscard = true }) { Text("Use saved progress") }
        }
    }
    if (confirmDiscard) AlertDialog(
        onDismissRequest = { confirmDiscard = false },
        title = { Text("Use saved progress?") },
        text = { Text("This discards the paused local changes and reloads progress saved on the server.") },
        confirmButton = { TextButton(onClick = {
            paused.map { it.target.seriesId }.distinct().forEach(repository.reading::useServerProgress)
            confirmDiscard = false
        }) { Text("Use saved progress") } },
        dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text("Keep local changes") } },
    )
}
