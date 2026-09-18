package com.mreader.android.core.repository

import com.mreader.android.core.model.ReadingProgress
import org.junit.Assert.*
import org.junit.Test

class ReadingJournalTest {
    private val target = ReadingTarget("series", "series-slug", "Series", "chapter", "ch-1", 1.0, null, 10)
    private fun opened(): ReadingVisit = ReadingVisit("visit", target, 1, 100L)
        .freezeOpen("open-id", 4)
        .acknowledge(ReadingProgress(1, 0.0, revision = 5, chapterId = "chapter",
            sessionGeneration = 3, commandId = "open-id"))

    @Test fun rejectedAckRetainsPayloadAndCheckpoint() {
        val pending = opened().checkpoint(7, 0.7, false, 2, 200).freezeCommit("commit-id")
        val rejected = pending.acknowledge(ReadingProgress(2, 0.2, revision = 9,
            accepted = false, code = "stale_session", commandId = "commit-id"))
        assertEquals(pending.command, rejected.command)
        assertEquals(7, rejected.position?.lastPage)
        assertEquals("stale_session", rejected.pauseCode)
        assertTrue(rejected.pending)
    }

    @Test fun oldAckCannotClearMovementCapturedDuringUpload() {
        val sent = opened().checkpoint(3, 0.3, false, 2, 200).freezeCommit("commit-id")
        val moved = sent.checkpoint(8, 0.8, false, 3, 300)
        val acknowledged = moved.acknowledge(ReadingProgress(3, 0.3, revision = 6,
            chapterId = "chapter", sessionGeneration = 3, commandSequence = 1, commandId = "commit-id"))
        assertEquals(8, acknowledged.position?.lastPage)
        assertTrue(acknowledged.pending)
        val next = acknowledged.freezeCommit("next-id").command!!
        assertEquals(2L, next.sequence)
        assertEquals(8, next.position?.lastPage)
    }

    @Test fun timeoutRetryNeverChangesCommandIdentityOrPayload() {
        val sent = opened().checkpoint(3, 0.3, false, 2, 200).freezeCommit("commit-id")
        val moved = sent.checkpoint(8, 0.8, false, 3, 300).freezeCommit("must-not-replace")
        assertEquals(sent.command, moved.command)
    }

    @Test fun completedEvidenceSurvivesScrollingBack() {
        val visit = opened().checkpoint(10, 1.0, true, 2, 200)
            .checkpoint(2, 0.2, false, 3, 300).freezeCommit("commit-id")
        assertEquals(2, visit.command?.position?.lastPage)
        assertEquals(10, visit.command?.position?.completedPage)
    }

    @Test fun unrelatedAckCannotAdvanceTheVisit() {
        val pending = opened().checkpoint(3, 0.3, false, 2, 200).freezeCommit("commit-id")
        assertEquals(pending, pending.acknowledge(ReadingProgress(3, 0.3, commandId = "other")))
    }

    @Test fun duplicateOpenWithAnotherCurrentChapterCannotBorrowItsSession() {
        val pending = ReadingVisit("visit", target, 1, 100).freezeOpen("open-id", 4)
        val result = pending.acknowledge(ReadingProgress(4, 0.4, revision = 8,
            chapterId = "another", sessionGeneration = 9, duplicate = true, commandId = "open-id"))
        assertEquals("stale_session", result.pauseCode)
        assertEquals(0L, result.sessionGeneration)
        assertNotNull(result.command)
    }

    @Test fun unchangedPositionIsNotDirtiedByTimer() {
        val visit = opened().checkpoint(3, 0.3, false, 2, 200)
        assertEquals(visit, visit.checkpoint(3, 0.3, false, 3, 300))
    }

    @Test fun originAndAccountAreBothPartOfScopeIdentity() {
        assertNotEquals(ReadingScope("https://one", "a"), ReadingScope("https://one", "b"))
        assertNotEquals(ReadingScope("https://one", "a"), ReadingScope("https://two", "a"))
        assertNotEquals(ReadingScope("https://one", null), ReadingScope("https://one", "a"))
    }

    @Test fun delayedDiskLoadKeepsEarlierCommandsAheadOfNewIntent() {
        val old = opened().checkpoint(3, 0.3, false, 8, 200).freezeCommit("old-command")
        val stored = ReadingJournal(nextGeneration = 9, visits = listOf(old))
        val fresh = ReadingVisit("new-visit", target.copy(chapterId = "next", chapterSlug = "ch-2"), 1, 300)
        val merged = ReadingJournal(nextGeneration = 2, visits = listOf(fresh)).prependStored(stored)
        assertEquals(listOf("visit", "new-visit"), merged.visits.map { it.id })
        assertEquals(old.command, merged.visits.first().command)
        assertTrue(merged.visits.last().generation > old.generation)
        assertTrue(merged.nextGeneration > merged.visits.last().generation)
    }

    @Test fun pruningNeverDropsUnacknowledgedCommands() {
        val pending = opened().checkpoint(3, 0.3, false, 2, 200).freezeCommit("unacknowledged")
        val expired = opened().copy(id = "expired")
        val pruned = ReadingJournal(visits = listOf(expired, pending)).prune(ReadingJournal.CONFIRMED_TTL_MS + 1_000)
        assertEquals(listOf(pending), pruned.visits)
    }

    @Test fun retryDoesNotReplaceAnOpenRevisionAfterItIsFrozen() {
        val pending = ReadingVisit("visit", target, 1, 100).freezeOpen("open-id", 4)
        assertEquals(pending, pending.freezeOpen("new-id", 99))
    }
}
