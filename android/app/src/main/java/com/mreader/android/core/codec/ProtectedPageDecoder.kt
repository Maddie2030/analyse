package com.mreader.android.core.codec

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Native decoder for MReader protected page codecs.
 *
 * Unlike a browser canvas, Android has a relatively strict per-process bitmap
 * heap. The decoder therefore reconstructs into a display-sized output bitmap
 * instead of blindly allocating the source dimensions. v4 remains lossless in
 * tile placement while the final canvas may be downscaled for the phone.
 */
class ProtectedPageDecoder {
    data class Encoding(
        val version: Int,
        val width: Int,
        val height: Int,
        val rows: Int,
        val columns: Int,
        val seed: String,
        val pageNumber: Int,
    )

    fun decode(bytes: ByteArray, encoding: Encoding, targetWidthPx: Int = encoding.width): Bitmap {
        val output = outputSize(encoding, targetWidthPx)
        validateEncoding(encoding, output.first, output.second)
        return try {
            decodeV4(bytes, encoding, output.first, output.second)
        } catch (oom: OutOfMemoryError) {
            throw IOException("Android ran out of memory decoding this page. Try the responsive page variant.", oom)
        }
    }

    private fun decodeV4(bytes: ByteArray, encoding: Encoding, outputWidth: Int, outputHeight: Int): Bitmap {
        if (bytes.size < V4_HEADER_BYTES) throw IOException("Protected v4 tile-pack is truncated.")
        for (i in V4_MAGIC.indices) {
            if (bytes[i] != V4_MAGIC[i]) throw IOException("Invalid protected v4 tile-pack magic.")
        }
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN)
        buffer.position(8)
        val rows = buffer.short.toInt() and 0xffff
        val columns = buffer.short.toInt() and 0xffff
        val overlap = buffer.short.toInt() and 0xffff
        buffer.short // reserved
        val width = buffer.int.toLong() and 0xffffffffL
        val height = buffer.int.toLong() and 0xffffffffL
        val total = buffer.int.toLong() and 0xffffffffL
        if (
            rows != encoding.rows || columns != encoding.columns ||
            width != encoding.width.toLong() || height != encoding.height.toLong() ||
            total != rows.toLong() * columns.toLong() || total !in 1..1024
        ) throw IOException("Protected v4 tile-pack metadata does not match the chapter manifest.")

        val tileCount = total.toInt()
        val lengthTableEnd = V4_HEADER_BYTES + tileCount * 4
        if (lengthTableEnd > bytes.size) throw IOException("Protected v4 length table is truncated.")
        val lengths = IntArray(tileCount)
        var cursor = V4_HEADER_BYTES
        repeat(tileCount) { index ->
            val length = ByteBuffer.wrap(bytes, cursor, 4).order(ByteOrder.BIG_ENDIAN).int.toLong() and 0xffffffffL
            if (length !in 1..MAX_TILE_BYTES.toLong()) throw IOException("Protected v4 tile length is invalid.")
            lengths[index] = length.toInt()
            cursor += 4
        }
        cursor = lengthTableEnd
        val ranges = Array(tileCount) { 0 until 0 }
        lengths.forEachIndexed { index, length ->
            val end = cursor + length
            if (end < cursor || end > bytes.size) throw IOException("Protected v4 tile payload is truncated.")
            ranges[index] = cursor until end
            cursor = end
        }
        if (cursor != bytes.size) throw IOException("Protected v4 tile-pack has trailing bytes.")

        val output = safeBitmap(outputWidth, outputHeight)
        val canvas = Canvas(output)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { isFilterBitmap = outputWidth != encoding.width }
        val order = ProtectedCodecMath.permutationV4(tileCount, encoding.seed, encoding.pageNumber)

