package com.mreader.android.core.repository

import com.mreader.android.core.model.LocalProgressCheckpoint
import com.mreader.android.core.model.ReadingProgress

/**
 * Overlays unacknowledged local intent without nullable smart-cast tricks in the
 * Compose UI. Local checkpoints are converted to the same model used for server
 * progress so the reader has one restore contract.
 */
object ProgressSelectionPolicy {
    fun choose(
        local: LocalProgressCheckpoint?,
        server: ReadingProgress?,
    ): ReadingProgress? {
        if (local == null) return server
        // A local row exists only while it is unacknowledged. Pending intent is
        // overlaid without comparing the device clock to the server clock.
        return ReadingProgress(
            lastPage = local.lastPage,
            scrollPosition = local.scrollPosition,
            updatedAtMillis = local.updatedAtMillis,
        )
    }
}
