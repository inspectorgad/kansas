package org.ksrace.senate2026.work

import android.content.Context
import android.content.SharedPreferences

/**
 * The small slice of key-value storage the change detector actually needs.
 *
 * [ChangeDetector] used to take a SharedPreferences directly, which made it
 * depend on Android for no good reason and forced its unit test to implement
 * twenty-odd abstract members it never called — a fake that drifted out of step
 * with the platform interface and broke the build rather than catching anything.
 *
 * Depending on this instead keeps the detector pure Kotlin, so its rules are
 * testable without a device, an emulator, or a robolectric shadow.
 */
interface KeyValueStore {
    fun getString(key: String): String?
    fun getStringSet(key: String): Set<String>
    fun getFloat(key: String): Float?
    fun getBoolean(key: String, default: Boolean): Boolean

    fun putString(key: String, value: String)
    fun putStringSet(key: String, value: Set<String>)
    fun putFloat(key: String, value: Float)
    fun putBoolean(key: String, value: Boolean)
}

/** The real implementation, backed by SharedPreferences. */
class PreferenceStore(private val prefs: SharedPreferences) : KeyValueStore {

    override fun getString(key: String): String? = prefs.getString(key, null)

    override fun getStringSet(key: String): Set<String> =
        prefs.getStringSet(key, emptySet()) ?: emptySet()

    override fun getFloat(key: String): Float? =
        if (prefs.contains(key)) prefs.getFloat(key, Float.NaN).takeIf { !it.isNaN() } else null

    override fun getBoolean(key: String, default: Boolean): Boolean =
        prefs.getBoolean(key, default)

    override fun putString(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }

    override fun putStringSet(key: String, value: Set<String>) {
        prefs.edit().putStringSet(key, value).apply()
    }

    override fun putFloat(key: String, value: Float) {
        prefs.edit().putFloat(key, value).apply()
    }

    override fun putBoolean(key: String, value: Boolean) {
        prefs.edit().putBoolean(key, value).apply()
    }

    companion object {
        fun of(context: Context, name: String): PreferenceStore =
            PreferenceStore(context.getSharedPreferences(name, Context.MODE_PRIVATE))
    }
}
