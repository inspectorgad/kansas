package org.ksrace.senate2026.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The published data contract, mirroring the pydantic models in
 * `collector/schemas/`. The two are kept in step by a CI check.
 *
 * Two rules make this safe against a moving contract:
 *
 * Every optional field carries a default. The collector serialises with
 * `exclude_none`, so an absent value means null on the wire, not `"field": null`.
 * A field without a default would throw on a payload that simply omitted it.
 *
 * Timestamps are held as ISO-8601 strings and parsed at the edge where they are
 * displayed. That avoids a custom serializer for every date field, and means a
 * malformed timestamp degrades to "unknown age" rather than failing the whole
 * parse and blanking the screen.
 */

@Serializable
data class CandidatePair(
    val marshall: Double,
    val hamilton: Double,
) {
    /** Positive means Marshall leads. */
    val margin: Double get() = marshall - hamilton
    val leaderId: String get() = if (marshall >= hamilton) CandidateIds.MARSHALL else CandidateIds.HAMILTON
}

object CandidateIds {
    const val MARSHALL = "marshall"
    const val HAMILTON = "hamilton"
}

@Serializable
data class Attribution(
    val name: String,
    val url: String,
    val license: String? = null,
    val note: String? = null,
)

@Serializable
data class Candidate(
    val id: String,
    val name: String,
    val party: String,
    val incumbent: Boolean = false,
    @SerialName("fec_candidate_id") val fecCandidateId: String? = null,
    @SerialName("committee_id") val committeeId: String? = null,
    val website: String? = null,
) {
    /** Surname alone, for the tight spaces where the full name will not fit. */
    val surname: String get() = name.substringAfterLast(' ')
}

@Serializable
data class Rating(
    val source: String,
    val rating: String,
    val lean: String? = null,
    @SerialName("as_of") val asOf: String? = null,
    val url: String? = null,
    val previous: String? = null,
)

// --- race.json ---------------------------------------------------------------

@Serializable
data class RacePayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("election_date") val electionDate: String,
    @SerialName("days_until_election") val daysUntilElection: Int,
    val state: String = "KS",
    val office: String = "U.S. Senate",
    val candidates: List<Candidate> = emptyList(),
    val ratings: List<Rating> = emptyList(),
)

// --- polls.json --------------------------------------------------------------

@Serializable
data class Poll(
    val id: String,
    val pollster: String,
    val sponsor: String? = null,
    val partisan: String? = null,
    @SerialName("start_date") val startDate: String,
    @SerialName("end_date") val endDate: String,
    @SerialName("sample_size") val sampleSize: Int? = null,
    val population: String? = null,
    @SerialName("margin_of_error") val marginOfError: Double? = null,
    val results: CandidatePair,
    val other: Double? = null,
    val undecided: Double? = null,
    val url: String? = null,
    @SerialName("added_at") val addedAt: String? = null,
) {
    val isPartisan: Boolean get() = partisan != null
}

@Serializable
data class AggregatePoint(
    val date: String,
    val marshall: Double,
    val hamilton: Double,
    val margin: Double,
    @SerialName("n_polls") val nPolls: Int,
)

@Serializable
data class Aggregate(
    @SerialName("as_of") val asOf: String,
    val method: String,
    val marshall: Double,
    val hamilton: Double,
    val margin: Double,
    val leader: String,
    val band: Double,
    @SerialName("n_polls_used") val nPollsUsed: Int,
    @SerialName("trend_7d") val trend7d: Double? = null,
    val history: List<AggregatePoint> = emptyList(),
)

@Serializable
data class PollsPayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val polls: List<Poll> = emptyList(),
    val aggregate: Aggregate? = null,
    val attribution: List<Attribution> = emptyList(),
)

// --- markets.json ------------------------------------------------------------

@Serializable
data class Market(
    val platform: String,
    @SerialName("market_id") val marketId: String,
    val title: String? = null,
    val url: String? = null,
    val marshall: Double,
    val hamilton: Double,
    @SerialName("volume_usd") val volumeUsd: Double? = null,
    @SerialName("open_interest") val openInterest: Double? = null,
    @SerialName("last_trade_at") val lastTradeAt: String? = null,
    @SerialName("fetched_at") val fetchedAt: String,
)

@Serializable
data class MarketPoint(
    val t: String,
    val marshall: Double,
    val hamilton: Double,
)

@Serializable
data class Consensus(
    @SerialName("as_of") val asOf: String,
    val marshall: Double,
    val hamilton: Double,
    val platforms: List<String> = emptyList(),
    @SerialName("change_1h") val change1h: Double? = null,
    @SerialName("change_24h") val change24h: Double? = null,
    @SerialName("change_7d") val change7d: Double? = null,
    val history: List<MarketPoint> = emptyList(),
)

@Serializable
data class MarketsPayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val markets: List<Market> = emptyList(),
    val consensus: Consensus? = null,
    val attribution: List<Attribution> = emptyList(),
    val disclaimer: String? = null,
)

// --- finance.json ------------------------------------------------------------

