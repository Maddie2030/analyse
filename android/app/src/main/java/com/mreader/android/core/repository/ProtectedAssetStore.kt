package com.mreader.android.core.repository

import android.content.Context
import android.util.LruCache
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

/**
 * Encoded protected-page bytes only. Decoded bitmaps are never written to disk.
 *
 * Signed-in readers may persist encoded chapter bytes for up to 24 hours. Guests
 * only use the bounded in-memory layer, so they still benefit from the reader
 * prefetch window without receiving persistent chapter-download privileges.
 *
 * The in-memory layer carries the same timestamp as the persistent object. That
 * matters for a long-running app process: a page whose disk object has expired
 * must not remain readable indefinitely just because its bytes are still in RAM.
 */
class ProtectedAssetStore(context: Context) {
    private val root = File(context.cacheDir, "mreader_protected_pages_v1").apply { mkdirs() }

    private data class MemoryEntry(
        val bytes: ByteArray,
        val savedAtMillis: Long,
        val persistent: Boolean,
    )

    private val memory = object : LruCache<String, MemoryEntry>(MEMORY_CACHE_BYTES.toInt()) {
        override fun sizeOf(key: String, value: MemoryEntry): Int = value.bytes.size.coerceAtLeast(1)
    }

    suspend fun read(identity: String, persistent: Boolean = true): ByteArray? = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        val hot = synchronized(memory) { memory.get(identity) }
        if (hot != null) {
            if (now - hot.savedAtMillis > RETENTION_MS) {
                synchronized(memory) { memory.remove(identity) }
                if (hot.persistent) fileFor(identity).delete()
            } else {
                if (persistent && !hot.persistent) {
                    // A guest may have already fetched this encoded page into RAM and
                    // then signed in. Promote those same bytes to app cache rather than
                    // downloading them again, and start the 24-hour persistent window
                    // from the promotion/write time.
                    val promotedAt = System.currentTimeMillis()
                    if (writeDisk(identity, hot.bytes, promotedAt)) {
                        synchronized(memory) {
                            memory.put(identity, MemoryEntry(hot.bytes, promotedAt, persistent = true))
                        }
                    }
                }
                return@withContext hot.bytes
            }
        }

        if (!persistent) return@withContext null
        val file = fileFor(identity)
        if (!file.isFile || file.length() <= 0L || file.length() > MAX_ENTRY_BYTES) return@withContext null
        val savedAt = file.lastModified()
        if (now - savedAt > RETENTION_MS) {
            file.delete()
            return@withContext null
        }
        runCatching { file.readBytes() }.getOrNull()?.also { bytes ->
            // Reading does not touch lastModified: retention is measured from the
            // most recent download/write, not extended on every page view.
            synchronized(memory) { memory.put(identity, MemoryEntry(bytes, savedAt, persistent = true)) }
        }
    }

    suspend fun write(identity: String, bytes: ByteArray, persistent: Boolean = true) = withContext(Dispatchers.IO) {
        if (bytes.isEmpty() || bytes.size > MAX_ENTRY_BYTES) return@withContext
        val savedAt = System.currentTimeMillis()
        if (!persistent) {
            synchronized(memory) { memory.put(identity, MemoryEntry(bytes, savedAt, persistent = false)) }
            return@withContext
        }

        // Mark the RAM entry persistent only when the atomic disk write actually
        // succeeds. A storage-pressure/write failure must not make Settings or the
        // reader believe a chapter page will survive process death.
        val persisted = writeDisk(identity, bytes, savedAt)
        synchronized(memory) { memory.put(identity, MemoryEntry(bytes, savedAt, persistent = persisted)) }
    }

    suspend fun evict(identity: String) = withContext(Dispatchers.IO) {
        synchronized(memory) { memory.remove(identity) }
        fileFor(identity).delete()
    }

    suspend fun clear() = withContext(Dispatchers.IO) {
        synchronized(memory) { memory.evictAll() }
        root.listFiles()?.forEach { it.delete() }
    }

    suspend fun usage(): CacheUsage = withContext(Dispatchers.IO) {
        pruneExpired()
        val files = root.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") }.orEmpty()
        CacheUsage(files.sumOf { it.length() }, files.size)
    }

    private fun writeDisk(identity: String, bytes: ByteArray, savedAt: Long): Boolean = runCatching {
        root.mkdirs()
        val target = fileFor(identity)
        val tmp = File.createTempFile(target.nameWithoutExtension, ".tmp", root)
        try {
            tmp.writeBytes(bytes)
            if (!tmp.renameTo(target)) {
                target.delete()
                if (!tmp.renameTo(target)) return@runCatching false
            }
        } finally {
            if (tmp.exists()) tmp.delete()
        }
        target.setLastModified(savedAt)
        prune()
        true
    }.getOrDefault(false)

    private fun fileFor(identity: String): File {
        val digest = MessageDigest.getInstance("SHA-256").digest(identity.toByteArray(Charsets.UTF_8))
        val name = digest.joinToString("") { "%02x".format(it) }
        return File(root, "$name.bin")
    }

    private fun pruneExpired() {
        val cutoff = System.currentTimeMillis() - RETENTION_MS
        root.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") }?.forEach { file ->
            if (file.lastModified() < cutoff) file.delete()
        }
        val expiredKeys = mutableListOf<String>()
        val now = System.currentTimeMillis()
        synchronized(memory) {
            // LruCache has no iterator, so snapshot() is the supported inspection path.
            for ((key, entry) in memory.snapshot()) {
                if (now - entry.savedAtMillis > RETENTION_MS) expiredKeys += key
            }
            expiredKeys.forEach { key -> memory.remove(key) }
        }
    }

    private fun prune() {
        pruneExpired()
        val files = root.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") } ?: return
        var total = files.sumOf { it.length() }
        if (total <= MAX_CACHE_BYTES) return
        for (file in files.sortedBy { it.lastModified() }) {
            if (total <= TARGET_CACHE_BYTES) break
            total -= file.length()
            file.delete()
        }

        // Disk LRU eviction must also update the RAM bookkeeping. The bytes may
        // stay hot for the current process, but they are no longer process-durable
        // and must be eligible for promotion/write on the next persistent read.
        synchronized(memory) {
            val demotions = memory.snapshot()
                .filter { (identity, entry) -> entry.persistent && !fileFor(identity).isFile }
            for ((identity, entry) in demotions) {
                memory.put(identity, entry.copy(persistent = false))
            }
        }
    }

    private companion object {
        const val RETENTION_MS = 24L * 60L * 60L * 1000L
        const val MAX_ENTRY_BYTES = 32L * 1024L * 1024L
        const val MAX_CACHE_BYTES = 256L * 1024L * 1024L
        const val TARGET_CACHE_BYTES = 192L * 1024L * 1024L
        const val MEMORY_CACHE_BYTES = 32L * 1024L * 1024L
    }
}
