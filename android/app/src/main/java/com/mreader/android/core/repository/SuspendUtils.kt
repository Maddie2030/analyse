package com.mreader.android.core.repository

import kotlinx.coroutines.CancellationException

/**
 * Best-effort helpers for optional UI data. Unlike Kotlin runCatching, these
 * never swallow coroutine cancellation, so an old screen/request cannot finish
 * later and overwrite state belonging to a newer navigation/filter selection.
 */
suspend inline fun <T> bestEffortOrNull(crossinline block: suspend () -> T): T? = try {
    block()
} catch (cancelled: CancellationException) {
    throw cancelled
} catch (_: Throwable) {
    null
}

suspend inline fun <T> bestEffort(default: T, crossinline block: suspend () -> T): T =
    bestEffortOrNull(block) ?: default
