package org.ksrace.senate2026.ui.polls

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.data.DataFile
import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.data.model.Poll
import org.ksrace.senate2026.format.formatDateRange
import org.ksrace.senate2026.format.formatIsoDate
import org.ksrace.senate2026.format.formatShare
import org.ksrace.senate2026.ui.components.AsOfLabel
import org.ksrace.senate2026.ui.components.EmptyState
import org.ksrace.senate2026.ui.components.Series
import org.ksrace.senate2026.ui.components.SectionCard
import org.ksrace.senate2026.ui.components.ThinDivider
import org.ksrace.senate2026.ui.components.TrendChart
import org.ksrace.senate2026.ui.theme.LocalChartPalette
import org.ksrace.senate2026.ui.theme.TabularNumberStyle
import kotlin.math.abs

/**
 * Every poll, and the average built from them.
 *
 * The list shows methodology inline — sample, population, margin of error, and a
 * label on anything a campaign paid for. A reader should be able to see which
 * polls are carrying the average and decide for themselves whether to trust it.
 */
@Composable
fun PollsScreen(snapshot: RaceSnapshot, now: Long, modifier: Modifier = Modifier) {
    val palette = LocalChartPalette.current
    val payload = snapshot.polls
    var independentOnly by rememberSaveable { mutableStateOf(false) }

    if (payload == null || payload.polls.isEmpty()) {
        EmptyState(
            message = "No polls yet",
            detail = "Public polling of this race will appear here as it is released.",
            modifier = modifier,
        )
        return
    }

    val visible = if (independentOnly) payload.polls.filterNot { it.isPartisan } else payload.polls
    val aggregate = payload.aggregate

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (aggregate != null && aggregate.history.size >= 3) {
            item {
                SectionCard(
                    title = "Trend",
                    subtitle = "Recomputed as of each day, using only polls finished by then",
                ) {
                    TrendChart(
                        series = listOf(
                            Series(
                                label = "Marshall",
                                color = palette.marshall,
                                values = aggregate.history.map { it.marshall },
                            ),
                            Series(
                                label = "Hamilton",
                                color = palette.hamilton,
                                values = aggregate.history.map { it.hamilton },
                            ),
                        ),
                        startLabel = formatIsoDate(
                            aggregate.history.first().date,
                        ),
                        endLabel = formatIsoDate(
                            aggregate.history.last().date,
                        ),
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = aggregate.method,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        item {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                FilterChip(
                    selected = !independentOnly,
                    onClick = { independentOnly = false },
                    label = { Text("All polls (${payload.polls.size})") },
                )
                FilterChip(
                    selected = independentOnly,
                    onClick = { independentOnly = true },
                    label = { Text("Independent only") },
                )
            }
        }

        if (visible.isEmpty()) {
            item {
                EmptyState(
                    message = "No independent polls yet",
                    detail = "Every poll released so far was sponsored by a campaign or an " +
                        "aligned group. Switch back to see them, labelled.",
                )
            }
        }

        items(visible.size) { index ->
            PollRow(visible[index])
        }

        item {
            Spacer(Modifier.height(4.dp))
            AsOfLabel(snapshot.ageMillis(DataFile.POLLS, now))
            payload.attribution.forEach { credit ->
                Text(
                    text = "${credit.name}${credit.license?.let { " · $it" } ?: ""}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun PollRow(poll: Poll) {
    val palette = LocalChartPalette.current
    val leaderColor = palette.forCandidate(poll.results.leaderId)

    SectionCard(
        title = poll.pollster,
        subtitle = formatDateRange(poll.startDate, poll.endDate),
        trailing = {
            if (poll.isPartisan) {
                // A label, not a chip: there is nothing to tap, and a disabled
                // chip reads as a control the reader is being denied.
                Text(
                    text = "SPONSORED",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            CandidateNumber("Marshall", poll.results.marshall, palette.marshall)
            CandidateNumber("Hamilton", poll.results.hamilton, palette.hamilton)
            Column {
                Text(
                    text = "MARGIN",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = formatShare(abs(poll.results.margin)),
                    style = TabularNumberStyle,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }

        Spacer(Modifier.height(10.dp))
        ThinDivider()
        Spacer(Modifier.height(8.dp))

        Text(
            text = methodologyLine(poll),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        poll.sponsor?.let { sponsor ->
            Text(
                text = "Sponsor: $sponsor",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CandidateNumber(name: String, value: Double, color: Color) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(color))
            Spacer(Modifier.size(6.dp))
            Text(
                text = name.uppercase(),
                style = MaterialTheme.typography.labelSmall,
                // The dot carries identity; the text stays in ink.
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text(
            text = formatShare(value),
            style = TabularNumberStyle,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

/** Sample, population and margin of error, or an honest note when absent. */
private fun methodologyLine(poll: Poll): String {
    val parts = mutableListOf<String>()
    val size = poll.sampleSize
    if (size != null) {
        val population = when (poll.population?.uppercase()) {
            "LV" -> "likely voters"
            "RV" -> "registered voters"
            "A" -> "adults"
            else -> "respondents"
        }
        parts += "%,d".format(size) + " $population"
    } else {
        // `?.let {} ?: run {}` would not work here: the let block ends in a
        // MutableList `+=`, which returns Unit, so the elvis branch never runs.
        parts += "sample size not reported"
    }

    poll.marginOfError?.let { parts += "±${formatShare(it)} pts" }
    poll.undecided?.let { parts += "${formatShare(it)}% undecided" }
    return parts.joinToString(" · ")
}
