package org.ksrace.senate2026.format

import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import kotlin.math.abs
import kotlin.math.roundToLong

/**
 * Display formatting.
 *
 * Everything here tolerates bad input: an unparseable timestamp renders as
 * "unknown", never as a crash or a misleading default like the epoch. Payload
 * timestamps arrive as strings from an upstream we do not control.
 */

private val MONTH_DAY: DateTimeFormatter = DateTimeFormatter.ofPattern("MMM d")
private val MONTH_DAY_YEAR: DateTimeFormatter = DateTimeFormatter.ofPattern("MMM d, yyyy")
private val TIME_OF_DAY: DateTimeFormatter = DateTimeFormatter.ofPattern("h:mm a")

/** `$1.2M`, `$840K`, `$1,240`. Compact enough for a stat tile. */
fun formatShortDollars(amount: Double): String {
    val magnitude = abs(amount)
    return when {
        magnitude >= 1_000_000_000 -> "$%.1fB".format(amount / 1_000_000_000)
        magnitude >= 1_000_000 -> "$%.1fM".format(amount / 1_000_000)
        magnitude >= 10_000 -> "$%.0fK".format(amount / 1_000)
        else -> "$" + "%,d".format(amount.roundToLong())
    }
}

/** `$1,234,567` — for detail rows where the exact figure matters. */
fun formatDollars(amount: Double): String = "$" + "%,d".format(amount.roundToLong())

/** A 0..1 probability as a whole percentage. */
fun formatProbability(value: Double): String = "%.0f%%".format(value * 100)

/** A polling share, one decimal. */
fun formatShare(value: Double): String = "%.1f".format(value)

/** A margin with an explicit sign, so a lead is never ambiguous. */
fun formatSigned(value: Double, decimals: Int = 1): String {
    val formatted = "%.${decimals}f".format(abs(value))
    val sign = if (value >= 0) "+" else "−" // true minus sign, not a hyphen
    return "$sign$formatted"
}

fun formatVotes(votes: Int): String = "%,d".format(votes)

/** `Aug 8` for this year, `Aug 8, 2025` otherwise. Returns null if unparseable. */
fun formatIsoDate(value: String?, today: LocalDate = LocalDate.now()): String? {
    val date = parseIsoDate(value) ?: return null
    return if (date.year == today.year) date.format(MONTH_DAY) else date.format(MONTH_DAY_YEAR)
}

/** A poll's field window: `Aug 6–8` or `Jul 28 – Aug 2`. */
fun formatDateRange(start: String?, end: String?, today: LocalDate = LocalDate.now()): String? {
    val from = parseIsoDate(start)
    val to = parseIsoDate(end)
    if (from == null || to == null) return formatIsoDate(end, today) ?: formatIsoDate(start, today)
    if (from == to) return formatIsoDate(end, today)
    return if (from.month == to.month && from.year == to.year) {
        "${from.format(MONTH_DAY)}–${to.dayOfMonth}"
    } else {
        "${from.format(MONTH_DAY)} – ${formatIsoDate(end, today)}"
    }
}

fun formatIsoTime(value: String?, zone: ZoneId = ZoneId.systemDefault()): String? {
    val instant = parseInstant(value) ?: return null
    return instant.atZone(zone).format(TIME_OF_DAY)
}

/**
 * How stale something is, in plain words: `just now`, `12 min ago`, `3 h ago`,
 * `2 days ago`. This label appears next to every number in the app.
 */
fun formatAge(ageMillis: Long?): String {
    if (ageMillis == null || ageMillis < 0) return "age unknown"
    val duration = Duration.ofMillis(ageMillis)
    val minutes = duration.toMinutes()
    return when {
        minutes < 2 -> "just now"
        minutes < 60 -> "$minutes min ago"
        duration.toHours() < 24 -> "${duration.toHours()} h ago"
        duration.toDays() == 1L -> "yesterday"
        duration.toDays() < 30 -> "${duration.toDays()} days ago"
        else -> "over a month ago"
    }
}

/** Days-to-election, phrased for a countdown line. */
fun formatCountdown(days: Int): String = when {
    days > 1 -> "$days days to election day"
    days == 1 -> "Election day is tomorrow"
    days == 0 -> "Election day"
    else -> "Election day has passed"
}

fun parseIsoDate(value: String?): LocalDate? {
    if (value.isNullOrBlank()) return null
    return try {
        LocalDate.parse(value.take(10))
    } catch (_: DateTimeParseException) {
        null
    }
}

fun parseInstant(value: String?): Instant? {
    if (value.isNullOrBlank()) return null
    return try {
        Instant.parse(value)
    } catch (_: DateTimeParseException) {
        // The collector emits offset timestamps; Instant.parse wants a Z suffix.
        try {
            java.time.OffsetDateTime.parse(value).toInstant()
        } catch (_: DateTimeParseException) {
            null
        }
    }
}
