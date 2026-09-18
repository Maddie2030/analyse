package com.mreader.android.core.repository

import kotlin.math.max

/**
 * Pure progress math shared by the Android reader and unit tests.
 *
 * The backend's scroll_position is a whole-chapter fraction, not a fraction
 * within the current page. Android derives it from the relative rendered page
 * heights so chapters with mixed page heights remain proportional.
 */
object ReaderProgressMath {
    data class PageUnit(
        val pageNumber: Int,
        val relativeHeight: Double,
    )

    data class PageLocation(
        val pageNumber: Int,
        val withinPageFraction: Double,
    )

    fun chapterFraction(
        pages: List<PageUnit>,
        pageNumber: Int,
        withinPageFraction: Double,
    ): Double {
        if (pages.isEmpty()) return 0.0
        val normalized = pages.map { it.copy(relativeHeight = saneWeight(it.relativeHeight)) }
        val total = normalized.sumOf { it.relativeHeight }
        if (total <= 0.0) return 0.0
        val index = normalized.indexOfFirst { it.pageNumber == pageNumber }.let { if (it < 0) 0 else it }
        val before = normalized.take(index).sumOf { it.relativeHeight }
        val current = normalized[index].relativeHeight
        return ((before + current * withinPageFraction.coerceIn(0.0, 1.0)) / total).coerceIn(0.0, 1.0)
    }

    fun pageFractionFromChapterFraction(
        pages: List<PageUnit>,
        pageNumber: Int,
        chapterFraction: Double,
    ): Double {
        if (pages.isEmpty()) return 0.0
        val normalized = pages.map { it.copy(relativeHeight = saneWeight(it.relativeHeight)) }
        val total = normalized.sumOf { it.relativeHeight }
        if (total <= 0.0) return 0.0
        val index = normalized.indexOfFirst { it.pageNumber == pageNumber }.let { if (it < 0) 0 else it }
        val before = normalized.take(index).sumOf { it.relativeHeight }
        val current = normalized[index].relativeHeight
        val absolute = chapterFraction.coerceIn(0.0, 1.0) * total
        return ((absolute - before) / current).coerceIn(0.0, 1.0)
    }

    fun locationFromChapterFraction(
        pages: List<PageUnit>,
        chapterFraction: Double,
    ): PageLocation? {
        if (pages.isEmpty()) return null
        val normalized = pages.map { it.copy(relativeHeight = saneWeight(it.relativeHeight)) }
        val total = normalized.sumOf { it.relativeHeight }
        if (total <= 0.0) return PageLocation(normalized.first().pageNumber, 0.0)
        val target = chapterFraction.coerceIn(0.0, 1.0) * total
        var before = 0.0
        normalized.forEachIndexed { index, page ->
            val after = before + page.relativeHeight
            if (target < after || index == normalized.lastIndex) {
                return PageLocation(
                    page.pageNumber,
                    ((target - before) / page.relativeHeight).coerceIn(0.0, 1.0),
                )
            }
            before = after
        }
        return PageLocation(normalized.last().pageNumber, 1.0)
    }

    fun relativeHeight(width: Int?, height: Int?): Double {
        if (width == null || height == null || width <= 0 || height <= 0) return 1.0
        return saneWeight(height.toDouble() / width.toDouble())
    }

    private fun saneWeight(value: Double): Double = if (value.isFinite() && value > 0.0) max(value, 1e-6) else 1.0
}
