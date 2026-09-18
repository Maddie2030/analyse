package com.mreader.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.mreader.android.core.model.ReaderManifest
import com.mreader.android.core.model.User
import com.mreader.android.core.repository.MReaderRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class AppViewModel(val repository: MReaderRepository) : ViewModel() {
    private val _user = MutableStateFlow<User?>(repository.cachedProfile())
    val user: StateFlow<User?> = _user.asStateFlow()
    val reading = repository.reading.view
    private val _logoutProblem = MutableStateFlow<String?>(null)
    val logoutProblem: StateFlow<String?> = _logoutProblem.asStateFlow()

    private val _sessionReady = MutableStateFlow(false)
    val sessionReady: StateFlow<Boolean> = _sessionReady.asStateFlow()

    private val _unreadNotifications = MutableStateFlow(0)
    val unreadNotifications: StateFlow<Int> = _unreadNotifications.asStateFlow()

    // Bumped whenever account/reading mutations can make an already-visible
    // section stale. Screens key their best-effort refreshes to this value.
    private val _contentEpoch = MutableStateFlow(0L)
    val contentEpoch: StateFlow<Long> = _contentEpoch.asStateFlow()

    // Separate lightweight epoch for Settings cache-usage accounting. Updating
    // this does not force Browse/Search/Library to re-fetch content just because
    // a background chapter download finished.
    private val _cacheEpoch = MutableStateFlow(0L)
    val cacheEpoch: StateFlow<Long> = _cacheEpoch.asStateFlow()

    // Persistent chapter-cache jobs live in the activity ViewModel rather than a
    // ReaderScreen composition, so navigating back to Browse does not cancel a
    // signed-in user's 24-hour chapter download.
    private val chapterCacheJobs = mutableMapOf<String, Job>()

    private fun invalidateContent() { _contentEpoch.value = _contentEpoch.value + 1L }
    private fun invalidateCacheUsage() { _cacheEpoch.value = _cacheEpoch.value + 1L }

    fun notifyContentChanged() = invalidateContent()

    fun cacheChapterFor24Hours(manifest: ReaderManifest, screenWidthDp: Int, screenWidthPx: Float) {
        val accountId = _user.value?.id ?: return
        val key = "$accountId|${manifest.chapterId}"
        if (chapterCacheJobs[key]?.isActive == true) return
        chapterCacheJobs[key] = viewModelScope.launch {
            var completed = false
            try {
                // Prioritize the visible page and the 3-ahead/2-behind reader
                // window. The chapter-wide cache then fills remaining encoded
                // objects through its single background lane.
                delay(900L)
                repository.cacheReaderChapter(
                    manifest = manifest,
                    chapterToken = manifest.chapterToken,
                    screenWidthDp = screenWidthDp,
                    screenWidthPx = screenWidthPx,
                    persistentCacheEnabled = true,
                )
                completed = true
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                // Chapter caching is a privilege/optimization, never a reading blocker.
            } finally {
                chapterCacheJobs.remove(key)
                if (completed) invalidateCacheUsage()
            }
        }
    }

    private suspend fun cancelChapterCacheJobsAndAwait() {
        val jobs = chapterCacheJobs.values.toList()
        chapterCacheJobs.clear()
        jobs.forEach { it.cancel() }
        jobs.joinAll()
    }

    suspend fun clearDownloadedData() {
        cancelChapterCacheJobsAndAwait()
        repository.clearDownloadedData()
        invalidateCacheUsage()
        invalidateContent()
    }

    fun refreshForegroundContent() {
        repository.reading.retryTransport()
        // Public discovery/catalog data can change while a guest is backgrounded.
        // For a cached signed-in identity, independently reconcile the profile:
        // transport failures keep local personal content usable, but a real 401
        // clears the stale session and prevents cross-session Smart Library access.
        invalidateContent()
        if (_user.value != null) {
            refreshNotificationCount()
            viewModelScope.launch {
                try {
                    val remote = repository.profile()
                    if (remote == null) {
                        cancelChapterCacheJobsAndAwait()
                        repository.clearExpiredSessionState()
                        _user.value = null
                        _unreadNotifications.value = 0
                        invalidateCacheUsage()
                        invalidateContent()
                    } else {
                        _user.value = remote
                        repository.reading.activate(remote.id)
                    }
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Throwable) {
                    // Keep the encrypted last-known identity and account-scoped
                    // local cache while the server is temporarily unavailable.
                }
            }
        }
    }

    init {
        repository.reading.activate(_user.value?.id)
        viewModelScope.launch {
            var lastConfirmed = repository.reading.view.value.confirmedEpoch
            repository.reading.view.collect { value ->
                if (value.confirmedEpoch != lastConfirmed) { lastConfirmed = value.confirmedEpoch; invalidateContent() }
            }
        }
        viewModelScope.launch {
            try {
                val remote = repository.profile()
                if (remote == null) {
                    repository.clearExpiredSessionState()
                    _user.value = null
                } else {
                    _user.value = remote
                    repository.reading.activate(remote.id)
                }
                if (_user.value != null) {
                    _unreadNotifications.value = try {
                        repository.notificationCount()
                    } catch (cancelled: CancellationException) {
                        throw cancelled
                    } catch (_: Throwable) {
                        0
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                // Do not demote a previously verified account to guest merely
                // because DNS/TLS/gateway is temporarily unavailable. The cached
                // identity is only a UI/cache scope; the encrypted cookie still
                // decides whether server requests are authenticated.
            } finally {
                _sessionReady.value = true
            }
        }
    }

    suspend fun register(username: String, email: String, password: String): Result<User> = try {
        Result.success(repository.register(username, email, password).also {
            _user.value = it
            repository.reading.activate(it.id)
            invalidateContent()
            _unreadNotifications.value = try {
                repository.notificationCount()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                0
            }
        })
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (failure: Throwable) {
        Result.failure(failure)
    }

    suspend fun login(identifier: String, password: String): Result<User> = try {
        Result.success(repository.login(identifier, password).also {
            _user.value = it
            repository.reading.activate(it.id)
            invalidateContent()
            _unreadNotifications.value = try {
                repository.notificationCount()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                0
            }
        })
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (failure: Throwable) {
        Result.failure(failure)
    }

    fun logout() {
        viewModelScope.launch {
            _logoutProblem.value = null
            try {
                cancelChapterCacheJobsAndAwait()
                repository.logout()
                invalidateCacheUsage()
                _user.value = null
                _unreadNotifications.value = 0
                invalidateContent()
            } catch (cancelled: CancellationException) { throw cancelled
            } catch (_: Throwable) {
                _logoutProblem.value = "Could not remove local reading data. Free storage and try signing out again."
            }
        }
    }

    suspend fun updateAvatar(avatarKey: String): Result<User> = try {
        Result.success(repository.updateAvatar(avatarKey).also {
            _user.value = it
            repository.reading.activate(it.id)
            invalidateContent()
        })
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (failure: Throwable) {
        Result.failure(failure)
    }

    fun refreshNotificationCount() {
        val accountId = _user.value?.id
        if (accountId == null) {
            _unreadNotifications.value = 0
            return
        }
        viewModelScope.launch {
            try {
                val count = repository.notificationCount()
                if (_user.value?.id == accountId) _unreadNotifications.value = count
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                // Keep the last known badge count until the next foreground refresh.
            }
        }
    }

    fun setUnreadNotificationCount(value: Int) {
        _unreadNotifications.value = value.coerceAtLeast(0)
    }

    /** Marks one notification read in ViewModel scope so navigation cannot cancel the request. */
    fun markNotificationRead(notificationId: String) {
        val accountId = _user.value?.id ?: return
        viewModelScope.launch {
            try {
                repository.markNotificationRead(notificationId)
                val count = repository.notificationCount()
                if (_user.value?.id == accountId) _unreadNotifications.value = count
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Throwable) {
                // The Notifications screen keeps its local optimistic state; a later
                // foreground refresh reconciles the badge with the server.
            }
        }
    }

    fun recordChapterOpen(manifest: ReaderManifest): String? = repository.reading.begin(manifest)

    fun checkpointProgress(visitId: String, page: Int, scroll: Double, completed: Boolean, commitServer: Boolean) {
        repository.reading.checkpoint(visitId, page, scroll, completed, commitServer)
    }

    class Factory(private val repository: MReaderRepository) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = AppViewModel(repository) as T
    }
}
