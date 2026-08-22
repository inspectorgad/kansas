package org.ksrace.senate2026.data

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ksrace.senate2026.data.model.CandidateIds
import org.ksrace.senate2026.data.model.AdsPayload
import org.ksrace.senate2026.data.model.FinancePayload
import org.ksrace.senate2026.data.model.GroundPayload
import org.ksrace.senate2026.data.model.MarketsPayload
import org.ksrace.senate2026.data.model.NewsPayload
import org.ksrace.senate2026.data.model.PollsPayload
import org.ksrace.senate2026.data.model.RacePayload
import org.ksrace.senate2026.data.model.ResultsPayload

/**
 * Cross-language contract tests.
 *
 * The fixtures in `src/test/resources/contract/` are not hand-written JSON —
 * they are produced by the Python collector's own publisher, which validates
 * every file against its pydantic model before writing. So if these tests pass,
 * the Kotlin DTOs and the pydantic schemas genuinely agree, and the usual way
 * this breaks (someone adds a field on one side only) fails here.
 */
class ContractParsingTest {

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    private fun load(name: String): String =
        checkNotNull(javaClass.getResourceAsStream("/contract/$name")) {
            "missing contract fixture $name"
        }.bufferedReader().readText()

    @Test
    fun `parses race`() {
        val race = json.decodeFromString<RacePayload>(load("race.json"))
        assertEquals(1, race.schemaVersion)
        assertEquals("2026-11-03", race.electionDate)
        assertEquals(2, race.candidates.size)

        val marshall = race.candidates.single { it.id == CandidateIds.MARSHALL }
        assertEquals("Roger Marshall", marshall.name)
        assertEquals("R", marshall.party)
        assertTrue("Marshall is the incumbent", marshall.incumbent)
        assertEquals("Marshall", marshall.surname)

        val hamilton = race.candidates.single { it.id == CandidateIds.HAMILTON }
        assertEquals("D", hamilton.party)
        assertFalse("Hamilton is the challenger", hamilton.incumbent)
        // The challenger has no FEC id in this fixture; an absent optional must
        // decode to null rather than throwing.
        assertNull(hamilton.fecCandidateId)

        assertEquals("Cook Political Report", race.ratings.single().source)
    }

    @Test
    fun `parses polls and the aggregate`() {
        val polls = json.decodeFromString<PollsPayload>(load("polls.json"))
        assertEquals(6, polls.polls.size)

        val aggregate = requireNotNull(polls.aggregate) { "polls.json must carry an aggregate" }
        assertTrue("leader is a known candidate", aggregate.leader in listOf("marshall", "hamilton"))
        assertTrue("band is positive", aggregate.band > 0)
        assertTrue("history is populated", aggregate.history.size > 30)
        assertTrue("method is documented", aggregate.method.isNotBlank())

        // Margin must agree with the shares it was computed from.
        assertEquals(aggregate.marshall - aggregate.hamilton, aggregate.margin, 0.02)

        // Attribution survives the round trip: Wikipedia is CC BY-SA and the app
        // has to be able to say so.
        assertEquals("CC BY-SA 4.0", polls.attribution.first().license)
    }

    @Test
    fun `parses a poll with no reported sample size`() {
        val polls = json.decodeFromString<PollsPayload>(load("polls.json"))
        val cygnal = polls.polls.single { it.pollster == "Cygnal" }
        assertNull(cygnal.sampleSize)
        assertNull(cygnal.marginOfError)
        assertTrue("known partisan pollster is flagged", cygnal.isPartisan)
    }

    @Test
    fun `parses a campaign-sponsored poll`() {
        val polls = json.decodeFromString<PollsPayload>(load("polls.json"))
        val gbao = polls.polls.single { it.pollster == "GBAO" }
        assertEquals("for Hamilton campaign", gbao.sponsor)
        assertEquals("D", gbao.partisan)
        assertTrue(gbao.isPartisan)
    }

    @Test
    fun `parses markets and never yields a pair that fails to sum to one`() {
        val markets = json.decodeFromString<MarketsPayload>(load("markets.json"))
        val market = markets.markets.single()
        assertEquals("kalshi", market.platform)
        assertEquals(1.0, market.marshall + market.hamilton, 0.001)

        val consensus = markets.consensus!!
        assertEquals(1.0, consensus.marshall + consensus.hamilton, 0.001)
        assertEquals(7, consensus.history.size)
        assertNotNull(markets.disclaimer)
    }

