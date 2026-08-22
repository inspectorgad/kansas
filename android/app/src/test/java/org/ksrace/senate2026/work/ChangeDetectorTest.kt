package org.ksrace.senate2026.work

import android.content.SharedPreferences
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ksrace.senate2026.data.model.CandidatePair
import org.ksrace.senate2026.data.model.Consensus
import org.ksrace.senate2026.data.model.Filing
import org.ksrace.senate2026.data.model.FinancePayload
import org.ksrace.senate2026.data.model.MarketsPayload
import org.ksrace.senate2026.data.model.Poll
import org.ksrace.senate2026.data.model.PollsPayload
import org.ksrace.senate2026.data.model.ResultsPayload
import org.ksrace.senate2026.data.RaceSnapshot

/**
 * Notification rules.
 *
 * The behaviour worth protecting is restraint. A tracker that notifies on every
 * refresh gets muted within a day, and a muted tracker reports nothing — so the
 * first run must stay silent about the existing back catalogue, and a repeat run
 * over unchanged data must stay silent entirely.
 */
class ChangeDetectorTest {

    /** An in-memory SharedPreferences, so this stays a plain JVM test. */
    private class FakePrefs : SharedPreferences {
        val values = mutableMapOf<String, Any?>()

        override fun getString(key: String, defValue: String?) = values[key] as? String ?: defValue

        @Suppress("UNCHECKED_CAST")
        override fun getStringSet(key: String, defValues: Set<String>?) =
            values[key] as? Set<String> ?: defValues

        override fun getFloat(key: String, defValue: Float) = values[key] as? Float ?: defValue
        override fun getBoolean(key: String, defValue: Boolean) = values[key] as? Boolean ?: defValue

        // Written out longhand deliberately: a helper named `apply` would collide
        // with both the Editor.apply() override and Kotlin's stdlib `apply`.
        override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
            override fun putString(key: String, value: String?): SharedPreferences.Editor {
                values[key] = value
                return this
            }

            override fun putStringSet(key: String, v: Set<String>?): SharedPreferences.Editor {
                values[key] = v
                return this
            }

            override fun putFloat(key: String, value: Float): SharedPreferences.Editor {
                values[key] = value
                return this
            }

            override fun putBoolean(key: String, value: Boolean): SharedPreferences.Editor {
                values[key] = value
                return this
            }

