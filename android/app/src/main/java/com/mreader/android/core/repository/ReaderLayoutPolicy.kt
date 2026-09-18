package com.mreader.android.core.repository

import kotlin.math.roundToInt

/**
 * Native reader geometry shared by rendering, responsive asset selection, and
 * progress calculations.
 *
 * The Android reader is intentionally edge-to-edge: there is no synthetic
 * cream/paper surround. This keeps page geometry identical to the actual image
 * dimensions and removes inset-specific progress/resume drift.
 */
object ReaderLayoutPolicy {
    fun contentWidthDp(screenWidthDp: Int): Int = screenWidthDp.coerceAtLeast(1)

    fun pageRelativeHeight(width: Int?, height: Int?, screenWidthDp: Int): Double {
        // screenWidthDp is retained in the signature so rendering/progress call
        // sites share one policy, but edge-to-edge layout needs no inset math.
        screenWidthDp.coerceAtLeast(1)
        return ReaderProgressMath.relativeHeight(width, height)
    }

    fun contentWidthPx(screenWidthDp: Int, screenWidthPx: Float): Float {
        screenWidthDp.coerceAtLeast(1)
        return screenWidthPx.coerceAtLeast(1f)
    }

    fun decodeWidthPx(screenWidthDp: Int, screenWidthPx: Float): Int {
        val requested = contentWidthPx(screenWidthDp, screenWidthPx).roundToInt().coerceAtLeast(1)
        val cap = if (screenWidthDp <= 600) 720 else 1080
        return requested.coerceAtMost(cap)
    }
}
