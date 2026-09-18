package com.mreader.android.core.repository

/** Current reader grant policy: manifests expose one chapter-scoped token. */
object ReaderTokenPolicy {
    fun choose(chapterToken: String?): String = chapterToken?.trim().orEmpty()
}