            override fun apply() {
                // Writes land immediately in this fake; nothing to flush.
            }
        }
    }

    private fun poll(id: String, marshall: Double = 46.0, hamilton: Double = 45.0) = Poll(
        id = id,
        pollster = "Pollster $id",
        startDate = "2026-08-06",
        endDate = "2026-08-08",
        results = CandidatePair(marshall = marshall, hamilton = hamilton),
    )

    private fun snapshotWithPolls(vararg ids: String) = RaceSnapshot(
        polls = PollsPayload(
            generatedAt = "2026-08-22T12:00:00Z",
            polls = ids.map { poll(it) },
        ),
    )

    private fun snapshotWithMarket(marshall: Double) = RaceSnapshot(
        markets = MarketsPayload(
            generatedAt = "2026-08-22T12:00:00Z",
            consensus = Consensus(
                asOf = "2026-08-22T12:00:00Z",
                marshall = marshall,
                hamilton = 1.0 - marshall,
            ),
        ),
    )

    @Test
    fun `the first run is silent about polls that already existed`() {
        val detector = ChangeDetector(FakePrefs())
        val events = detector.eventsFor(snapshotWithPolls("a", "b", "c"))
        assertTrue("first run must not announce a back catalogue", events.none { it.id.startsWith("poll-") })
    }

    @Test
    fun `a genuinely new poll notifies once`() {
        val prefs = FakePrefs()
        ChangeDetector(prefs).eventsFor(snapshotWithPolls("a", "b"))

        val events = ChangeDetector(prefs).eventsFor(snapshotWithPolls("new", "a", "b"))
        val pollEvent = events.single { it.id.startsWith("poll-") }
        assertEquals("New poll: Pollster new", pollEvent.title)

        // Same data again: nothing more to say.
        val repeat = ChangeDetector(prefs).eventsFor(snapshotWithPolls("new", "a", "b"))
        assertTrue(repeat.none { it.id.startsWith("poll-") })
    }

    @Test
    fun `several new polls collapse into one notification`() {
        val prefs = FakePrefs()
        ChangeDetector(prefs).eventsFor(snapshotWithPolls("a"))
        val events = ChangeDetector(prefs).eventsFor(snapshotWithPolls("x", "y", "z", "a"))
        assertEquals("3 new polls", events.single { it.id.startsWith("poll-") }.title)
    }

    @Test
    fun `a poll that disappears and returns does not notify twice`() {
        val prefs = FakePrefs()
        ChangeDetector(prefs).eventsFor(snapshotWithPolls("a"))
        ChangeDetector(prefs).eventsFor(snapshotWithPolls("blip", "a"))
        ChangeDetector(prefs).eventsFor(snapshotWithPolls("a"))

        val events = ChangeDetector(prefs).eventsFor(snapshotWithPolls("blip", "a"))
        assertTrue(
            "an upstream edit that removed and restored a poll must stay quiet",
            events.none { it.id.startsWith("poll-") },
        )
    }

    @Test
    fun `a small market move stays quiet`() {
        val prefs = FakePrefs()
        ChangeDetector(prefs).eventsFor(snapshotWithMarket(0.70))
        val events = ChangeDetector(prefs).eventsFor(snapshotWithMarket(0.72))
        assertTrue("2 points is noise", events.none { it.id.startsWith("market-") })
    }

    @Test
    fun `a large market move notifies with a direction`() {
        val prefs = FakePrefs()
        ChangeDetector(prefs).eventsFor(snapshotWithMarket(0.70))
        val event = ChangeDetector(prefs).eventsFor(snapshotWithMarket(0.78))
            .single { it.id.startsWith("market-") }
        assertTrue(event.title.contains("toward Marshall"))
        assertTrue(event.title.contains("8 points"))
        // The body must not let a probability be mistaken for a vote share.
        assertTrue(event.body.contains("not a vote share"))
    }

    @Test
    fun `a large market move the other way names the other candidate`() {
        val prefs = FakePrefs()
        ChangeDetector(prefs).eventsFor(snapshotWithMarket(0.70))
        val event = ChangeDetector(prefs).eventsFor(snapshotWithMarket(0.60))
            .single { it.id.startsWith("market-") }
        assertTrue(event.title.contains("toward Hamilton"))
    }

    @Test
    fun `a new filing notifies but the same one does not`() {
        val prefs = FakePrefs()
        fun snapshot(date: String) = RaceSnapshot(
            finance = FinancePayload(
                generatedAt = "2026-08-22T12:00:00Z",
                filings = listOf(
                    Filing(
                        date = date,
                        committeeName = "Marshall for Kansas",
                        committeeId = "C001",
                        formType = "F3",
                        totalReceipts = 1_900_000.0,
                    ),
                ),
            ),
        )

        ChangeDetector(prefs).eventsFor(snapshot("2026-07-15"))
        val events = ChangeDetector(prefs).eventsFor(snapshot("2026-10-15"))
        val filing = events.single { it.id.startsWith("filing-") }
        assertTrue(filing.title.contains("Marshall for Kansas"))
        assertTrue(filing.body.contains("$1.9M"))

        assertTrue(ChangeDetector(prefs).eventsFor(snapshot("2026-10-15")).none { it.id.startsWith("filing-") })
    }

    @Test
    fun `results going live is announced exactly once`() {
        val prefs = FakePrefs()
        val live = RaceSnapshot(
            results = ResultsPayload(
                generatedAt = "2026-11-03T23:10:00Z",
                status = "live",
            ),
        )
        assertEquals(1, ChangeDetector(prefs).eventsFor(live).count { it.id == "results-live" })
        assertEquals(0, ChangeDetector(prefs).eventsFor(live).count { it.id == "results-live" })
    }

    @Test
    fun `an empty snapshot produces nothing`() {
        assertTrue(ChangeDetector(FakePrefs()).eventsFor(RaceSnapshot()).isEmpty())
    }
}
