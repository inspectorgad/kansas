package org.ksrace.senate2026.work

import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.format.formatShortDollars
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Decides what in a freshly downloaded snapshot is worth a notification.
 *
 * The bar is deliberately high. A tracker that pings on every 20-minute refresh
 * gets muted within a day, and a muted tracker reports nothing. So: only genuinely
 * new polls, market moves past a threshold, new filings, rating changes, and the
 * one moment that matters most — returns starting to come in.
 *
 * State lives in a KeyValueStore rather than being derived from the data, so a
 * poll that appears, disappears and reappears upstream cannot notify twice.
 */
class ChangeDetector(private val prefs: KeyValueStore) {

    fun eventsFor(snapshot: RaceSnapshot): List<RaceEvent> {
        val events = mutableListOf<RaceEvent>()

        newPolls(snapshot)?.let { events += it }
        marketSwing(snapshot)?.let { events += it }
        newFilings(snapshot)?.let { events += it }
        ratingChange(snapshot)?.let { events += it }
        resultsLive(snapshot)?.let { events += it }

        return events
    }

    private fun newPolls(snapshot: RaceSnapshot): RaceEvent? {
        val polls = snapshot.polls?.polls?.takeIf { it.isNotEmpty() } ?: return null
        val seen = prefs.getStringSet(KEY_SEEN_POLLS)
        val fresh = polls.filter { it.id !in seen }

        // Accumulate, never replace. Overwriting with just the currently visible
        // ids would forget a poll the moment it dropped off the upstream table,
        // and notify again when an editor restored it. Poll counts run to a few
        // dozen a cycle, so the cap is only a runaway guard.
        val remembered = (seen + polls.map { it.id }).let { ids ->
            if (ids.size <= MAX_REMEMBERED_POLLS) ids else ids.take(MAX_REMEMBERED_POLLS).toSet()
        }
        prefs.putStringSet(KEY_SEEN_POLLS, remembered)

        // First run: learn the back catalogue silently rather than announcing it.
        if (seen.isEmpty() || fresh.isEmpty()) return null

        val newest = fresh.first()
        val title = if (fresh.size == 1) "New poll: ${newest.pollster}" else "${fresh.size} new polls"
        val marshall = newest.results.marshall.roundToInt()
        val hamilton = newest.results.hamilton.roundToInt()
        val partisan = if (newest.isPartisan) " (campaign-sponsored)" else ""
        return RaceEvent(
            id = "poll-${newest.id}",
            title = title,
            body = "Marshall $marshall%, Hamilton $hamilton%$partisan",
        )
    }

    private fun marketSwing(snapshot: RaceSnapshot): RaceEvent? {
        val consensus = snapshot.markets?.consensus ?: return null
        val current = consensus.marshall
        val last = prefs.getFloat(KEY_LAST_MARKET)
        prefs.putFloat(KEY_LAST_MARKET, current.toFloat())

        // No prior reading means there is no movement to report, which is not
        // the same as a move from zero.
        if (last == null) return null
        val move = current - last
        if (abs(move) < MARKET_SWING_THRESHOLD) return null

        val direction = if (move > 0) "toward Marshall" else "toward Hamilton"
        val points = (abs(move) * 100).roundToInt()
        return RaceEvent(
            id = "market-${(current * 1000).roundToInt()}",
            title = "Market moved $points points $direction",
            body = "Marshall now ${(current * 100).roundToInt()}% to win. " +
                "This is a betting-market probability, not a vote share.",
        )
    }

    private fun newFilings(snapshot: RaceSnapshot): RaceEvent? {
        val filings = snapshot.finance?.filings?.takeIf { it.isNotEmpty() } ?: return null
        val newest = filings.first()
        val key = "${newest.committeeId}-${newest.date}-${newest.formType}"
        val seen = prefs.getString(KEY_LAST_FILING)
        prefs.putString(KEY_LAST_FILING, key)

        if (seen == null || seen == key) return null
        val amount = newest.totalReceipts?.let { " — ${formatShortDollars(it)} raised" } ?: ""
        return RaceEvent(
            id = "filing-$key",
            title = "New FEC filing: ${newest.committeeName}",
            body = "${newest.formType ?: "Report"} filed ${newest.date}$amount",
        )
    }

    private fun ratingChange(snapshot: RaceSnapshot): RaceEvent? {
        val ratings = snapshot.race?.ratings?.takeIf { it.isNotEmpty() } ?: return null
        val fingerprint = ratings.joinToString("|") { "${it.source}=${it.rating}" }
        val seen = prefs.getString(KEY_LAST_RATINGS)
        prefs.putString(KEY_LAST_RATINGS, fingerprint)

        if (seen == null || seen == fingerprint) return null
        val summary = ratings.joinToString(", ") { "${it.source}: ${it.rating}" }
        return RaceEvent(
            id = "rating-${fingerprint.hashCode()}",
            title = "Race rating changed",
            body = summary,
        )
    }

    private fun resultsLive(snapshot: RaceSnapshot): RaceEvent? {
        if (!snapshot.resultsAreLive) return null
        if (prefs.getBoolean(KEY_RESULTS_ANNOUNCED, false)) return null
        prefs.putBoolean(KEY_RESULTS_ANNOUNCED, true)
        return RaceEvent(
            id = "results-live",
            title = "Results are coming in",
            body = "Kansas has started reporting returns. Tap to follow the count.",
        )
    }

    private companion object {
        const val KEY_SEEN_POLLS = "seen_poll_ids"
        const val KEY_LAST_MARKET = "last_market_marshall"
        const val KEY_LAST_FILING = "last_filing_key"
        const val KEY_LAST_RATINGS = "last_ratings_fingerprint"
        const val KEY_RESULTS_ANNOUNCED = "results_announced"

        /** Five percentage points of implied probability. */
        const val MARKET_SWING_THRESHOLD = 0.05

        const val MAX_REMEMBERED_POLLS = 500
    }
}
