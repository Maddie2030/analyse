package com.mreader.android.core.repository

import com.mreader.android.core.model.ReaderManifest
import com.mreader.android.core.model.ReadingProgress

/** Device order is local only. Server revision/session/sequence order all durable facts. */
data class ReadingScope(val origin: String, val accountId: String?)

data class ReadingTarget(
    val seriesId: String,
    val seriesSlug: String,
    val seriesTitle: String,
    val chapterId: String,
    val chapterSlug: String,
    val chapterNumber: Double,
    val chapterTitle: String?,
    val pageCount: Int,
) {
    companion object {
        fun from(manifest: ReaderManifest) = ReadingTarget(manifest.seriesId, manifest.seriesSlug,
            manifest.seriesTitle, manifest.chapterId, manifest.chapterSlug, manifest.chapterNumber,
            manifest.chapterTitle, manifest.pageCount)
    }
}

data class ReadingPosition(val lastPage: Int, val scrollPosition: Double, val completedPage: Int = 0)

/** Once attached to a visit, a command is immutable until its matching ACK. */
data class ReadingCommand(
    val id: String,
    val kind: String,
    val generation: Long,
    val expectedRevision: Long = 0,
    val sessionGeneration: Long = 0,
    val sequence: Long = 0,
    val position: ReadingPosition? = null,
)

data class ReadingVisit(
    val id: String,
    val target: ReadingTarget,
    val generation: Long,
    val touchedAtMillis: Long,
    val position: ReadingPosition? = null,
    val acknowledgedGeneration: Long = 0,
    val sessionGeneration: Long = 0,
    val sequence: Long = 0,
    val opened: Boolean = false,
    val command: ReadingCommand? = null,
    val pauseCode: String? = null,
) {
    val pending: Boolean get() = !opened || command != null || (position != null && generation > acknowledgedGeneration)

    fun checkpoint(page: Int, fraction: Double, endVerified: Boolean, nextGeneration: Long, now: Long): ReadingVisit {
        if (!fraction.isFinite()) return this
        val next = ReadingPosition(page.coerceIn(1, target.pageCount.coerceAtLeast(1)), fraction.coerceIn(0.0, 1.0),
            if (endVerified && target.pageCount > 0) target.pageCount else position?.completedPage ?: 0)
        return if (position == next) this else copy(position = next, generation = nextGeneration, touchedAtMillis = now)
    }

    fun freezeOpen(commandId: String, revision: Long): ReadingVisit =
        if (command != null || opened || pauseCode != null) this
        else copy(command = ReadingCommand(commandId, "open", generation, expectedRevision = revision))

    fun freezeCommit(commandId: String): ReadingVisit =
        if (command != null || !opened || !pending || pauseCode != null || position == null) this
        else copy(command = ReadingCommand(commandId, "commit", generation,
            sessionGeneration = sessionGeneration, sequence = sequence + 1, position = position))

    fun acknowledge(value: ReadingProgress): ReadingVisit {
        val sent = command ?: return this
        if (sent.id != value.commandId) return this
        if (!value.accepted) return copy(pauseCode = value.code ?: "conflict")
        // An old exact retry can return the current aggregate. Never borrow the
        // session belonging to another chapter (or a later visit to this chapter).
        if (value.chapterId != target.chapterId || value.sessionGeneration <= 0 ||
            (sent.kind == "commit" && value.sessionGeneration != sent.sessionGeneration)) {
            return copy(pauseCode = "stale_session")
        }
        return if (sent.kind == "open") copy(opened = true, command = null,
            sessionGeneration = value.sessionGeneration, sequence = 0,
            acknowledgedGeneration = if (position == null) sent.generation else acknowledgedGeneration)
        else copy(command = null, sequence = sent.sequence,
            acknowledgedGeneration = maxOf(acknowledgedGeneration, sent.generation))
    }
}

data class ReadingJournal(
    val nextGeneration: Long = 1,
    val visits: List<ReadingVisit> = emptyList(),
    val canonical: Map<String, ReadingProgress> = emptyMap(),
) {
    fun replace(visit: ReadingVisit): ReadingJournal = copy(visits = visits.map { if (it.id == visit.id) visit else it })

    /** Disk loading cannot erase activity captured while IO was pending. */
    fun prependStored(stored: ReadingJournal): ReadingJournal {
        var generation = maxOf(nextGeneration, stored.nextGeneration)
        val loadedIds = stored.visits.map { it.id }.toSet()
        val fresh = visits.filter { it.id !in loadedIds }.map { it.copy(generation = generation++) }
        return copy(nextGeneration = generation, visits = stored.visits + fresh, canonical = stored.canonical + canonical)
    }

    fun prune(now: Long): ReadingJournal {
        val confirmedIds = visits.filter { !it.pending && now - it.touchedAtMillis < CONFIRMED_TTL_MS }
            .takeLast(MAX_PENDING).map { it.id }.toSet()
        val retained = visits.filter { it.pending || it.id in confirmedIds }
        val seriesIds = retained.map { it.target.seriesId }.toSet()
        return copy(visits = retained, canonical = canonical.filterKeys { it in seriesIds })
    }

    companion object {
        const val MAX_PENDING = 500
        const val MAX_BYTES = 5 * 1024 * 1024
        const val CONFIRMED_TTL_MS = 7L * 24 * 60 * 60 * 1000
    }
}

data class ReadingView(
    val scope: ReadingScope? = null,
    val visits: List<ReadingVisit> = emptyList(),
    val storageProblem: Boolean = false,
    val suspendedUnsaved: Boolean = false,
    val confirmedEpoch: Long = 0,
    val syncing: Boolean = false,
    val needsSignIn: Boolean = false,
    val resetEpoch: Long = 0,
) {
    fun pending(seriesId: String): ReadingVisit? = visits.lastOrNull { it.target.seriesId == seriesId && it.pending }
    val pendingCount: Int get() = visits.count { it.pending }
    val paused: Boolean get() = visits.any { it.pauseCode != null }
}
