package com.mreader.android.core.repository

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.mreader.android.core.model.User
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Small encrypted snapshot of the last server-verified account identity.
 *
 * This is not an authentication credential: the encrypted session cookie remains
 * authoritative. The snapshot only lets account-scoped local content render while
 * the gateway is temporarily unreachable. A real profile 401 clears it.
 */
class EncryptedUserSnapshotStore(context: Context, originNamespace: String) {
    private val prefs = context.getSharedPreferences("mreader_user_snapshot_v2_$originNamespace", Context.MODE_PRIVATE)

    fun read(): User? = runCatching {
        val encoded = prefs.getString(KEY_PAYLOAD, null) ?: return null
        val obj = JSONObject(decrypt(encoded))
        User(
            id = obj.getString("id"),
            username = obj.getString("username"),
            email = obj.optString("email"),
            role = obj.optString("role", "user"),
            avatarKey = obj.optString("avatar_key", "skull"),
        )
    }.getOrElse {
        clear()
        null
    }

    fun write(user: User) {
        val payload = JSONObject()
            .put("id", user.id)
            .put("username", user.username)
            .put("email", user.email)
            .put("role", user.role)
            .put("avatar_key", user.avatarKey)
            .toString()
        prefs.edit().putString(KEY_PAYLOAD, encrypt(payload)).apply()
    }

    fun clear() {
        prefs.edit().remove(KEY_PAYLOAD).apply()
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
        require(payload.size > IV_BYTES) { "Invalid encrypted user snapshot" }
        val iv = payload.copyOfRange(0, IV_BYTES)
        val ciphertext = payload.copyOfRange(IV_BYTES, payload.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        return cipher.doFinal(ciphertext).toString(Charsets.UTF_8)
    }

    private companion object {
        const val KEY_ALIAS = "mreader.user.snapshot.v1"
        const val KEY_PAYLOAD = "profile"
        const val IV_BYTES = 12
    }
}
