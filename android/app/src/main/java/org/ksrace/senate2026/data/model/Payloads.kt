package org.ksrace.senate2026.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

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
    /**
     * A person typed this rather than a scraper reading it.
     *
     * Every handicapper answers 403 to the collector, so ratings arrive by hand
     * or not at all. A typed value is still worth showing — a move from Lean R to
     * Toss-up is among the more newsworthy things that happens in a race — but it
     * carries a different guarantee from a scraped number and must not look the
     * same. The label is not decoration.
     */
    @SerialName("entered_by_hand") val enteredByHand: Boolean = false,
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
data class MarginBucket(
    val label: String,
    @SerialName("candidate_id") val candidateId: String? = null,
    val low: Double? = null,
    val high: Double? = null,
    val probability: Double,
)

/**
 * The winning margin the market implies, not just who it favours.
 *
 * Built from Kalshi's margin-threshold ladder: each rung prices "will the margin
 * be at least N points", so the gap between adjacent rungs is the chance of
 * landing between them. The bands close to one using a win probability derived
 * from a completely separate market, which is why they are worth showing — two
 * unrelated contracts agreeing is a stronger claim than either alone.
 *
 * [detailedSide] matters for reading the chart. The exchange lists rungs for one
 * party only, so that candidate gets a dozen bands and the other gets one. The
 * asymmetry is in the source, not in the race.
 */
@Serializable
data class MarginDistribution(
    @SerialName("median_margin") val medianMargin: Double? = null,
    val leader: String? = null,
    val buckets: List<MarginBucket> = emptyList(),
    val rungs: Int = 0,
    @SerialName("detailed_side") val detailedSide: String? = null,
    val note: String,
) {
    val hasBands: Boolean get() = buckets.size >= 2

    /** The likeliest single band, for a direct label rather than labelling all. */
    val modal: MarginBucket? get() = buckets.maxByOrNull { it.probability }
}

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
    val margin: MarginDistribution? = null,
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
    @SerialName("party_contributions") val partyContributions: Double = 0.0,
    /** Moved in from another committee the candidate controls, e.g. a prior campaign. */
    @SerialName("transfers_in") val transfersIn: Double = 0.0,
    @SerialName("other_receipts") val otherReceipts: Double = 0.0,
    @SerialName("affiliated_committees") val affiliatedCommittees: List<AffiliatedCommittee> =
        emptyList(),
    @SerialName("in_state_amount") val inStateAmount: Double? = null,
    @SerialName("in_state_pct") val inStatePct: Double? = null,
    @SerialName("burn_rate_monthly") val burnRateMonthly: Double? = null,
    val donors: DonorDetail? = null,
)

@Serializable
data class AffiliatedCommittee(
    @SerialName("committee_id") val committeeId: String,
    val name: String,
    val designation: String? = null,
    @SerialName("designation_full") val designationFull: String? = null,
    @SerialName("committee_type") val committeeType: String? = null,
    val receipts: Double? = null,
    val disbursements: Double? = null,
    @SerialName("cash_on_hand") val cashOnHand: Double? = null,
)

@Serializable
data class CommitteeDonor(
    val name: String,
    @SerialName("committee_id") val committeeId: String? = null,
    val amount: Double,
    val gifts: Int = 1,
    /** "pac", "party", or "transfer" — the FEC line the money was filed on. */
    val kind: String,
) {
    /** Not a donation: money the candidate moved in from a committee of their own. */
    val isTransfer: Boolean get() = kind == "transfer"
}

@Serializable
data class DonorGroup(
    val label: String,
    val amount: Double,
    val donors: Int = 0,
)

@Serializable
data class SizeBucket(
    val label: String,
    val amount: Double,
    val count: Int = 0,
)

@Serializable
data class LargeDonor(
    val name: String,
    val city: String? = null,
    val state: String? = null,
    val employer: String? = null,
    val occupation: String? = null,
    val amount: Double,
    val gifts: Int = 1,
) {
    /** "Wichita, KS" — or whichever half of it disclosure actually carried. */
    val place: String?
        get() = listOfNotNull(city?.takeIf { it.isNotBlank() }, state?.takeIf { it.isNotBlank() })
            .takeIf { it.isNotEmpty() }
            ?.joinToString(", ")
}

/**
 * Who funds a campaign, as far as federal disclosure goes.
 *
 * [itemizedNote] is not decoration. Donors are only named above $200 for the
 * cycle, so every list here describes a campaign's larger givers rather than its
 * typical one, and it under-represents a small-dollar campaign the most. The
 * caption travels with the data so no screen can render these lists without it.
 */
