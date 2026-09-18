package com.mreader.android.core.repository

import org.junit.Assert.assertEquals
import org.junit.Test

class ReaderTokenPolicyTest {
    @Test fun chapterTokenIsCanonical() {
        assertEquals("chapter", ReaderTokenPolicy.choose(" chapter "))
    }

    @Test fun missingChapterTokenDoesNotUsePageFallback() {
        assertEquals("", ReaderTokenPolicy.choose(null))
    }
}
