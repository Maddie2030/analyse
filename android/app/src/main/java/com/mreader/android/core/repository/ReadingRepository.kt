package com.mreader.android.core.repository

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import com.mreader.android.core.model.LocalProgressCheckpoint
import com.mreader.android.core.model.ReaderManifest
import com.mreader.android.core.model.ReadingProgress
import com.mreader.android.core.network.ApiException
import com.mreader.android.core.network.MReaderApiAdapter
import com.mreader.android.core.network.parseProgress
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.util.UUID

/**
 * The one device reading owner. Public intent methods run on the main thread;
 * IO never blocks capture. Network/disk continuations return to this same lane.
 * The account in a request comes from its journal, never mutable login state.
 */
class ReadingRepository(context: Context, private val origin: String, private val api: MReaderApiAdapter) {
    private class Account(val scope: ReadingScope) {
        var journal = ReadingJournal()
        var loaded = CompletableDeferred<Unit>()
        var loadProblem = false
        var storageProblem = false
        var suspended = false
        var version = 0L
        var persistedVersion = -1L
        var saveJob: Job? = null
    }

    private val owner = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val disk = LocalProgressStore(context.applicationContext)
    private val diskLock = Mutex()
    private val networkLanes = Semaphore(2)
    private val accounts = mutableMapOf<ReadingScope, Account>()
    private val jobs = mutableMapOf<String, Job>()
    private val reads = mutableMapOf<String, Deferred<ReadingProgress>>()
    private val commitRequested = mutableSetOf<String>()
    private var active: Account? = null
    private var epoch = 0L
    private var confirmedEpoch = 0L
    private var resetEpoch = 0L
    private var discarding = false
    private val _view = MutableStateFlow(ReadingView())
    val view: StateFlow<ReadingView> = _view.asStateFlow()

