package org.ksrace.senate2026.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.ksrace.senate2026.ServiceLocator
import java.util.concurrent.TimeUnit

/**
 * Background refresh.
 *
 * WorkManager's floor for periodic work is 15 minutes, which sits about right
 * against the collector's 20-minute cadence: often enough to catch a new poll
 * within the hour, rare enough not to matter for battery. Conditional GETs mean
 * an unchanged file costs a 304 and nothing else.
 */
class RefreshWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val repository = ServiceLocator.repository(applicationContext)
        val snapshot = try {
            repository.refresh()
        } catch (e: Exception) {
            // Retry with WorkManager's backoff rather than dropping the round.
            return Result.retry()
        }

        if (!snapshot.hasAnyData) return Result.retry()

        val prefs = applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_NOTIFICATIONS_ENABLED, true)) {
            val notifier = Notifier(applicationContext)
            ChangeDetector(prefs).eventsFor(snapshot).forEach(notifier::notify)
        }

        // Every file failing is worth retrying; some failing is normal weather.
        return if (snapshot.problems.size >= snapshot.fetchedAt.size && snapshot.problems.isNotEmpty()) {
            Result.retry()
        } else {
            Result.success()
        }
    }

    companion object {
        const val PREFS = "race-prefs"
        const val KEY_NOTIFICATIONS_ENABLED = "notifications_enabled"
        const val WORK_NAME = "race-refresh"
    }
}

object RefreshScheduler {

    fun ensureScheduled(context: Context) {
        val request = PeriodicWorkRequestBuilder<RefreshWorker>(15, TimeUnit.MINUTES)
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            RefreshWorker.WORK_NAME,
            // KEEP, so relaunching the app does not reset the interval and
            // trigger an immediate extra fetch every time it is opened.
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(RefreshWorker.WORK_NAME)
    }
}
