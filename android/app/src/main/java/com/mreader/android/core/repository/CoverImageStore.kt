package com.mreader.android.core.repository

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import com.mreader.android.core.network.MReaderApiAdapter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

/**
 * Small app-owned cover cache.
 *
 * We deliberately avoid a second general-purpose image framework here: covers are
 * simple public WebP/JPEG assets, while protected chapter pages have their own
 * authorization/codec path. This cache keeps those concerns separate and bounded.
 */
class CoverImageStore(context: Context) {
    private val root = File(context.cacheDir, "mreader_covers_v1").apply { mkdirs() }
    private val stripes = Array(16) { Mutex() }
    private val memoryBytes = minOf(24L * MB, maxOf(8L * MB, Runtime.getRuntime().maxMemory() / 16L)).toInt()
    private val memory = object : LruCache<String, Bitmap>(memoryBytes) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.allocationByteCount.coerceAtLeast(1)
    }

    /** Fast main-thread-safe lookup used when rebuilding a screen after navigation. */
    fun peek(url: String): Bitmap? = memory.get(url)?.takeIf { !it.isRecycled }

    suspend fun load(url: String, api: MReaderApiAdapter): Bitmap {
        memory.get(url)?.takeIf { !it.isRecycled }?.let { return it }
        val stripe = stripes[(url.hashCode() and Int.MAX_VALUE) % stripes.size]
        return stripe.withLock {
            memory.get(url)?.takeIf { !it.isRecycled }?.let { return@withLock it }
            val bytes = withContext(Dispatchers.IO) { readDisk(url) }
                ?: api.getBytes(url, MReaderApiAdapter.MAX_COVER_BYTES).bytes.also { downloaded ->
                    withContext(Dispatchers.IO) { writeDisk(url, downloaded) }
                }
            val bitmap = withContext(Dispatchers.Default) { decodeSampled(bytes) }
            memory.put(url, bitmap)
            bitmap
        }
    }

    suspend fun clear() = withContext(Dispatchers.IO) {
        memory.evictAll()
        root.listFiles()?.forEach { it.delete() }
    }

    suspend fun usage(): CacheUsage = withContext(Dispatchers.IO) {
        val files = root.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") }.orEmpty()
        CacheUsage(files.sumOf { it.length() }, files.size)
    }

    private fun readDisk(identity: String): ByteArray? {
        val file = fileFor(identity)
        if (!file.isFile || file.length() <= 0L || file.length() > MAX_ENTRY_BYTES) return null
        file.setLastModified(System.currentTimeMillis())
        return runCatching { file.readBytes() }.getOrNull()
    }

    private fun writeDisk(identity: String, bytes: ByteArray) {
        if (bytes.isEmpty() || bytes.size > MAX_ENTRY_BYTES) return
        runCatching {
            root.mkdirs()
            val target = fileFor(identity)
            val tmp = File.createTempFile(target.nameWithoutExtension, ".tmp", root)
            try {
                tmp.writeBytes(bytes)
                if (!tmp.renameTo(target)) {
                    target.delete()
                    if (!tmp.renameTo(target)) return@runCatching
                }
            } finally {
                if (tmp.exists()) tmp.delete()
            }
            prune()
        }
    }

    private fun decodeSampled(bytes: ByteArray): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) error("Cover image decode failed")
        var sample = 1
        val largest = maxOf(bounds.outWidth, bounds.outHeight)
        while (largest / (sample * 2) >= TARGET_MAX_DIMENSION) sample *= 2
        val options = BitmapFactory.Options().apply {
            inSampleSize = sample
            inPreferredConfig = Bitmap.Config.ARGB_8888
            inScaled = false
        }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
            ?: error("Cover image decode failed")
    }

    private fun fileFor(identity: String): File {
        val digest = MessageDigest.getInstance("SHA-256").digest(identity.toByteArray(Charsets.UTF_8))
        val name = digest.joinToString("") { "%02x".format(it) }
        return File(root, "$name.bin")
    }

    private fun prune() {
        val files = root.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") } ?: return
        var total = files.sumOf { it.length() }
        if (total <= MAX_CACHE_BYTES) return
        for (file in files.sortedBy { it.lastModified() }) {
            if (total <= TARGET_CACHE_BYTES) break
            total -= file.length()
            file.delete()
        }
    }

    private companion object {
        const val MB = 1024L * 1024L
        const val TARGET_MAX_DIMENSION = 768
        const val MAX_ENTRY_BYTES = 8L * MB
        const val MAX_CACHE_BYTES = 64L * MB
        const val TARGET_CACHE_BYTES = 48L * MB
    }
}