    init {
        owner.launch { while (true) { delay(30_000L); flush() } }
        val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        connectivity.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { owner.launch { retryTransport() } }
        })
    }

    fun activate(accountId: String?) {
        val scope = ReadingScope(origin, accountId)
        if (active?.scope == scope && active?.suspended == false) return
        epoch++
        jobs.values.forEach { it.cancel() }
        jobs.clear()
        reads.values.forEach { it.cancel() }
        reads.clear()
        commitRequested.clear()
        val account = accounts.getOrPut(scope) { Account(scope).also { load(it) } }
        active = account
        account.suspended = false
        publish()
        flush()
    }

    /** Automatic expiry retains both durable and volatile private intent. */
    fun suspendAccount() {
        active?.takeIf { it.scope.accountId != null }?.suspended = true
        activate(null)
    }

    fun isCurrent(accountId: String): Boolean = !discarding && active?.scope?.accountId == accountId && active?.suspended == false
    fun identityVersion(): Long = epoch
    fun isCurrent(accountId: String, version: Long): Boolean = version == epoch && isCurrent(accountId)

    private fun load(account: Account) {
        owner.launch {
            try {
                val stored = diskLock.withLock { withContext(Dispatchers.IO) { disk.read(account.scope) } }
                account.journal = account.journal.prependStored(stored.prune(System.currentTimeMillis()))
                account.loadProblem = false
            } catch (cancelled: CancellationException) { throw cancelled
            } catch (_: Exception) {
                account.loadProblem = true
                account.storageProblem = true
            } finally {
                account.loaded.complete(Unit)
                publish()
                if (active === account) flush()
            }
        }
    }

    fun begin(manifest: ReaderManifest): String? {
        if (discarding) return null
        val account = active ?: return null
        if (account.journal.visits.count { it.pending } >= ReadingJournal.MAX_PENDING) {
            account.storageProblem = true
            publish()
            return null
        }
        val id = UUID.randomUUID().toString()
        val generation = account.journal.nextGeneration
        account.journal = account.journal.prune(System.currentTimeMillis()).copy(nextGeneration = generation + 1,
            visits = account.journal.prune(System.currentTimeMillis()).visits + ReadingVisit(id, ReadingTarget.from(manifest), generation,
                System.currentTimeMillis(), opened = account.scope.accountId == null,
                acknowledgedGeneration = if (account.scope.accountId == null) generation else 0))
        changed(account, immediate = true)
        flush(allowCommits = false)
        return id
    }

    fun checkpoint(visitId: String, page: Int, fraction: Double, endVerified: Boolean, flushNow: Boolean = false) {
        if (discarding) return
        val account = active ?: return
        val visit = account.journal.visits.find { it.id == visitId } ?: return
        val updated = visit.checkpoint(page, fraction, endVerified, account.journal.nextGeneration, System.currentTimeMillis())
        if (updated != visit) {
            val stored = if (account.scope.accountId == null) updated.copy(acknowledgedGeneration = updated.generation) else updated
            account.journal = account.journal.replace(stored).copy(nextGeneration = account.journal.nextGeneration + 1)
            changed(account, immediate = flushNow || endVerified)
        }
        if (flushNow || (endVerified && (visit.position?.completedPage ?: 0) == 0)) flush()
    }

    suspend fun localCheckpoint(visitId: String): LocalProgressCheckpoint? {
        val account = active ?: return null
        val capturedEpoch = epoch
        account.loaded.await()
        if (active !== account || capturedEpoch != epoch) return null
        val visit = account.journal.visits.find { it.id == visitId } ?: return null
        val previous = account.journal.visits.lastOrNull {
            it.target.chapterId == visit.target.chapterId && it.position != null &&
                (it.pending || account.scope.accountId == null)
        } ?: return null
        val checkpoint = previous.position ?: return null
        return LocalProgressCheckpoint(checkpoint.lastPage, checkpoint.scrollPosition, previous.touchedAtMillis,
            checkpoint.completedPage > 0, previous.generation)
    }

    suspend fun serverCheckpoint(visitId: String): ReadingProgress? {
        val account = active ?: return null
        if (account.scope.accountId == null) return null
        val capturedEpoch = epoch
        account.loaded.await()
        val target = account.journal.visits.find { it.id == visitId }?.target ?: return null
        val value = remoteCheckpoint(account, target, capturedEpoch)
        if (active !== account || capturedEpoch != epoch) return null
        rememberCanonical(account, target.seriesId, value)
        // GET is a series aggregate, not a checkpoint for the requested slug.
        return value.takeIf { it.chapterId == target.chapterId }
    }

    /** Restore and open revision resolution share only an in-flight GET, never a stale cache. */
    private suspend fun remoteCheckpoint(account: Account, target: ReadingTarget, version: Long): ReadingProgress {
        val key = "$version|${target.seriesId}|${target.chapterId}"
        val request = reads[key] ?: owner.async {
            parseProgress(api.progress(target.seriesSlug, target.chapterSlug, requireNotNull(account.scope.accountId)))
        }.also { task ->
            reads[key] = task
            task.invokeOnCompletion { owner.launch { if (reads[key] === task) reads.remove(key) } }
        }
        return request.await()
    }

    private fun rememberCanonical(account: Account, seriesId: String, value: ReadingProgress) {
        val current = account.journal.canonical[seriesId]
        if (current == null || value.revision >= current.revision) {
            account.journal = account.journal.copy(canonical = account.journal.canonical + (seriesId to value))
        }
    }

    private fun changed(account: Account, immediate: Boolean = false) {
        account.version++
        publish()
        scheduleSave(account, immediate)
    }

    private fun scheduleSave(account: Account, immediate: Boolean) {
        if (immediate) account.saveJob?.cancel()
        if (account.saveJob?.isActive == true) return
        account.saveJob = owner.launch {
            if (!immediate) delay(1_000L)
            val written = save(account)
            account.saveJob = null
            if (written && account.version > account.persistedVersion) scheduleSave(account, immediate = false)
        }
    }

    private suspend fun save(account: Account): Boolean {
        account.loaded.await()
        if (account.loadProblem || discarding) return false
        return diskLock.withLock {
            if (discarding) return@withLock false
            val version = account.version
            val snapshot = account.journal.prune(System.currentTimeMillis())
            try {
                withContext(Dispatchers.IO) { disk.write(account.scope, snapshot) }
                account.persistedVersion = version
                account.storageProblem = false
                publish()
                true
            } catch (cancelled: CancellationException) { throw cancelled
            } catch (_: Exception) {
                account.storageProblem = true
                publish()
                false
            }
        }
    }

    fun flush(allowCommits: Boolean = true) {
        val account = active ?: return
        if (discarding || account.suspended || account.scope.accountId == null || !account.loaded.isCompleted || account.loadProblem) return
        val capturedEpoch = epoch
        account.journal.visits.filter { it.pending }.groupBy { it.target.seriesId }.forEach { (seriesId, _) ->
            if (allowCommits) commitRequested.add(seriesId)
            if (jobs[seriesId]?.isActive == true) return@forEach
            jobs[seriesId] = owner.launch {
                try { networkLanes.withPermit { drain(account, seriesId, capturedEpoch) } }
                finally {
                    if (epoch == capturedEpoch) {
                        jobs.remove(seriesId)
                        publish()
                    }
                }
            }
        }
        publish()
    }

    private suspend fun drain(account: Account, seriesId: String, capturedEpoch: Long) {
        val accountId = requireNotNull(account.scope.accountId)
        var failures = 0
        while (active === account && epoch == capturedEpoch && !account.suspended && !discarding) {
            var visit = account.journal.visits.firstOrNull { it.target.seriesId == seriesId && it.pending } ?: break
            if (visit.pauseCode != null) break
            val needsNextOpen = account.journal.visits.any { it.target.seriesId == seriesId && it.id != visit.id && !it.opened }
            if (visit.opened && visit.command == null && seriesId !in commitRequested && !needsNextOpen) break
            try {
                if (visit.command == null) {
                    if (!visit.opened) {
                        // Resolve a dependency once, before freezing and saving its open.
                        // A concurrent remote update is then an explicit conflict.
                        val remote = remoteCheckpoint(account, visit.target, capturedEpoch)
                        if (active !== account || epoch != capturedEpoch) return
                        rememberCanonical(account, seriesId, remote)
                        visit = account.journal.visits.first { it.id == visit.id }.freezeOpen(UUID.randomUUID().toString(), remote.revision)
                    } else visit = visit.freezeCommit(UUID.randomUUID().toString())
                    account.journal = account.journal.replace(visit)
                    account.version++
                }
                val command = visit.command ?: break
                if (!save(account)) break // No request is sent before its exact payload is durable.
                if (active !== account || epoch != capturedEpoch) return
                val body = ReadingJournalCodec.commandBody(command).toString()
                val response = if (command.kind == "open") api.recordChapterOpen(visit.target.seriesSlug, visit.target.chapterSlug, accountId, body)
                    else api.commitProgress(visit.target.seriesSlug, visit.target.chapterSlug, accountId, body)
                if (active !== account || epoch != capturedEpoch) return
                if (!response.has("accepted") || !response.has("code") || !response.has("command_id")) {
                    val current = account.journal.visits.firstOrNull { it.id == visit.id } ?: return
                    account.journal = account.journal.replace(current.copy(pauseCode = "invalid_ack"))
                    changed(account, immediate = true)
                    return
                }
                val canonical = parseProgress(response)
                val current = account.journal.visits.firstOrNull { it.id == visit.id } ?: return
                val acknowledged = if (canonical.commandId != command.id) current.copy(pauseCode = "invalid_ack")
                    else current.acknowledge(canonical)
                rememberCanonical(account, seriesId, canonical)
                account.journal = account.journal.replace(acknowledged)
                changed(account, immediate = true)
                if (acknowledged.pauseCode != null) break
                confirmedEpoch++
                publish()
                failures = 0
            } catch (cancelled: CancellationException) { throw cancelled
            } catch (error: ApiException) {
                if (active !== account || epoch != capturedEpoch) return
                if (error.status == 401 || error.status == 403) {
                    account.suspended = true
                    publish()
                    return
                }
                if (error.status in 400..499 && error.status != 408 && error.status != 429) {
                    val current = account.journal.visits.firstOrNull { it.id == visit.id } ?: return
                    account.journal = account.journal.replace(current.copy(pauseCode = if (error.status == 404) "target_missing" else "invalid_command"))
                    changed(account, immediate = true)
                    return
                }
                failures++
                delay((1_000L shl failures.coerceAtMost(6)).coerceAtMost(60_000L))
            } catch (_: Exception) {
                failures++
                delay((1_000L shl failures.coerceAtMost(6)).coerceAtMost(60_000L))
            }
        }
        commitRequested.remove(seriesId)
    }

    /** Retries transport/storage failures only; never silently rebases a conflict. */
    fun retryTransport() {
        accounts.values.filter { it.loadProblem }.forEach {
            it.loaded = CompletableDeferred()
            it.loadProblem = false
            load(it)
        }
        active?.let { changed(it, immediate = true) }
        flush()
    }

    /** Explicit user choice: discard this series' pending intent and reconcile from server. */
    fun useServerProgress(seriesId: String) {
        val account = active ?: return
        jobs.remove(seriesId)?.cancel()
        account.journal = account.journal.copy(visits = account.journal.visits.filterNot { it.target.seriesId == seriesId && it.pending })
        confirmedEpoch++
        resetEpoch++
        changed(account, immediate = true)
    }

    fun hasPrivatePending(): Boolean = accounts.values.any { it.scope.accountId != null && it.journal.visits.any { visit -> visit.pending } }

    /** Called only by the explicit, warned logout action. Failure leaves intent retained. */
    suspend fun discardPrivateForLogout() {
        discarding = true
        epoch++
        try {
            val pendingJobs = jobs.values.toList() + reads.values.toList() + accounts.values.mapNotNull { it.saveJob }
            jobs.clear()
            reads.clear()
            pendingJobs.forEach { it.cancelAndJoin() }
            diskLock.withLock { withContext(Dispatchers.IO) { disk.clearPrivate() } }
            accounts.keys.filter { it.accountId != null }.forEach { accounts.remove(it) }
            active = null
        } finally {
            discarding = false
            publish()
        }
        activate(null)
    }

    private fun publish() {
        val account = active
        _view.value = ReadingView(account?.scope, account?.journal?.visits.orEmpty(),
            account?.storageProblem == true || account?.loadProblem == true,
            accounts.values.any { it !== account && it.scope.accountId != null && it.storageProblem && it.journal.visits.any { visit -> visit.pending } },
            confirmedEpoch, jobs.values.any { it.isActive }, account?.suspended == true, resetEpoch)
    }
}
