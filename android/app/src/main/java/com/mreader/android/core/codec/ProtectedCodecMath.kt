package com.mreader.android.core.codec

object ProtectedCodecMath {
    const val SALT_V4 = "mreader-v4-overlap-tilepack"

    data class Slice(val position: Int, val size: Int)

    fun permutationV4(count: Int, seed: String, pageNumber: Int): IntArray =
        permutation(count, "$SALT_V4:$seed:page:$pageNumber:$count")

    fun bounds(total: Int, count: Int, index: Int): Slice {
        require(total > 0 && count > 0 && index in 0 until count)
        val p0 = ((index.toLong() * total) / count).toInt()
        val p1 = (((index + 1L) * total) / count).toInt()
        return Slice(p0, (p1 - p0).coerceAtLeast(1))
    }

    fun hash32(input: String): Int {
        var h = 0x811c9dc5.toInt()
        input.forEach { ch ->
            h = h xor ch.code
            h *= 16777619
        }
        return h
    }

    private fun permutation(count: Int, material: String): IntArray {
        require(count in 0..1024)
        val output = IntArray(count) { it }
        val random = Mulberry32(hash32(material))
        for (i in output.lastIndex downTo 1) {
            val j = (random.nextDouble() * (i + 1)).toInt()
            val tmp = output[i]
            output[i] = output[j]
            output[j] = tmp
        }
        return output
    }

    private class Mulberry32(seed: Int) {
        private var state = seed

        fun nextDouble(): Double {
            state += 0x6d2b79f5
            var t = state
            t = (t xor (t ushr 15)) * (t or 1)
            t = t xor (t + (t xor (t ushr 7)) * (t or 61))
            val unsigned = (t xor (t ushr 14)).toUInt().toLong()
            return unsigned / 4294967296.0
        }
    }
}