        try {
            ranges.forEachIndexed { encodedIndex, range ->
                val tile = BitmapFactory.decodeByteArray(bytes, range.first, range.last - range.first + 1, BITMAP_OPTIONS)
                    ?: throw IOException("Android could not decode a protected v4 WebP tile.")
                try {
                    val tileBytes = tile.width.toLong() * tile.height.toLong() * 4L
                    if (tileBytes > Runtime.getRuntime().maxMemory() * 30L / 100L) {
                        throw IOException("A protected tile is too large for this Android device.")
                    }
                    val originalIndex = order[encodedIndex]
                    val row = originalIndex / columns
                    val col = originalIndex % columns
                    val bx = ProtectedCodecMath.bounds(encoding.width, columns, col)
                    val by = ProtectedCodecMath.bounds(encoding.height, rows, row)
                    val left = max(0, bx.position - overlap)
                    val top = max(0, by.position - overlap)
                    val sx = bx.position - left
                    val sy = by.position - top
                    if (tile.width < sx + bx.size || tile.height < sy + by.size) {
                        throw IOException("Protected v4 tile dimensions are invalid.")
                    }
                    val dx = ProtectedCodecMath.bounds(outputWidth, columns, col)
                    val dy = ProtectedCodecMath.bounds(outputHeight, rows, row)
                    canvas.drawBitmap(
                        tile,
                        Rect(sx, sy, sx + bx.size, sy + by.size),
                        Rect(dx.position, dy.position, dx.position + dx.size, dy.position + dy.size),
                        paint,
                    )
                } finally {
                    tile.recycle()
                }
            }
            return output
        } catch (error: Throwable) {
            output.recycle()
            throw error
        }
    }

    private fun safeBitmap(width: Int, height: Int): Bitmap =
        Bitmap.createBitmap(width.coerceAtLeast(1), height.coerceAtLeast(1), Bitmap.Config.ARGB_8888)

    private fun outputSize(encoding: Encoding, targetWidthPx: Int): Pair<Int, Int> {
        var width = min(encoding.width, targetWidthPx.coerceAtLeast(1)).coerceAtLeast(1)
        var height = max(1, ((encoding.height.toDouble() * width) / encoding.width.toDouble()).toInt())
        var pixels = width.toLong() * height.toLong()
        if (pixels > MAX_OUTPUT_PIXELS) {
            val scale = sqrt(MAX_OUTPUT_PIXELS.toDouble() / pixels.toDouble())
            width = max(1, (width * scale).toInt())
            height = max(1, ((encoding.height.toDouble() * width) / encoding.width.toDouble()).toInt())
            pixels = width.toLong() * height.toLong()
        }
        if (pixels <= 0L) throw IOException("Protected page output dimensions are invalid.")
        return width to height
    }

    private fun validateEncoding(encoding: Encoding, outputWidth: Int, outputHeight: Int) {
        if (encoding.version != 4) throw IOException("Unsupported protected-page codec v${encoding.version}; current MReader requires v4.")
        if (encoding.width <= 0 || encoding.height <= 0 || encoding.rows <= 0 || encoding.columns <= 0 || encoding.seed.isBlank()) {
            throw IOException("Protected page metadata is incomplete.")
        }
        if (encoding.rows.toLong() * encoding.columns.toLong() > 1024L) throw IOException("Protected page grid is unsafe.")
        val outputPixels = outputWidth.toLong() * outputHeight.toLong()
        val estimatedBytes = outputPixels * 4L
        val heapBudget = Runtime.getRuntime().maxMemory() * 45L / 100L
        if (estimatedBytes > heapBudget) {
            throw IOException("Protected page would consume too much Android heap; a smaller derivative is required.")
        }
    }

    private companion object {
        val V4_MAGIC = byteArrayOf(77, 82, 84, 73, 76, 69, 52, 0)
        const val V4_HEADER_BYTES = 28
        const val MAX_OUTPUT_PIXELS = 4_000_000L
        const val MAX_TILE_BYTES = 8 * 1024 * 1024
        val BITMAP_OPTIONS = BitmapFactory.Options().apply {
            inPreferredConfig = Bitmap.Config.ARGB_8888
            inScaled = false
        }
    }
}
