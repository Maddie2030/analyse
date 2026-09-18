package com.mreader.android.core.repository

import org.junit.Assert.assertEquals
import org.junit.Test

class ReaderLayoutPolicyTest {
    @Test
    fun standardPhoneUsesFullScreenWidth() {
        assertEquals(360, ReaderLayoutPolicy.contentWidthDp(360))
    }

    @Test
    fun narrowPhoneStillUsesFullScreenWidth() {
        assertEquals(320, ReaderLayoutPolicy.contentWidthDp(320))
    }

    @Test
    fun progressGeometryMatchesImageAspectRatioWithoutPadding() {
        val relative = ReaderLayoutPolicy.pageRelativeHeight(width = 1000, height = 1500, screenWidthDp = 360)
        assertEquals(1.5, relative, 0.000001)
    }

    @Test
    fun physicalContentWidthIsFullScreenWidth() {
        assertEquals(720f, ReaderLayoutPolicy.contentWidthPx(360, 720f))
    }

    @Test
    fun decodeWidthUsesFullVisibleReaderWidthWithinPhoneCap() {
        assertEquals(720, ReaderLayoutPolicy.decodeWidthPx(360, 720f))
    }
}
