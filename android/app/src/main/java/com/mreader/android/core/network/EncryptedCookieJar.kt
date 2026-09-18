package com.mreader.android.core.network

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import org.json.JSONArray
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class EncryptedCookieJar(context: Context, originNamespace: String) : CookieJar {
    private val prefs = context.getSharedPreferences("mreader_cookie_store_v2_$originNamespace", Context.MODE_PRIVATE)
    private val lock = Any()
    private var storedCookies: MutableList<Cookie> = load().toMutableList()

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        synchronized(lock) {
            val now = System.currentTimeMillis()
            storedCookies.removeAll { it.expiresAt <= now }
            for (incoming in cookies) {
                storedCookies.removeAll {
                    it.name == incoming.name && it.domain == incoming.domain && it.path == incoming.path
                }
                if (incoming.expiresAt > now) storedCookies.add(incoming)
            }
            persist(storedCookies)
        }
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> = synchronized(lock) {
        val now = System.currentTimeMillis()
        val before = storedCookies.size
        storedCookies.removeAll { it.expiresAt <= now }
        if (before != storedCookies.size) persist(storedCookies)
        storedCookies.filter { it.matches(url) }
    }

    fun clear() = synchronized(lock) {
        storedCookies.clear()
        prefs.edit().remove(KEY_PAYLOAD).apply()
    }

    private fun load(): List<Cookie> = runCatching {
        val encrypted = prefs.getString(KEY_PAYLOAD, null) ?: return emptyList()
        val plain = decrypt(encrypted)
        val array = JSONArray(plain)
        buildList {
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                val builder = Cookie.Builder()
                    .name(obj.getString("name"))
                    .value(obj.getString("value"))
                    .path(obj.optString("path", "/"))
                val domain = obj.getString("domain")
                if (obj.optBoolean("hostOnly", false)) builder.hostOnlyDomain(domain) else builder.domain(domain)
                if (obj.optBoolean("secure", false)) builder.secure()
                if (obj.optBoolean("httpOnly", false)) builder.httpOnly()
                if (obj.has("expiresAt")) builder.expiresAt(obj.getLong("expiresAt"))
                add(builder.build())
            }
        }.filter { it.expiresAt > System.currentTimeMillis() }
    }.getOrElse {
        prefs.edit().remove(KEY_PAYLOAD).apply()
        emptyList()
    }

    private fun persist(values: List<Cookie>) {
        val array = JSONArray()
        values.forEach { cookie ->
            array.put(JSONObject().apply {
                put("name", cookie.name)
                put("value", cookie.value)
                put("domain", cookie.domain)
                put("path", cookie.path)
                put("expiresAt", cookie.expiresAt)
                put("secure", cookie.secure)
                put("httpOnly", cookie.httpOnly)
                put("hostOnly", cookie.hostOnly)
            })
        }
        prefs.edit().putString(KEY_PAYLOAD, encrypt(array.toString())).apply()
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        )
        return generator.generateKey()
    }

    private fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val payload = cipher.iv + cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(payload, Base64.NO_WRAP)
    }

    private fun decrypt(encoded: String): String {
        val payload = Base64.decode(encoded, Base64.NO_WRAP)
        require(payload.size > IV_BYTES) { "Invalid encrypted cookie payload" }
        val iv = payload.copyOfRange(0, IV_BYTES)
        val ciphertext = payload.copyOfRange(IV_BYTES, payload.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        return cipher.doFinal(ciphertext).toString(Charsets.UTF_8)
    }

    private companion object {
        const val KEY_ALIAS = "mreader.session.cookies.v1"
        const val KEY_PAYLOAD = "cookies"
        const val IV_BYTES = 12
    }
}
