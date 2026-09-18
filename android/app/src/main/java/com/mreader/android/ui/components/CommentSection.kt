package com.mreader.android.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Message
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Reply
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mreader.android.core.model.CommentItem
import com.mreader.android.core.model.User
import com.mreader.android.core.repository.MReaderRepository
import com.mreader.android.ui.theme.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.temporal.ChronoUnit

private const val COMMENT_LIMIT = 50

/** Native counterpart of the web CommentSection. It intentionally uses HTTP only
 * while visible; no background polling/subscriber is kept alive on Android. */
@Composable
fun CommentSection(
    repository: MReaderRepository,
    currentUser: User?,
    seriesId: String,
    chapterId: String? = null,
    title: String = "Discussion",
    onLogin: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var comments by remember(seriesId, chapterId) { mutableStateOf<List<CommentItem>>(emptyList()) }
    var total by remember(seriesId, chapterId) { mutableIntStateOf(0) }
    var content by remember(seriesId, chapterId) { mutableStateOf("") }
    var replyingTo by remember(seriesId, chapterId) { mutableStateOf<CommentItem?>(null) }
    var loading by remember(seriesId, chapterId) { mutableStateOf(true) }
    var submitting by remember(seriesId, chapterId) { mutableStateOf(false) }
    var deletingId by remember(seriesId, chapterId) { mutableStateOf<String?>(null) }
    var error by remember(seriesId, chapterId) { mutableStateOf<String?>(null) }
    var reloadKey by remember(seriesId, chapterId) { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    fun removeTree(rootId: String) {
        val removed = mutableSetOf(rootId)
        var changed: Boolean
        do {
            changed = false
            comments.forEach { row ->
                if (row.parentId != null && row.parentId in removed && removed.add(row.id)) changed = true
            }
        } while (changed)
        comments = comments.filterNot { it.id in removed }
        total = (total - removed.size).coerceAtLeast(0)
    }

    LaunchedEffect(seriesId, chapterId, reloadKey) {
        loading = true
        error = null
        try {
            val page = repository.comments(seriesId, chapterId, limit = COMMENT_LIMIT)
            comments = page.items
            total = page.total
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Throwable) {
            error = failure.message ?: "Failed to load comments."
        } finally {
            loading = false
        }
    }

    val byId = remember(comments) { comments.associateBy { it.id } }
    val ordered = remember(comments) {
        val children = comments.groupBy { it.parentId }
        val seen = mutableSetOf<String>()
        buildList {
            fun append(parentId: String?, depth: Int) {
                children[parentId].orEmpty().forEach { item ->
                    if (!seen.add(item.id)) return@forEach
                    add(item to depth)
                    append(item.id, depth + 1)
                }
            }
            append(null, 0)
            // Preserve orphaned comments if an older page omitted a parent.
            comments.filterNot { it.id in seen }.forEach { add(it to 0) }
        }
    }

    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Surface(color = Brand600.copy(alpha = .14f), shape = CircleShape) {
                Icon(Icons.Default.Message, null, tint = Brand400, modifier = Modifier.padding(8.dp).size(18.dp))
            }
            Spacer(Modifier.width(9.dp))
            Column(Modifier.weight(1f)) {
                Eyebrow(if (chapterId == null) "Community" else "Chapter discussion")
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(title, style = MaterialTheme.typography.titleLarge, color = Ink50)
                    Text("($total)", style = MaterialTheme.typography.bodySmall, color = Ink500)
                }
            }
            IconButton(onClick = { reloadKey++ }, enabled = !loading) {
                Icon(Icons.Default.Refresh, "Refresh discussion", tint = Ink400)
            }
        }

        if (currentUser == null) {
            Surface(
                color = Ink900,
                shape = RoundedCornerShape(14.dp),
                border = BorderStroke(1.dp, Ink800),
            ) {
                Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Sign in to join the discussion.", color = Ink400, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    TextButton(onClick = onLogin) { Text("Sign in", color = Brand400) }
                }
            }
        } else {
            replyingTo?.let { target ->
                Surface(color = Brand950.copy(alpha = .32f), shape = RoundedCornerShape(11.dp), border = BorderStroke(1.dp, Brand700.copy(alpha = .45f))) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("Replying to ${target.authorUsername}", color = Ink300, style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        TextButton(onClick = { replyingTo = null }) { Text("Cancel") }
                    }
                }
            }
            OutlinedTextField(
                value = content,
                onValueChange = { content = it.take(2_000) },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                maxLines = 6,
                placeholder = { Text(if (replyingTo == null) "Share your thoughts…" else "Reply to ${replyingTo?.authorUsername}…") },
                supportingText = { Text("${content.length}/2000") },
                shape = RoundedCornerShape(14.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Brand500,
                    unfocusedBorderColor = Ink700,
                    focusedContainerColor = Ink900,
                    unfocusedContainerColor = Ink900,
                ),
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                Button(
                    enabled = content.isNotBlank() && !submitting,
                    onClick = {
                        submitting = true
                        error = null
                        val draft = content
                        val parent = replyingTo?.id
                        scope.launch {
                            try {
                                val created = repository.createComment(seriesId, chapterId, parent, draft)
                                comments = comments + created
                                total += 1
                                content = ""
                                replyingTo = null
                            } catch (cancelled: CancellationException) {
                                throw cancelled
                            } catch (failure: Throwable) {
                                error = failure.message ?: "Failed to post comment."
                            } finally {
                                submitting = false
                            }
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Brand600),
                ) {
                    if (submitting) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Color.White)
                    else Icon(Icons.Default.Send, null, modifier = Modifier.size(17.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Post")
                }
            }
        }

        error?.let { message ->
            Surface(color = Color(0xFF351D1B), shape = RoundedCornerShape(12.dp), border = BorderStroke(1.dp, Brand700.copy(alpha = .65f))) {
                Row(Modifier.fillMaxWidth().padding(11.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(message, color = Brand100, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                    TextButton(onClick = { reloadKey++ }) { Text("Retry") }
                }
            }
        }

        if (loading) {
            repeat(2) {
                Box(Modifier.fillMaxWidth().height(86.dp).background(Ink900, RoundedCornerShape(14.dp)))
            }
        } else if (comments.isEmpty()) {
            Surface(color = Ink900.copy(alpha = .45f), shape = RoundedCornerShape(15.dp), border = BorderStroke(1.dp, Ink800)) {
                Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Icon(Icons.Default.Message, null, tint = Ink600)
                    Text("No comments yet", color = Ink300, style = MaterialTheme.typography.titleSmall)
                    Text("Be the first reader to start the conversation.", color = Ink500, style = MaterialTheme.typography.bodySmall)
                }
            }
        } else {
            ordered.forEach { (comment, depth) ->
                val parent = comment.parentId?.let(byId::get)
                CommentCard(
                    comment = comment,
                    parentAuthor = parent?.authorUsername,
                    depth = depth,
                    own = currentUser?.id == comment.userId,
                    busy = deletingId == comment.id,
                    canReply = currentUser != null,
                    onReply = { replyingTo = comment; content = "" },
                    onDelete = {
                        deletingId = comment.id
                        scope.launch {
                            try {
                                repository.deleteComment(comment.id)
                                removeTree(comment.id)
                            } catch (cancelled: CancellationException) {
                                throw cancelled
                            } catch (failure: Throwable) {
                                error = failure.message ?: "Failed to delete comment."
                            } finally {
                                deletingId = null
                            }
                        }
                    },
                )
            }
            if (total > comments.size) {
                Text("Showing ${comments.size} of $total comments. Open the web app for older discussion history.", color = Ink500, style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

@Composable
private fun CommentCard(
    comment: CommentItem,
    parentAuthor: String?,
    depth: Int,
    own: Boolean,
    busy: Boolean,
    canReply: Boolean,
    onReply: () -> Unit,
    onDelete: () -> Unit,
) {
    val indent = (depth.coerceIn(0, 3) * 18).dp
    Row(Modifier.fillMaxWidth().padding(start = indent), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        Surface(color = if (own) Brand600.copy(alpha = .16f) else Ink800, shape = CircleShape) {
            Text(
                comment.authorUsername.take(1).uppercase().ifBlank { "R" },
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp),
                color = if (own) Brand300 else Ink300,
                fontWeight = FontWeight.Bold,
            )
        }
        Surface(
            modifier = Modifier.weight(1f),
            color = if (own) Brand950.copy(alpha = .22f) else Ink900.copy(alpha = .72f),
            shape = RoundedCornerShape(14.dp),
            border = BorderStroke(1.dp, if (own) Brand700.copy(alpha = .36f) else Ink800),
        ) {
            Column(Modifier.padding(11.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(comment.authorUsername, color = Ink100, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(commentRelativeTime(comment.createdAt), color = Ink500, style = MaterialTheme.typography.labelSmall)
                }
                if (!parentAuthor.isNullOrBlank()) Text("Reply to @$parentAuthor", color = Brand300, style = MaterialTheme.typography.labelSmall)
                Text(comment.content, color = Ink300, style = MaterialTheme.typography.bodyMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (canReply) {
                        TextButton(onClick = onReply, contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp)) {
                            Icon(Icons.Default.Reply, null, modifier = Modifier.size(15.dp)); Spacer(Modifier.width(4.dp)); Text("Reply", style = MaterialTheme.typography.labelMedium)
                        }
                    }
                    if (own) {
                        TextButton(onClick = onDelete, enabled = !busy, contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp)) {
                            if (busy) CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                            else Icon(Icons.Default.DeleteOutline, null, modifier = Modifier.size(15.dp))
                            Spacer(Modifier.width(4.dp)); Text("Delete", style = MaterialTheme.typography.labelMedium)
                        }
                    }
                }
            }
        }
    }
}

private fun commentRelativeTime(value: String): String {
    val then = runCatching { Instant.parse(value) }.getOrNull() ?: return ""
    val minutes = ChronoUnit.MINUTES.between(then, Instant.now()).coerceAtLeast(0)
    return when {
        minutes < 1 -> "now"
        minutes < 60 -> "${minutes}m"
        minutes < 1_440 -> "${minutes / 60}h"
        minutes < 43_200 -> "${minutes / 1_440}d"
        else -> "${minutes / 43_200}mo"
    }
}
