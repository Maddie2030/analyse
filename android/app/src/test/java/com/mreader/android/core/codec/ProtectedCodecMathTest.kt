package com.mreader.android.core.codec

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class ProtectedCodecMathTest {
    @Test
    fun v4Permutation_matchesBrowserReferenceVector() {
        assertArrayEquals(
            intArrayOf(10, 15, 13, 0, 8, 1, 3, 6, 7, 12, 14, 4, 11, 9, 5, 2),
            ProtectedCodecMath.permutationV4(16, "0123456789abcdef0123456789abcdef", 7),
        )
    }


    @Test
    fun bounds_matchIntegerSliceContract() {
        assertEquals(ProtectedCodecMath.Slice(0, 270), ProtectedCodecMath.bounds(1080, 4, 0))
        assertEquals(ProtectedCodecMath.Slice(810, 270), ProtectedCodecMath.bounds(1080, 4, 3))
        assertEquals(8192, ProtectedCodecMath.bounds(8192, 1, 0).size)
    }


}
