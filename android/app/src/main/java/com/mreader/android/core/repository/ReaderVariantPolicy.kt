package com.mreader.android.core.repository

/**
 * Matches the web reader's responsive-page selection rule.
 *
 * The 720px derivative is only preferred on narrow layouts when the device's
 * physical-pixel demand stays within 15% of that derivative. High-DPR phones
 * keep the primary protected asset so line art is not softened unnecessarily.
 */
object ReaderVariantPolicy {
    fun preferResponsive(
        screenWidthDp: Int,
        screenWidthPx: Float,
        responsiveWidth: Int?,
    ): Boolean {
        val width = responsiveWidth ?: return false
        if (width <= 0 || screenWidthDp > 820 || screenWidthPx <= 0f) return false
        return screenWidthPx <= width.toFloat() * 1.15f
    }
}
