package org.ksrace.senate2026.data

/**
 * The files the collector publishes. Names must match `FILES` in
 * `collector/schemas/__init__.py`; a CI check holds the two lists in step.
 */
enum class DataFile(val fileName: String) {
    RACE("race.json"),
    POLLS("polls.json"),
    MARKETS("markets.json"),
    FINANCE("finance.json"),
    NEWS("news.json"),
    ADS("ads.json"),
    GROUND("ground.json"),
    RESULTS("results.json"),
    ;

    companion object {
        /** The files the app's four v1 screens actually need. */
        val core = listOf(RACE, POLLS, MARKETS, FINANCE, NEWS, RESULTS)
    }
}