@Serializable
data class DonorDetail(
    val threshold: Double = 1000.0,
    @SerialName("itemized_note") val itemizedNote: String,
    @SerialName("large_donors") val largeDonors: List<LargeDonor> = emptyList(),
    @SerialName("top_employers") val topEmployers: List<DonorGroup> = emptyList(),
    @SerialName("top_occupations") val topOccupations: List<DonorGroup> = emptyList(),
    @SerialName("top_cities") val topCities: List<DonorGroup> = emptyList(),
    @SerialName("size_buckets") val sizeBuckets: List<SizeBucket> = emptyList(),
    @SerialName("itemized_total") val itemizedTotal: Double? = null,
    @SerialName("unitemized_total") val unitemizedTotal: Double? = null,
    @SerialName("large_donor_coverage") val largeDonorCoverage: String? = null,
    @SerialName("committee_donors") val committeeDonors: List<CommitteeDonor> = emptyList(),
    @SerialName("committee_donor_note") val committeeDonorNote: String = "",
) {
    val hasAnything: Boolean
        get() = largeDonors.isNotEmpty() || topEmployers.isNotEmpty() ||
            topOccupations.isNotEmpty() || sizeBuckets.isNotEmpty() ||
            committeeDonors.isNotEmpty()
}

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
    /** "news" for reporting, "official" for a government release. */
    val kind: String = "news",
) {
    /**
     * A press release from the incumbent's Senate office, rather than reporting.
     *
     * These are real coverage of the race and belong in the feed, but they are the
     * officeholder's own words, and the challenger holds no office and so has no
     * equivalent. Showing them unlabelled beside a newsroom's reporting would let
     * one side's press shop read as journalism.
     */
    val isOfficial: Boolean get() = kind == "official"
}

@Serializable
data class NewsPayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val items: List<NewsItem> = emptyList(),
    val attribution: List<Attribution> = emptyList(),
)


// --- ads.json ----------------------------------------------------------------

@Serializable
data class AdFiling(
    val id: String,
    val station: String,
    val market: String? = null,
    val advertiser: String,
    /** candidate id the buy helps, or null when it could not be justified. */
    val side: String? = null,
    @SerialName("is_outside_group") val isOutsideGroup: Boolean = false,
    val amount: Double? = null,
    @SerialName("flight_start") val flightStart: String? = null,
    @SerialName("flight_end") val flightEnd: String? = null,
    @SerialName("filed_at") val filedAt: String? = null,
    val url: String? = null,
)

@Serializable
data class WeeklySpend(
    @SerialName("week_start") val weekStart: String,
    val marshall: Double = 0.0,
    val hamilton: Double = 0.0,
    val outside: Double = 0.0,
) {
    val total: Double get() = marshall + hamilton + outside
}

@Serializable
data class MarketSpend(
    val market: String,
    val marshall: Double = 0.0,
    val hamilton: Double = 0.0,
    val outside: Double = 0.0,
) {
    val total: Double get() = marshall + hamilton + outside
}

@Serializable
data class BroadcastAds(
    @SerialName("total_by_side") val totalBySide: Map<String, Double> = emptyMap(),
    @SerialName("by_week") val byWeek: List<WeeklySpend> = emptyList(),
    @SerialName("by_market") val byMarket: List<MarketSpend> = emptyList(),
    val filings: List<AdFiling> = emptyList(),
) {
    val total: Double get() = totalBySide.values.sum()
}

@Serializable
data class DigitalAds(
    val available: Boolean = false,
    @SerialName("unavailable_reason") val unavailableReason: String? = null,
    @SerialName("total_by_side") val totalBySide: Map<String, Double> = emptyMap(),
    @SerialName("by_page") val byPage: List<JsonObject> = emptyList(),
)

@Serializable
data class AdsPayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val broadcast: BroadcastAds = BroadcastAds(),
    val digital: DigitalAds = DigitalAds(),
    val attribution: List<Attribution> = emptyList(),
)

// --- ground.json -------------------------------------------------------------

@Serializable
data class CountyRegistration(
    val county: String,
    val republican: Int = 0,
    val democrat: Int = 0,
    val unaffiliated: Int = 0,
    val libertarian: Int = 0,
    val total: Int = 0,
) {
    /** Positive means more registered Republicans than Democrats. */
    val partyGap: Int get() = republican - democrat
}

@Serializable
data class Registration(
    @SerialName("as_of") val asOf: String? = null,
    val statewide: CountyRegistration? = null,
    @SerialName("by_county") val byCounty: List<CountyRegistration> = emptyList(),
    @SerialName("source_url") val sourceUrl: String? = null,
)

@Serializable
data class CountyAdvance(
    val county: String,
    @SerialName("mail_ballots_sent") val mailBallotsSent: Int? = null,
    @SerialName("mail_ballots_returned") val mailBallotsReturned: Int? = null,
    @SerialName("in_person_votes") val inPersonVotes: Int? = null,
    @SerialName("total_advance") val totalAdvance: Int? = null,
    @SerialName("party_breakdown") val partyBreakdown: Map<String, Int>? = null,
    @SerialName("as_of") val asOf: String? = null,
    @SerialName("source_url") val sourceUrl: String? = null,
)

@Serializable
data class AdvanceBallots(
    @SerialName("coverage_note") val coverageNote: String = "",
    @SerialName("counties_covered") val countiesCovered: List<String> = emptyList(),
    val counties: List<CountyAdvance> = emptyList(),
)

@Serializable
data class GroundPayload(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    @SerialName("generated_at") val generatedAt: String,
    val registration: Registration = Registration(),
    @SerialName("advance_ballots") val advanceBallots: AdvanceBallots = AdvanceBallots(),
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
