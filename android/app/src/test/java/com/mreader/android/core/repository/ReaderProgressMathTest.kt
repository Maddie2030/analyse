package com.mreader.android.core.repository

import org.junit.Assert.assertEquals
import org.junit.Test

class ReaderProgressMathTest {
    private val pages = listOf(
        ReaderProgressMath.PageUnit(1, 1.0),
        ReaderProgressMath.PageUnit(2, 2.0),
        ReaderProgressMath.PageUnit(3, 1.0),
    )

    @Test
    fun chapterFractionUsesWholeChapterWeights() {
        assertEquals(0.0, ReaderProgressMath.chapterFraction(pages, 1, 0.0), 1e-9)
        assertEquals(0.25, ReaderProgressMath.chapterFraction(pages, 2, 0.0), 1e-9)
        assertEquals(0.50, ReaderProgressMath.chapterFraction(pages, 2, 0.5), 1e-9)
        assertEquals(0.75, ReaderProgressMath.chapterFraction(pages, 3, 0.0), 1e-9)
        assertEquals(1.0, ReaderProgressMath.chapterFraction(pages, 3, 1.0), 1e-9)
    }

    @Test
    fun pageFractionRoundTrips() {
        val chapter = ReaderProgressMath.chapterFraction(pages, 2, 0.37)
        assertEquals(0.37, ReaderProgressMath.pageFractionFromChapterFraction(pages, 2, chapter), 1e-9)
    }

    @Test
    fun chapterLocationUsesWholeChapterFraction() {
        assertEquals(1, ReaderProgressMath.locationFromChapterFraction(pages, 0.0)?.pageNumber)
        assertEquals(2, ReaderProgressMath.locationFromChapterFraction(pages, 0.50)?.pageNumber)
        assertEquals(0.50, ReaderProgressMath.locationFromChapterFraction(pages, 0.50)?.withinPageFraction ?: -1.0, 1e-9)
        assertEquals(3, ReaderProgressMath.locationFromChapterFraction(pages, 1.0)?.pageNumber)
        assertEquals(1.0, ReaderProgressMath.locationFromChapterFraction(pages, 1.0)?.withinPageFraction ?: -1.0, 1e-9)
    }

    @Test
    fun invalidDimensionsFallBackToUnitWeight() {
        assertEquals(1.0, ReaderProgressMath.relativeHeight(null, 10), 0.0)
        assertEquals(1.0, ReaderProgressMath.relativeHeight(0, 10), 0.0)
        assertEquals(2.0, ReaderProgressMath.relativeHeight(500, 1000), 1e-9)
    }
}
