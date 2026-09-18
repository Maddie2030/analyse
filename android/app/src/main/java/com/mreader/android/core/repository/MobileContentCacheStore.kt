package com.mreader.android.core.repository

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/**
 * Small disk cache for public/mobile metadata used to make tab and reader -> browse
 * transitions instantaneous. Network data is still revalidated in the background;
 * cached data is never treated as permanently authoritative.
 */
class MobileContentCacheStore(
    context: Context,
    namespace: String = "mreader_content_v1",
) {
    private val root = File(context.cacheDir, namespace).apply { mkdirs() }
    private data class MemoryEntry(val payload: String, val savedAt: Long)
    private val memory = LinkedHashMap<String, MemoryEntry>(32, 0.75f, true)

    suspend fun read(key: String): String? = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        synchronized(memory) {
            memory[key]?.let { cached ->
                if (now - cached.savedAt <= RETENTION_MS) return@withContext cached.payload
                memory.remove(key)
            }
        }
        val file = fileFor(key)
        if (!file.isFile || file.length() <= 0L || file.length() > MAX_ENTRY_BYTES) return@withContext null
        if (System.currentTimeMillis() - file.lastModified() > RETENTION_MS) {
            file.delete()
            return@withContext null
        }
        runCatching {
            val envelope = JSONObject(file.readText())
            val savedAt = envelope.optLong("saved_at", file.lastModified())
            if (System.currentTimeMillis() - savedAt > RETENTION_MS) {
                file.delete()
                null
            } else {
                envelope.getString("payload").also { payload ->
                    synchronized(memory) {
                        memory[key] = MemoryEntry(payload, savedAt)
                        trimMemory()
                    }
                }
            }
        }.getOrNull()
    }

    suspend fun write(key: String, payload: String) = withContext(Dispatchers.IO) {
        if (payload.isBlank() || payload.toByteArray().size > MAX_ENTRY_BYTES) return@withContext
        val savedAt = System.currentTimeMillis()
        synchronized(memory) {
            memory[key] = MemoryEntry(payload, savedAt)
            trimMemory()
        }
        runCatching {
            root.mkdirs()
            val target = fileFor(key)
            val tmp = File.createTempFile(target.nameWithoutExtension, ".tmp", root)
            try {
                tmp.writeText(
                    JSONObject()
                        .put("saved_at", savedAt)
                        .put("payload", payload)
                        .toString()
                )
                if (!tmp.renameTo(target)) {
                    target.delete()
                    tmp.renameTo(target)
                }
            } finally {
                if (tmp.exists()) tmp.delete()
            }
            prune()
        }
    }

    suspend fun clear() = withContext(Dispatchers.IO) {
        synchronized(memory) { memory.clear() }
        root.listFiles()?.forEach { it.delete() }
    }

    suspend fun usage(): CacheUsage = withContext(Dispatchers.IO) {
        pruneExpired()
        val files = root.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") }.orEmpty()
        CacheUsage(files.sumOf { it.length() }, files.size)
    }


    private fun trimMemory() {
        while (memory.size > MAX_MEMORY_ENTRIES) {
            val eldest = memory.entries.iterator()
            if (!eldest.hasNext()) break
            eldest.next()
            eldest.remove()
        }
    }

    private fun fileFor(key: String): File {
        val digest = MessageDigest.getInstance("SHA-256").digest(key.toByteArray(Charsets.UTF_8))
        return File(root, digest.joinToString("") { "%02x".format(it) } + ".json")
    }

    private fun pruneExpired() {
        val now = System.currentTimeMillis()
        root.listFiles()?.filter { it.isFile }?.forEach { file ->
            if (now - file.lastModified() > RETENTION_MS) file.delete()
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
    }

    private companion object {
        const val RETENTION_MS = 24L * 60L * 60L * 1000L
        const val MAX_ENTRY_BYTES = 4L * 1024L * 1024L
        const val MAX_CACHE_BYTES = 24L * 1024L * 1024L
        const val TARGET_CACHE_BYTES = 18L * 1024L * 1024L
        const val MAX_MEMORY_ENTRIES = 48
    }
}

data class CacheUsage(val bytes: Long, val entries: Int)
