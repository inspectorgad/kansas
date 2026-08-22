package org.ksrace.senate2026.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.ksrace.senate2026.ServiceLocator
import org.ksrace.senate2026.data.DataFile
import org.ksrace.senate2026.data.RaceRepository
import org.ksrace.senate2026.data.RaceSnapshot

/**
 * Takes only an Application, so androidx's default AndroidViewModelFactory can
 * build it. A second constructor parameter with a default value would compile
 * but blow up at runtime: Kotlin emits the two-argument constructor plus a
 * synthetic bridge, never the single-Application one the factory looks for.
 * Tests substitute the repository through ServiceLocator.overrideForTest.
 */
class RaceViewModel(application: Application) : AndroidViewModel(application) {

    private val repository: RaceRepository = ServiceLocator.repository(application)

    val snapshot: StateFlow<RaceSnapshot> = repository.snapshot

    /**
     * A clock the age labels can recompose against.
     *
     * Without it, "12 min ago" would stay frozen at whatever it read when the
     * screen was composed — a stale label about staleness, which is worse than
     * none.
     */
    private val _now = MutableStateFlow(System.currentTimeMillis())
    val now: StateFlow<Long> = _now.asStateFlow()

    init {
        // Cache first so the app opens with real content, then refresh.
        repository.loadFromCache()
        refresh()
        tickClock()
    }

    fun refresh() {
        viewModelScope.launch { repository.refresh() }
    }

    /**
     * Election night only: poll the results file on a short interval.
     *
     * Gated on results actually being live so the app never runs a 60-second
     * loop on an ordinary day in September.
     */
    fun startResultsPolling() {
        viewModelScope.launch {
            while (isActive) {
                if (!snapshot.value.resultsAreLive) return@launch
                delay(RESULTS_POLL_MILLIS)
                repository.refreshOnly(DataFile.RESULTS)
            }
        }
    }

    private fun tickClock() {
        viewModelScope.launch {
            while (isActive) {
                delay(CLOCK_TICK_MILLIS)
                _now.value = System.currentTimeMillis()
            }
        }
    }

    private companion object {
        const val CLOCK_TICK_MILLIS = 30_000L
        const val RESULTS_POLL_MILLIS = 60_000L
    }
}
