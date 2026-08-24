package org.ksrace.senate2026.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.data.DataFile
import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.data.model.CandidateIds
import org.ksrace.senate2026.data.model.MarginDistribution
import org.ksrace.senate2026.format.formatAge
import org.ksrace.senate2026.format.formatCountdown
import org.ksrace.senate2026.format.formatIsoDate
import org.ksrace.senate2026.format.formatProbability
import org.ksrace.senate2026.format.formatShare
import org.ksrace.senate2026.format.formatShortDollars
import org.ksrace.senate2026.format.formatSigned
import org.ksrace.senate2026.format.formatVotes
import org.ksrace.senate2026.ui.components.AsOfLabel
import org.ksrace.senate2026.ui.components.EmptyState
import org.ksrace.senate2026.ui.components.HeroNumber
import org.ksrace.senate2026.ui.components.SectionCard
import org.ksrace.senate2026.ui.components.Series
import org.ksrace.senate2026.ui.components.ShareBars
import org.ksrace.senate2026.ui.components.Sparkline
import org.ksrace.senate2026.ui.components.StaleBanner
import org.ksrace.senate2026.ui.components.StatTile
import org.ksrace.senate2026.ui.components.ThinDivider
import org.ksrace.senate2026.ui.components.TrendChart
import org.ksrace.senate2026.ui.theme.LocalChartPalette
import kotlin.math.abs

/**
 * The race at a glance.
 *
 * The headline slot answers "who is winning" with the two honest answers to that
 * question, kept visibly distinct: the market's probability of victory, and the
 * polling average's margin. On election night the same slot gives way to actual
 * returns, which is the only time a real vote share exists.
 */
@Composable
fun HomeScreen(
    snapshot: RaceSnapshot,
    now: Long,
    onRefresh: () -> Unit,
    onResultsVisible: () -> Unit,
    onOpenResults: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (!snapshot.hasAnyData) {
        Column(
            modifier = modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            EmptyState(
                message = if (snapshot.loading) "Loading the race…" else "No data yet",
                detail = if (snapshot.loading) {
                    null
                } else {
                    "Could not reach the data feed. Check your connection and try again."
                },
            )
            if (!snapshot.loading) {
                TextButton(onClick = onRefresh) { Text("Try again") }
            }
        }
        return
    }

    LaunchedEffect(snapshot.resultsAreLive) {
        if (snapshot.resultsAreLive) onResultsVisible()
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { RaceHeader(snapshot) }

        snapshot.problems[DataFile.MARKETS]?.let { reason ->
            item { StaleBanner(reason, snapshot.ageMillis(DataFile.MARKETS, now)) }
        }

        if (snapshot.resultsAreLive) {
            item { LiveResultsCard(snapshot, now, onOpenResults) }
        } else {
            item { MarketCard(snapshot, now) }
        }

        item { PollAverageCard(snapshot, now) }
        // After the poll average, because the card compares itself to it.
        snapshot.markets?.margin?.takeIf { it.hasBands }?.let { margin ->
            item { MarginCard(margin, now, snapshot) }
        }
        item { MoneySummaryCard(snapshot, now) }
        item { LatestHeadlineCard(snapshot, now) }
        item { Spacer(Modifier.height(8.dp)) }
    }
}

