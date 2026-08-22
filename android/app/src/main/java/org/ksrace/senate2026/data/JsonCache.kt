package org.ksrace.senate2026.data

import android.content.Context
import java.io.File

/**
 * On-disk cache of the last successfully downloaded copy of each file.
 *
 * This is the whole offline story. The payloads are small static JSON, so a
 * database would buy nothing over the filesystem, and skipping one removes a
 * schema-migration surface that would otherwise need maintaining for the life of
 * the app.
 *
 * ETags are stored alongside the body so refreshes can be conditional: the
 * collector runs every 20 minutes but most files change far less often, and a
 * 304 costs nothing.
 */
class JsonCache(context: Context) {

    private val root = File(context.filesDir, DIRECTORY).apply { mkdirs() }

    fun read(file: DataFile): String? {
        val body = File(root, file.fileName)
        return if (body.isFile) runCatching { body.readText() }.getOrNull() else null
    }

    fun write(file: DataFile, body: String, etag: String?) {
        runCatching {
            File(root, file.fileName).writeText(body)
            val tag = File(root, "${file.fileName}.etag")
            if (etag != null) tag.writeText(etag) else tag.delete()
        }
    }

    fun etag(file: DataFile): String? {
        val tag = File(root, "${file.fileName}.etag")
        return if (tag.isFile) runCatching { tag.readText() }.getOrNull()?.takeIf { it.isNotBlank() } else null
    }

    /** When we last wrote this file, as epoch millis, or null if we never have. */
    fun fetchedAt(file: DataFile): Long? =
        File(root, file.fileName).takeIf { it.isFile }?.lastModified()

    fun clear() {
        root.listFiles()?.forEach { it.delete() }
    }

    private companion object {
        const val DIRECTORY = "race-cache"
    }
}
