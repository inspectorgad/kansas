package org.ksrace.senate2026.data

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.json.Json
import org.ksrace.senate2026.data.model.AdsPayload
import org.ksrace.senate2026.data.model.FinancePayload
import org.ksrace.senate2026.data.model.GroundPayload
import org.ksrace.senate2026.data.model.MarketsPayload
import org.ksrace.senate2026.data.model.NewsPayload
import org.ksrace.senate2026.data.model.PollsPayload
import org.ksrace.senate2026.data.model.RacePayload
import org.ksrace.senate2026.data.model.ResultsPayload

/**
 * Everything the UI reads, plus how old it is and what went wrong.
 *
 * Age and failure are first-class rather than hidden, because the honest
 * failure mode for an election tracker is "here is the last number and here is
 * how old it is", never a fresh-looking wrong number.
 */
data class RaceSnapshot(
    val race: RacePayload? = null,
    val polls: PollsPayload? = null,
    val markets: MarketsPayload? = null,
    val finance: FinancePayload? = null,
    val news: NewsPayload? = null,
    val ads: AdsPayload? = null,
    val ground: GroundPayload? = null,
    val results: ResultsPayload? = null,
    /** Epoch millis when each file was last written to cache. */
    val fetchedAt: Map<DataFile, Long> = emptyMap(),
    /** Why a file could not be refreshed this round, if it could not. */
    val problems: Map<DataFile, String> = emptyMap(),
    val loading: Boolean = false,
) {
    val hasAnyData: Boolean
        get() = race != null || polls != null || markets != null || finance != null || news != null

    /** True once returns are actually flowing on election night. */
    val resultsAreLive: Boolean get() = results?.isLive == true

    fun ageMillis(file: DataFile, now: Long): Long? = fetchedAt[file]?.let { now - it }
}

class RaceRepository(
    private val api: RaceApi,
    private val cache: JsonCache,
) {
    private val json = Json {
        ignoreUnknownKeys = true // a new contract field must not break an old app
        isLenient = false
        explicitNulls = false
    }

    private val _snapshot = MutableStateFlow(RaceSnapshot())
    val snapshot: StateFlow<RaceSnapshot> = _snapshot.asStateFlow()

    /** Populate from cache without touching the network, for an instant cold start. */
    fun loadFromCache() {
        val bodies = DataFile.core.mapNotNull { file -> cache.read(file)?.let { file to it } }.toMap()
        _snapshot.update { current -> current.applyBodies(bodies, cache) }
    }

    /**
     * Conditionally refresh every core file.
     *
     * A file that fails keeps its cached value and records the reason; one
     * unreachable source must not blank the rest of the app.
     */
    suspend fun refresh(): RaceSnapshot {
        _snapshot.update { it.copy(loading = true) }

        val bodies = mutableMapOf<DataFile, String>()
        val problems = mutableMapOf<DataFile, String>()

        for (file in DataFile.core) {
            when (val result = api.fetch(file, cache.etag(file))) {
                is FetchResult.Fresh -> {
                    cache.write(file, result.body, result.etag)
                    bodies[file] = result.body
                }
                FetchResult.NotModified -> cache.read(file)?.let { bodies[file] = it }
                is FetchResult.Failed -> {
                    cache.read(file)?.let { bodies[file] = it }
                    problems[file] = result.reason
                }
            }
        }

        val updated = _snapshot.updateAndGetCompat { current ->
            current.applyBodies(bodies, cache).copy(problems = problems, loading = false)
        }
        return updated
    }

    /** Refresh a single file. Used by the election-night fast poll. */
    suspend fun refreshOnly(file: DataFile) {
        val result = api.fetch(file, cache.etag(file))
        val body = when (result) {
            is FetchResult.Fresh -> result.body.also { cache.write(file, it, result.etag) }
            FetchResult.NotModified -> cache.read(file)
            is FetchResult.Failed -> {
                _snapshot.update { it.copy(problems = it.problems + (file to result.reason)) }
                return
            }
        } ?: return

        _snapshot.update { current ->
            current.applyBodies(mapOf(file to body), cache).copy(problems = current.problems - file)
        }
    }

    private fun RaceSnapshot.applyBodies(
        bodies: Map<DataFile, String>,
        cache: JsonCache,
    ): RaceSnapshot {
        var next = this
        for ((file, body) in bodies) {
            next = when (file) {
                DataFile.RACE -> next.copy(race = decode<RacePayload>(body) ?: next.race)
                DataFile.POLLS -> next.copy(polls = decode<PollsPayload>(body) ?: next.polls)
                DataFile.MARKETS -> next.copy(markets = decode<MarketsPayload>(body) ?: next.markets)
                DataFile.FINANCE -> next.copy(finance = decode<FinancePayload>(body) ?: next.finance)
                DataFile.NEWS -> next.copy(news = decode<NewsPayload>(body) ?: next.news)
                DataFile.ADS -> next.copy(ads = decode<AdsPayload>(body) ?: next.ads)
                DataFile.GROUND -> next.copy(ground = decode<GroundPayload>(body) ?: next.ground)
                DataFile.RESULTS -> next.copy(results = decode<ResultsPayload>(body) ?: next.results)
            }
        }
        val stamps = DataFile.core.mapNotNull { file -> cache.fetchedAt(file)?.let { file to it } }.toMap()
        return next.copy(fetchedAt = stamps)
    }

    /**
     * Decode one file, returning null on malformed JSON.
     *
     * A corrupt or half-written file must cost us that one file, not the whole
     * snapshot — the previously decoded value stays in place.
     */
    private inline fun <reified T> decode(body: String): T? =
        runCatching { json.decodeFromString<T>(body) }.getOrNull()

    /**
     * `MutableStateFlow.updateAndGet` exists, but spelling it out keeps this
     * readable next to the `update` calls above and returns the applied value.
     */
    private inline fun MutableStateFlow<RaceSnapshot>.updateAndGetCompat(
        transform: (RaceSnapshot) -> RaceSnapshot,
    ): RaceSnapshot {
        while (true) {
            val current = value
            val next = transform(current)
            if (compareAndSet(current, next)) return next
        }
    }
}