@Composable
private fun RaceHeader(snapshot: RaceSnapshot) {
    val race = snapshot.race
    Column {
        Text(
            text = "Kansas · U.S. Senate",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = race?.candidates?.joinToString(" vs. ") { it.surname }
                ?: "Marshall vs. Hamilton",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        if (race != null) {
            Text(
                text = formatCountdown(race.daysUntilElection),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (race.ratings.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = race.ratings.joinToString(" · ") { "${it.source}: ${it.rating}" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * The market probability, as a hero number rather than a chart.
 *
 * One figure with a trend does not need axes; a two-slice chart of "72% / 28%"
 * would say less than the number itself. The caption does the load-bearing work
 * of saying what the number is not.
 */
@Composable
private fun MarketCard(snapshot: RaceSnapshot, now: Long) {
    val palette = LocalChartPalette.current
    val consensus = snapshot.markets?.consensus

    SectionCard(
        title = "Win probability",
        subtitle = consensus?.platforms?.takeIf { it.isNotEmpty() }
            ?.joinToString(" + ") { it.replaceFirstChar(Char::titlecase) },
    ) {
        if (consensus == null) {
            Text(
                text = "No prediction market is quoting this race right now.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            return@SectionCard
        }

        val leadsMarshall = consensus.marshall >= consensus.hamilton
        val leaderName = if (leadsMarshall) "Marshall" else "Hamilton"
        val leaderValue = if (leadsMarshall) consensus.marshall else consensus.hamilton

        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            HeroNumber(
                value = formatProbability(leaderValue),
                label = "$leaderName to win",
                caption = "A betting-market probability of winning — not a projected vote share.",
                modifier = Modifier.weight(1f),
            )
            val trend = consensus.history.map { it.marshall }
            if (trend.size >= 2) {
                Sparkline(
                    values = trend,
                    color = palette.marshall,
                    modifier = Modifier
                        .padding(start = 12.dp)
                        .height(48.dp)
                        .weight(0.6f),
                )
            }
        }

        consensus.change24h?.let { change ->
            Spacer(Modifier.height(8.dp))
            val points = formatSigned(change * 100, decimals = 0)
            Text(
                text = "$points points for Marshall in 24 hours",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(8.dp))
        AsOfLabel(snapshot.ageMillis(DataFile.MARKETS, now))
    }
}

/**
 * How close, not just who.
 *
 * A single win probability answers the less interesting question. This is built
 * from Kalshi's margin ladder — each rung a price on "will the margin be at least
 * N points" — so the gap between adjacent rungs is the chance of landing in that
 * band. The bands close to one against a win probability taken from a completely
 * separate market, the governor-by-senate grid, which is the reason to trust the
 * shape: two unrelated contracts agreeing is a stronger claim than either alone.
 *
 * Colour carries polarity only, one hue per candidate, and the two are the pair
 * already validated for colour-vision separation. Magnitude is bar length and
 * order is the band sequence, so a lightness ramp inside one candidate's bands
 * would encode the margin a third time and say nothing new.
 *
 * The asymmetry is honest and belongs on screen: the exchange lists rungs for one
 * candidate only, so that side gets a dozen bands and the other gets one. That is
 * a fact about the exchange, not about the race.
 */
@Composable
private fun MarginCard(margin: MarginDistribution, now: Long, snapshot: RaceSnapshot) {
    val palette = LocalChartPalette.current

    SectionCard(
        title = "How close is it likely to be",
        subtitle = margin.note,
    ) {
        val median = margin.medianMargin
        if (median != null) {
            val who = if (margin.leader == CandidateIds.MARSHALL) "Marshall" else "Hamilton"
            HeroNumber(
                value = "$who +${formatShare(median)}",
                label = "Median implied margin",
                caption = "from ${margin.rungs} threshold markets",
            )
            // The poll average is the natural comparison, and the two disagree
            // sharply at the moment, which is worth seeing side by side rather
            // than on two different screens.
            snapshot.polls?.aggregate?.let { aggregate ->
                val pollLeader =
                    if (aggregate.leader == CandidateIds.MARSHALL) "Marshall" else "Hamilton"
                Spacer(Modifier.height(6.dp))
                Text(
                    text = "Polling average: $pollLeader " +
                        "+${formatShare(abs(aggregate.margin))}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(12.dp))
            ThinDivider()
            Spacer(Modifier.height(12.dp))
        }

        ShareBars(
            rows = margin.buckets.map { bucket ->
                Triple(
                    bucket.label,
                    bucket.probability * 100.0,
                    if (bucket.candidateId == CandidateIds.HAMILTON) {
                        palette.hamilton
                    } else {
                        palette.marshall
                    },
                )
            },
            valueLabel = { "${formatShare(it)}%" },
        )

        margin.modal?.let { modal ->
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Likeliest single outcome: ${modal.label}, " +
                    "${formatShare(modal.probability * 100)}%.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }

        Spacer(Modifier.height(8.dp))
        Text(
            text = "Bands are derived from prices, not from a forecast, and they " +
                "sum to 100%.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        AsOfLabel(snapshot.ageMillis(DataFile.MARKETS, now), source = "Kalshi")
    }
}

@Composable
private fun PollAverageCard(snapshot: RaceSnapshot, now: Long) {
    val palette = LocalChartPalette.current
    val aggregate = snapshot.polls?.aggregate

    SectionCard(
        title = "Polling average",
        subtitle = aggregate?.let { "${it.nPollsUsed} polls" },
    ) {
        if (aggregate == null) {
            Text(
                text = "Not enough polling yet to average.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            return@SectionCard
        }

        val leaderName = if (aggregate.leader == CandidateIds.MARSHALL) "Marshall" else "Hamilton"
        val margin = abs(aggregate.margin)

        // Inside the band there is no clear leader, and saying so is the point.
        val headline = if (margin <= aggregate.band) {
            "Too close to call"
        } else {
            "$leaderName +${formatShare(margin)}"
        }

        HeroNumber(
            value = headline,
            label = "Margin",
            caption = "±${formatShare(aggregate.band)} points. The band combines sampling error " +
                "with how much pollsters disagree.",
        )

        Spacer(Modifier.height(14.dp))
        ShareBars(
            rows = listOf(
                Triple("Marshall", aggregate.marshall, palette.marshall),
                Triple("Hamilton", aggregate.hamilton, palette.hamilton),
            ),
            maxValue = 100.0,
        )

        val history = aggregate.history
        if (history.size >= 3) {
            Spacer(Modifier.height(16.dp))
            TrendChart(
                series = listOf(
                    Series(
                        label = "Marshall",
                        color = palette.marshall,
                        values = history.map { it.marshall },
                        band = history.map { aggregate.band / 2 },
                    ),
                    Series(
                        label = "Hamilton",
                        color = palette.hamilton,
                        values = history.map { it.hamilton },
                        band = history.map { aggregate.band / 2 },
                    ),
                ),
                startLabel = formatIsoDate(history.first().date),
                endLabel = formatIsoDate(history.last().date),
            )
        }

        Spacer(Modifier.height(8.dp))
        AsOfLabel(snapshot.ageMillis(DataFile.POLLS, now))
    }
}

@Composable
private fun MoneySummaryCard(snapshot: RaceSnapshot, now: Long) {
    val palette = LocalChartPalette.current
    val finance = snapshot.finance ?: return
    val marshall = finance.candidates[CandidateIds.MARSHALL]
    val hamilton = finance.candidates[CandidateIds.HAMILTON]
    if (marshall == null && hamilton == null) return

    SectionCard(
        title = "Money",
        subtitle = marshall?.coverageEndDate?.let { "Through $it" },
    ) {
        ShareBars(
            rows = listOfNotNull(
                marshall?.let { Triple("Marshall raised", it.totalReceipts, palette.marshall) },
                hamilton?.let { Triple("Hamilton raised", it.totalReceipts, palette.hamilton) },
            ),
            valueLabel = { formatShortDollars(it) },
        )

        val outside = finance.outsideSpending.total
        if (outside > 0) {
            Spacer(Modifier.height(12.dp))
            ThinDivider()
            Spacer(Modifier.height(12.dp))
            StatTile(
                label = "Outside spending",
                value = formatShortDollars(outside),
                caption = "Independent expenditures for and against both candidates.",
            )
        }

        Spacer(Modifier.height(8.dp))
        AsOfLabel(snapshot.ageMillis(DataFile.FINANCE, now), source = "FEC")
    }
}

@Composable
private fun LatestHeadlineCard(snapshot: RaceSnapshot, now: Long) {
    val items = snapshot.news?.items?.take(3).orEmpty()
    if (items.isEmpty()) return

    SectionCard(title = "Latest") {
        items.forEachIndexed { index, item ->
            if (index > 0) {
                Spacer(Modifier.height(10.dp))
                ThinDivider()
                Spacer(Modifier.height(10.dp))
            }
            Text(
                text = item.title,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = item.source,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(8.dp))
        AsOfLabel(snapshot.ageMillis(DataFile.NEWS, now))
    }
}

/**
 * Election night. This is the only screen in the app that shows a real vote
 * share, because it is the only time one exists.
 */
@Composable
private fun LiveResultsCard(snapshot: RaceSnapshot, now: Long, onOpenResults: () -> Unit) {
    val palette = LocalChartPalette.current
    val results = snapshot.results ?: return

    SectionCard(
        title = if (results.status == "final") "Final results" else "Results coming in",
        subtitle = results.pctReporting?.let { "${formatShare(it)}% of precincts reporting" },
    ) {
        val rows = results.statewide.map { row ->
            val name = if (row.candidateId == CandidateIds.MARSHALL) "Marshall" else "Hamilton"
            Triple("$name — ${formatVotes(row.votes)}", row.pct, palette.forCandidate(row.candidateId))
        }
        ShareBars(rows = rows, maxValue = 100.0)

        if (results.called && results.calledFor != null) {
            Spacer(Modifier.height(12.dp))
            Text(
                text = "Race called for ${results.calledFor}.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }

        Spacer(Modifier.height(8.dp))
        TextButton(onClick = onOpenResults) { Text("See all 105 counties") }
        Text(
            text = "Unofficial returns from the Kansas Secretary of State. " +
                "Updated every minute; refreshed ${formatAge(snapshot.ageMillis(DataFile.RESULTS, now))}.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
