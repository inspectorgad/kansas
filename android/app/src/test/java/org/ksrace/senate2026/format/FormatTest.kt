package org.ksrace.senate2026.format

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.util.concurrent.TimeUnit

/**
 * Formatting tests.
 *
 * The bad-input cases matter more than the happy path here: these strings come
 * from an upstream we do not control, and the requirement is that a malformed
 * value renders as "unknown" rather than crashing a screen or, worse, silently
 * displaying the epoch as though it were real.
 */
class FormatTest {

    private val today = LocalDate.of(2026, 8, 22)

    @Test
    fun `short dollars compact at each magnitude`() {
        assertEquals("$1.2B", formatShortDollars(1_240_000_000.0))
        assertEquals("$8.4M", formatShortDollars(8_400_000.0))
        assertEquals("$840K", formatShortDollars(840_000.0))
        assertEquals("$1,240", formatShortDollars(1_240.0))
        assertEquals("$0", formatShortDollars(0.0))
    }

    @Test
    fun `exact dollars group thousands`() {
        assertEquals("$1,234,567", formatDollars(1_234_567.0))
    }

    @Test
    fun `probability renders as whole percent`() {
        assertEquals("71%", formatProbability(0.71))
        assertEquals("50%", formatProbability(0.5))
        assertEquals("100%", formatProbability(1.0))
    }

    @Test
    fun `signed margin always carries an explicit sign`() {
        assertEquals("+1.3", formatSigned(1.3))
        assertEquals("−1.3", formatSigned(-1.3))
        // A true minus sign, not a hyphen: it reads correctly next to digits.
        assertTrue(formatSigned(-1.3).startsWith("−"))
        assertEquals("+0.0", formatSigned(0.0))
        assertEquals("+2", formatSigned(2.4, decimals = 0))
    }

    @Test
    fun `date range collapses within a month and spells out across months`() {
        assertEquals("Aug 6–8", formatDateRange("2026-08-06", "2026-08-08", today))
        assertEquals("Jul 28 – Aug 2", formatDateRange("2026-07-28", "2026-08-02", today))
    }

    @Test
    fun `single-day range renders as one date`() {
        assertEquals("Aug 8", formatDateRange("2026-08-08", "2026-08-08", today))
    }

    @Test
    fun `dates from another year keep the year`() {
        assertEquals("Jan 3, 2026", formatIsoDate("2026-01-03", LocalDate.of(2027, 2, 1)))
        assertEquals("Aug 8", formatIsoDate("2026-08-08", today))
    }

    @Test
    fun `malformed dates return null rather than a wrong date`() {
        assertNull(formatIsoDate("sometime last spring", today))
        assertNull(formatIsoDate("", today))
        assertNull(formatIsoDate(null, today))
        assertNull(parseIsoDate("2026-13-45"))
    }

    @Test
    fun `a half-parseable range degrades to the end date`() {
        assertEquals("Aug 8", formatDateRange("nonsense", "2026-08-08", today))
    }

    @Test
    fun `instants parse with and without an offset`() {
        assertEquals(parseInstant("2026-08-22T12:00:00Z"), parseInstant("2026-08-22T12:00:00+00:00"))
        assertNull(parseInstant("not a timestamp"))
        assertNull(parseInstant(null))
    }

    @Test
    fun `age reads in plain words`() {
        assertEquals("just now", formatAge(TimeUnit.SECONDS.toMillis(30)))
        assertEquals("12 min ago", formatAge(TimeUnit.MINUTES.toMillis(12)))
        assertEquals("3 h ago", formatAge(TimeUnit.HOURS.toMillis(3)))
        assertEquals("yesterday", formatAge(TimeUnit.DAYS.toMillis(1)))
        assertEquals("5 days ago", formatAge(TimeUnit.DAYS.toMillis(5)))
        assertEquals("over a month ago", formatAge(TimeUnit.DAYS.toMillis(90)))
    }

    @Test
    fun `unknown age says so instead of claiming freshness`() {
        assertEquals("age unknown", formatAge(null))
        assertEquals("age unknown", formatAge(-1))
    }

    @Test
    fun `countdown handles the last few days and the day itself`() {
        assertEquals("73 days to election day", formatCountdown(73))
        assertEquals("Election day is tomorrow", formatCountdown(1))
        assertEquals("Election day", formatCountdown(0))
        assertEquals("Election day has passed", formatCountdown(-1))
    }

    @Test
    fun `votes group thousands`() {
        assertEquals("412,905", formatVotes(412_905))
        assertEquals("0", formatVotes(0))
    }
}
