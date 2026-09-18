package com.mreader.android.core.repository

import android.content.Context
import com.mreader.android.core.network.parseProgress
import java.io.IOException
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject

/** Called only on Dispatchers.IO by ReadingRepository; commit failure is never an ACK. */
class LocalProgressStore(context: Context) {
    private val prefs = context.getSharedPreferences("mreader_reading_journal_v3", Context.MODE_PRIVATE)
    private val legacy = listOf("mreader_local_progress_v2", "mreader_local_recent_v1")
        .map { context.getSharedPreferences(it, Context.MODE_PRIVATE) }

    fun read(scope: ReadingScope): ReadingJournal {
        val raw = prefs.getString(key(scope), null) ?: return ReadingJournal()
        val root = JSONObject(raw)
        require(root.getInt("version") == 1 && root.getString("origin") == scope.origin)
        require(root.optString("account", "") == scope.accountId.orEmpty())
        return ReadingJournalCodec.decode(root.getJSONObject("journal"))
    }

    fun write(scope: ReadingScope, journal: ReadingJournal) {
        if (journal.visits.count { it.pending } > ReadingJournal.MAX_PENDING) throw IOException("Reading queue is full")
        val raw = JSONObject().put("version", 1).put("origin", scope.origin)
            .put("account", scope.accountId.orEmpty()).put("journal", ReadingJournalCodec.encode(journal)).toString()
        if (raw.toByteArray(Charsets.UTF_8).size > ReadingJournal.MAX_BYTES) throw IOException("Reading storage is full")
        if (!prefs.edit().putString(key(scope), raw).commit()) throw IOException("Reading checkpoint was not saved")
    }

    fun clearPrivate() {
        val editor = prefs.edit()
        prefs.all.forEach { (key, raw) ->
            // Malformed private rows are removed only by explicit logout/discard.
            if (runCatching { JSONObject(raw as String).optString("account").isNotBlank() }.getOrDefault(true)) editor.remove(key)
        }
        if (!editor.commit()) throw IOException("Unable to remove saved reading state")
        legacy.forEach { if (!it.edit().clear().commit()) throw IOException("Unable to remove old reading state") }
    }

    private fun key(scope: ReadingScope): String = MessageDigest.getInstance("SHA-256")
        .digest("${scope.origin}\n${scope.accountId.orEmpty()}".toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it.toInt() and 255) }

    companion object { const val GUEST_SCOPE = "guest" }
}

internal object ReadingJournalCodec {
    fun commandBody(value: ReadingCommand): JSONObject = JSONObject().put("command_id", value.id).apply {
        if (value.kind == "open") put("expected_revision", value.expectedRevision)
        else {
            val checkpoint = requireNotNull(value.position)
            put("session_generation", value.sessionGeneration)
            put("command_sequence", value.sequence)
            put("last_page", checkpoint.lastPage)
            put("scroll_position", checkpoint.scrollPosition)
            put("completed", checkpoint.completedPage > 0)
            put("completed_page", checkpoint.completedPage)
        }
    }

    private fun position(value: ReadingPosition) = JSONObject().put("page", value.lastPage)
        .put("scroll", value.scrollPosition).put("completed_page", value.completedPage)
    private fun position(value: JSONObject) = ReadingPosition(value.getInt("page"),
        value.getDouble("scroll"), value.getInt("completed_page"))

    fun encode(journal: ReadingJournal): JSONObject = JSONObject().put("next_generation", journal.nextGeneration).apply {
        put("visits", JSONArray().apply {
            journal.visits.forEach { visit -> put(JSONObject().apply {
                put("id", visit.id); put("generation", visit.generation); put("touched", visit.touchedAtMillis)
                put("acked", visit.acknowledgedGeneration); put("session", visit.sessionGeneration)
                put("sequence", visit.sequence); put("opened", visit.opened); put("pause", visit.pauseCode)
                visit.position?.let { put("position", position(it)) }
                put("target", JSONObject().apply {
                    val target = visit.target
                    put("series_id", target.seriesId); put("series_slug", target.seriesSlug); put("series_title", target.seriesTitle)
                    put("chapter_id", target.chapterId); put("chapter_slug", target.chapterSlug); put("chapter_number", target.chapterNumber)
                    put("chapter_title", target.chapterTitle); put("page_count", target.pageCount)
                })
                visit.command?.let { command -> put("command", JSONObject().apply {
                    put("id", command.id); put("kind", command.kind); put("generation", command.generation)
                    put("revision", command.expectedRevision); put("session", command.sessionGeneration); put("sequence", command.sequence)
                    command.position?.let { put("position", position(it)) }
                }) }
            }) }
        })
        put("canonical", JSONObject().apply {
            journal.canonical.forEach { (series, value) -> put(series, JSONObject().apply {
                put("last_page", value.lastPage); put("scroll_position", value.scrollPosition)
                put("revision", value.revision); put("series_id", value.seriesId); put("chapter_id", value.chapterId)
                put("session_generation", value.sessionGeneration); put("command_sequence", value.commandSequence)
            }) }
        })
    }

    fun decode(root: JSONObject): ReadingJournal {
        val array = root.getJSONArray("visits")
        val visits = (0 until array.length()).map { index ->
            val visit = array.getJSONObject(index)
            val target = visit.getJSONObject("target")
            ReadingVisit(visit.getString("id"), ReadingTarget(target.getString("series_id"), target.getString("series_slug"),
                target.getString("series_title"), target.getString("chapter_id"), target.getString("chapter_slug"),
                target.getDouble("chapter_number"), target.optString("chapter_title").takeIf { it.isNotEmpty() }, target.getInt("page_count")),
                visit.getLong("generation"), visit.getLong("touched"), visit.optJSONObject("position")?.let(::position),
                visit.getLong("acked"), visit.getLong("session"), visit.getLong("sequence"), visit.getBoolean("opened"),
                visit.optJSONObject("command")?.let { command -> ReadingCommand(command.getString("id"), command.getString("kind"),
                    command.getLong("generation"), command.getLong("revision"), command.getLong("session"), command.getLong("sequence"),
                    command.optJSONObject("position")?.let(::position)) },
                visit.optString("pause").takeIf { it.isNotEmpty() })
        }
        val canonical = root.getJSONObject("canonical")
        return ReadingJournal(root.getLong("next_generation"), visits,
            canonical.keys().asSequence().associateWith { parseProgress(canonical.getJSONObject(it)) })
    }
}
