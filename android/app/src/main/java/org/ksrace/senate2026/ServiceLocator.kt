package org.ksrace.senate2026

import android.content.Context
import org.ksrace.senate2026.data.JsonCache
import org.ksrace.senate2026.data.RaceApi
import org.ksrace.senate2026.data.RaceRepository

/**
 * Hand-rolled dependency container.
 *
 * The graph is three objects deep and will stay that way, so a DI framework
 * would add an annotation processor, a version to keep compatible with Kotlin,
 * and build time — for no benefit at this size.
 */
object ServiceLocator {

    @Volatile
    private var repository: RaceRepository? = null

    fun repository(context: Context): RaceRepository =
        repository ?: synchronized(this) {
            repository ?: build(context.applicationContext).also { repository = it }
        }

    private fun build(context: Context) = RaceRepository(
        api = RaceApi(BuildConfig.DATA_BASE_URL),
        cache = JsonCache(context),
    )

    /** Test seam: replace the repository with one wired to fakes. */
    fun overrideForTest(replacement: RaceRepository?) {
        synchronized(this) { repository = replacement }
    }
}
