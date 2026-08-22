package org.ksrace.senate2026.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.util.concurrent.TimeUnit

/** The outcome of one conditional fetch. */
sealed interface FetchResult {
    /** New body downloaded. */
    data class Fresh(val body: String, val etag: String?) : FetchResult

    /** Server says our cached copy is still current. */
    data object NotModified : FetchResult

    /** Network or server problem; the caller falls back to cache. */
    data class Failed(val reason: String) : FetchResult
}

/**
 * Fetches the collector's static JSON.
 *
 * There is no API here in the usual sense — just conditional GETs of files on a
 * CDN. That is the point of the architecture: no server to run, no keys in the
 * APK, and every device sees byte-identical numbers.
 */
class RaceApi(
    private val baseUrl: String,
    private val client: OkHttpClient = defaultClient(),
) {

    suspend fun fetch(file: DataFile, etag: String? = null): FetchResult =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url(baseUrl.trimEnd('/') + "/" + file.fileName)
                .header("Accept", "application/json")
                .apply { if (etag != null) header("If-None-Match", etag) }
                .build()

            try {
                client.newCall(request).execute().use { response ->
                    when {
                        response.code == 304 -> FetchResult.NotModified
                        response.isSuccessful -> {
                            val body = response.body?.string()
                            if (body.isNullOrBlank()) {
                                FetchResult.Failed("empty response")
                            } else {
                                FetchResult.Fresh(body, response.header("ETag"))
                            }
                        }
                        else -> FetchResult.Failed("HTTP ${response.code}")
                    }
                }
            } catch (e: IOException) {
                FetchResult.Failed(e.message ?: "network unavailable")
            }
        }

    companion object {
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }
}
