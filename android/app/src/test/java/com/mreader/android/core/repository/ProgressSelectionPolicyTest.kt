package com.mreader.android.core.repository

import com.mreader.android.core.model.LocalProgressCheckpoint
import com.mreader.android.core.model.ReadingProgress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ProgressSelectionPolicyTest {
    @Test
    fun noProgressReturnsNull() {
        assertNull(ProgressSelectionPolicy.choose(null, null))
    }

    @Test
    fun localOnlyCheckpointIsSelected() {
        val selected = ProgressSelectionPolicy.choose(
            LocalProgressCheckpoint(lastPage = 4, scrollPosition = 0.42, updatedAtMillis = 200L),
            null,
        )
        assertEquals(4, selected?.lastPage)
        assertEquals(0.42, selected?.scrollPosition ?: -1.0, 0.0)
        assertEquals(200L, selected?.updatedAtMillis)
    }

    @Test
    fun serverOnlyCheckpointIsSelected() {
        val server = ReadingProgress(lastPage = 7, scrollPosition = 0.71, updatedAtMillis = 300L)
        assertEquals(server, ProgressSelectionPolicy.choose(null, server))
    }

    @Test
    fun pendingLocalCheckpointWinsWithoutTrustingDeviceClock() {
        val local = LocalProgressCheckpoint(lastPage = 9, scrollPosition = 0.91, updatedAtMillis = 500L)
        val server = ReadingProgress(lastPage = 8, scrollPosition = 0.81, updatedAtMillis = 400L)
        val selected = ProgressSelectionPolicy.choose(local, server)
        assertEquals(9, selected?.lastPage)
        assertEquals(0.91, selected?.scrollPosition ?: -1.0, 0.0)

        val newerServerClock = server.copy(updatedAtMillis = 600L)
        val stillPending = ProgressSelectionPolicy.choose(local, newerServerClock)
        assertEquals(9, stillPending?.lastPage)
        assertEquals(0.91, stillPending?.scrollPosition ?: -1.0, 0.0)
    }
}
