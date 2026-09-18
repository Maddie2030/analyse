package com.mreader.android.core.settings

import android.content.Context
import android.net.Uri
import com.mreader.android.BuildConfig

data class ServerConfig(
    val baseUrl: String,
    val imageCdnUrl: String = "",
)

class ServerConfigStore(context: Context) {
    private val prefs = context.getSharedPreferences("mreader_server", Context.MODE_PRIVATE)

    // Endpoint policy belongs to the installed build. Old hidden preferences are
    // never consulted, even if the one-time cleanup cannot reach disk.
    private val configuredOrigin = normalizeOrigin(BuildConfig.MREADER_DEFAULT_BASE_URL).also {
        require(BuildConfig.DEBUG || it.startsWith("https://")) { "Release builds require HTTPS." }
    }
    val namespace: String = java.security.MessageDigest.getInstance("SHA-256")
        .digest(configuredOrigin.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it.toInt() and 255) }

    init {
        if (prefs.getInt("origin_policy", 0) < 1) {
            prefs.edit().remove(KEY_BASE_URL).remove(KEY_IMAGE_CDN_URL).putInt("origin_policy", 1).apply()
        }
    }

    fun current(): ServerConfig = ServerConfig(configuredOrigin, "")

    fun validate(baseUrl: String, imageCdnUrl: String = ""): ServerConfig {
        require(normalizeOrigin(baseUrl) == configuredOrigin && imageCdnUrl.isBlank()) {
            "This app uses the gateway configured for its installed build."
        }
        require(BuildConfig.DEBUG || configuredOrigin.startsWith("https://")) { "Release builds require HTTPS." }
        return current()
    }

    private fun normalizeOrigin(value: String): String {
        val trimmed = value.trim().trimEnd('/')
        val uri = Uri.parse(trimmed)
        val scheme = uri.scheme?.lowercase().orEmpty()
        require(scheme == "https" || scheme == "http") { "Server URL must start with https:// or http://" }
        require(!uri.host.isNullOrBlank()) { "Server URL must include a valid host." }
        require(uri.userInfo.isNullOrBlank()) { "Server URL must not contain embedded credentials." }
        require(uri.query.isNullOrBlank() && uri.fragment.isNullOrBlank()) { "Server URL must not contain a query or fragment." }
        require(uri.path.isNullOrBlank() || uri.path == "/") { "MReader gateway URL must point to the site root." }
        val authority = requireNotNull(uri.encodedAuthority)
        return "$scheme://$authority"
    }

    private companion object {
        const val KEY_BASE_URL = "base_url"
        const val KEY_IMAGE_CDN_URL = "image_cdn_url"
    }
}