@Serializable
data class CandidateFinance(
    @SerialName("candidate_id") val candidateId: String,
    @SerialName("fec_candidate_id") val fecCandidateId: String? = null,
    @SerialName("committee_id") val committeeId: String? = null,
    @SerialName("committee_name") val committeeName: String? = null,
    @SerialName("coverage_start_date") val coverageStartDate: String? = null,
    @SerialName("coverage_end_date") val coverageEndDate: String? = null,
    @SerialName("total_receipts") val totalReceipts: Double = 0.0,
    @SerialName("total_disbursements") val totalDisbursements: Double = 0.0,
    @SerialName("cash_on_hand") val cashOnHand: Double = 0.0,
    @SerialName("debts_owed") val debtsOwed: Double = 0.0,
    @SerialName("individual_contributions") val individualContributions: Double = 0.0,
    @SerialName("small_dollar_contributions") val smallDollarContributions: Double? = null,
    @SerialName("pac_contributions") val pacContributions: Double = 0.0,
    @SerialName("in_state_amount") val inStateAmount: Double? = null,
    @SerialName("in_state_pct") val inStatePct: Double? = null,
    @SerialName("burn_rate_monthly") val burnRateMonthly: Double? = null,
)

@Serializable
data class IndependentExpenditure(
    val date: String,
    @SerialName("committee_id") val committeeId: String? = null,
    @SerialName("committee_name") val committeeName: String,
    val amount: Double,
    @SerialName("support_oppose") val supportOppose: String,
    @SerialName("candidate_id") val candidateId: String,
    val purpose: String? = null,
    val url: String? = null,
) {
    val supports: Boolean get() = supportOppose.equals("S", ignoreCase = true)
}

@Serializable
data class TopSpender(
    @SerialName("committee_name") val committeeName: String,
    @SerialName("committee_id") val committeeId: String? = null,
    val amount: Double,
    val supports: String? = null,
    val opposes: String? = null,
)

@Serializable
data class OutsideSpending(
    val supporting: Map<String, Double> = emptyMap(),
    val opposing: Map<String, Double> = emptyMap(),
    val total: Double = 0.0,
    @SerialName("top_spenders") val topSpenders: List<TopSpender> = emptyList(),
    val recent: List<IndependentExpenditure> = emptyList(),
)

@Serializable
data class Filing(
    val date: String,
    @SerialName("committee_name") val committeeName: String,
    @SerialName("committee_id") val committeeId: String? = null,
    @SerialName("form_type") val formType: String? = null,
    @SerialName("report_type") val reportType: String? = null,
    @SerialName("coverage_end_date") val coverageEndDate: String? = null,
    @SerialName("total_receipts") val totalReceipts: Double? = null,
    val url: String? = null,
)

@Serializable
data class FinancePayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val cycle: Int = 2026,
    val candidates: Map<String, CandidateFinance> = emptyMap(),
    @SerialName("outside_spending") val outsideSpending: OutsideSpending = OutsideSpending(),
    val filings: List<Filing> = emptyList(),
    val attribution: List<Attribution> = emptyList(),
)

// --- news.json ---------------------------------------------------------------

@Serializable
data class NewsItem(
    val id: String,
    val title: String,
    val source: String,
    val url: String,
    @SerialName("published_at") val publishedAt: String? = null,
    val summary: String? = null,
    val mentions: List<String> = emptyList(),
)

@Serializable
data class NewsPayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val items: List<NewsItem> = emptyList(),
    val attribution: List<Attribution> = emptyList(),
)

// --- results.json ------------------------------------------------------------

@Serializable
data class CandidateResult(
    @SerialName("candidate_id") val candidateId: String,
    val votes: Int = 0,
    val pct: Double = 0.0,
)

@Serializable
data class CountyResult(
    val county: String,
    @SerialName("marshall_votes") val marshallVotes: Int = 0,
    @SerialName("hamilton_votes") val hamiltonVotes: Int = 0,
    @SerialName("other_votes") val otherVotes: Int = 0,
    @SerialName("total_votes") val totalVotes: Int = 0,
    @SerialName("precincts_reporting") val precinctsReporting: Int? = null,
    @SerialName("precincts_total") val precinctsTotal: Int? = null,
    @SerialName("pct_reporting") val pctReporting: Double? = null,
)

@Serializable
data class ResultsPayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val status: String = "pending",
    val statewide: List<CandidateResult> = emptyList(),
    @SerialName("total_votes") val totalVotes: Int = 0,
    @SerialName("precincts_reporting") val precinctsReporting: Int? = null,
    @SerialName("precincts_total") val precinctsTotal: Int? = null,
    @SerialName("pct_reporting") val pctReporting: Double? = null,
    val counties: List<CountyResult> = emptyList(),
    val called: Boolean = false,
    @SerialName("called_for") val calledFor: String? = null,
    @SerialName("last_updated") val lastUpdated: String? = null,
    @SerialName("source_url") val sourceUrl: String? = null,
    val attribution: List<Attribution> = emptyList(),
) {
    val isLive: Boolean get() = status == "live" || status == "final"
}