    @Test
    fun `parses finance including a candidate with almost nothing filed`() {
        val finance = json.decodeFromString<FinancePayload>(load("finance.json"))
        assertEquals(2026, finance.cycle)

        val marshall = finance.candidates.getValue(CandidateIds.MARSHALL)
        assertEquals("Marshall for Kansas", marshall.committeeName)
        assertEquals("2026-06-30", marshall.coverageEndDate)
        assertEquals(41.2, marshall.inStatePct!!, 0.001)

        // Sparse record: numeric fields default to zero, optionals to null, and
        // the screen must still render rather than crash.
        val hamilton = finance.candidates.getValue(CandidateIds.HAMILTON)
        assertNull(hamilton.committeeName)
        assertNull(hamilton.inStatePct)
        assertNull(hamilton.burnRateMonthly)
        assertEquals(0.0, hamilton.pacContributions, 0.001)

        val outside = finance.outsideSpending
        assertEquals(5_500_000.0, outside.total, 0.001)
        assertEquals(3_400_000.0, outside.opposing.getValue(CandidateIds.HAMILTON), 0.001)
        assertEquals("hamilton", outside.topSpenders.single().opposes)
        assertFalse("the recent expenditure opposes Hamilton", outside.recent.single().supports)
    }

    @Test
    fun `parses news including an item with no timestamp`() {
        val news = json.decodeFromString<NewsPayload>(load("news.json"))
        assertEquals(2, news.items.size)

        val dated = news.items.first { it.publishedAt != null }
        assertEquals(listOf("hamilton", "marshall"), dated.mentions)

        val undated = news.items.single { it.publishedAt == null }
        assertNull(undated.summary)
        assertEquals(listOf("marshall"), undated.mentions)
    }

    @Test
    fun `results start dormant`() {
        val results = json.decodeFromString<ResultsPayload>(load("results.json"))
        assertEquals("pending", results.status)
        assertFalse("results are dormant before election night", results.isLive)
        assertTrue(results.counties.isEmpty())
    }

    @Test
    fun `unknown fields are ignored so a new contract field cannot break an old app`() {
        val body = """
            {"schema_version": 1, "generated_at": "2026-08-22T12:00:00Z",
             "election_date": "2026-11-03", "days_until_election": 73,
             "candidates": [], "a_field_from_the_future": {"nested": [1, 2, 3]}}
        """.trimIndent()
        val race = json.decodeFromString<RacePayload>(body)
        assertEquals(73, race.daysUntilElection)
    }

    @Test
    fun `every core data file has a fixture`() {
        // If someone adds a file to the contract, this fails until the app is
        // taught to read it.
        DataFile.core.forEach { file ->
            assertNotNull("no fixture for ${file.fileName}", load(file.fileName))
        }
    }

    @Test
    fun `parses ads including an unattributed buy with no amount`() {
        val ads = json.decodeFromString<AdsPayload>(load("ads.json"))
        val broadcast = ads.broadcast

        assertEquals(3, broadcast.byWeek.size)
        assertEquals(2, broadcast.byMarket.size)
        assertEquals(1_850_000.0, broadcast.totalBySide.getValue(CandidateIds.MARSHALL), 0.01)

        // Money that could not be attributed to either side keeps its own bucket
        // rather than being folded into a candidate's column.
        assertEquals(260_000.0, broadcast.totalBySide.getValue("unattributed"), 0.01)

        val unattributed = broadcast.filings.single { it.advertiser == "Sunflower Values Fund" }
        assertNull("an unattributable buy names no side", unattributed.side)
        assertTrue(unattributed.isOutsideGroup)
        // A missing amount must stay null: a filing with no figure is not a $0 buy.
        assertNull(unattributed.amount)
        assertNull(unattributed.market)
    }

    @Test
    fun `digital ads report their own unavailability with a reason`() {
        val ads = json.decodeFromString<AdsPayload>(load("ads.json"))
        assertFalse(ads.digital.available)
        assertTrue(ads.digital.unavailableReason!!.contains("identity verification"))
    }

    @Test
    fun `parses ground data and a partially-read county dashboard`() {
        val ground = json.decodeFromString<GroundPayload>(load("ground.json"))

        val statewide = ground.registration.statewide!!
        assertEquals(2_004_800, statewide.total)
        assertEquals(875_400 - 498_200, statewide.partyGap)
        assertEquals(3, ground.registration.byCounty.size)

        val advance = ground.advanceBallots
        assertEquals(listOf("Johnson", "Sedgwick"), advance.countiesCovered)

        // Sedgwick's dashboard yielded only one figure. The others must read as
        // null — unknown — never as zero.
        val sedgwick = advance.counties.single { it.county == "Sedgwick" }
        assertEquals(6_900, sedgwick.mailBallotsReturned)
        assertNull(sedgwick.mailBallotsSent)
        assertNull(sedgwick.inPersonVotes)
    }

    @Test
    fun `advance coverage is described rather than implied`() {
        val ground = json.decodeFromString<GroundPayload>(load("ground.json"))
        // The payload must carry its own caveat, so the app cannot present
        // five counties as though they were the state.
        assertTrue(ground.advanceBallots.coverageNote.contains("no statewide"))
    }
}
