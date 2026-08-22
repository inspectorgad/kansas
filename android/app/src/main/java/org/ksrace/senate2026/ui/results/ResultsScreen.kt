package org.ksrace.senate2026.ui.results

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.material3.FilterChip
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.data.DataFile
import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.data.model.CandidateIds
import org.ksrace.senate2026.data.model.CountyResult
import org.ksrace.senate2026.format.formatShare
import org.ksrace.senate2026.format.formatSigned
import org.ksrace.senate2026.format.formatVotes
import org.ksrace.senate2026.ui.components.AsOfLabel
import org.ksrace.senate2026.ui.components.EmptyState
import org.ksrace.senate2026.ui.components.HeroNumber
import org.ksrace.senate2026.ui.components.SectionCard
import org.ksrace.senate2026.ui.components.ShareBars
import org.ksrace.senate2026.ui.components.StatTile
import org.ksrace.senate2026.ui.components.ThinDivider
import org.ksrace.senate2026.ui.theme.LocalChartPalette
import org.ksrace.senate2026.ui.theme.TabularNumberStyle

private enum class CountySort(val label: String) {
    MARGIN("Margin"),
    VOTES("Votes"),
    NAME("County"),
}

/**
 * Election night.
 *
 * This is the only screen in the app that shows a real vote share, because
 * election night is the only time one exists. Everything else — polls, market
 * probabilities — is an estimate of this.
 *
 * The word "unofficial" appears on the screen rather than in a footnote. These
 * are county returns as reported on the night; the official canvass follows
 * weeks later and does move numbers.
 */
@Composable
fun ResultsScreen(
    snapshot: RaceSnapshot,
    now: Long,
    onNeedsPolling: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val palette = LocalChartPalette.current
    val results = snapshot.results
    var sort by rememberSaveable { mutableStateOf(CountySort.MARGIN) }

    LaunchedEffect(results?.isLive) {
        if (results?.isLive == true) onNeedsPolling()
    }

    if (results == null || !results.isLive) {
        EmptyState(
            message = "No results yet",
            detail = "Kansas begins reporting unofficial returns after polls close on " +
                "November 3. This screen will fill in as counties report.",
            modifier = modifier,
        )
        return
    }

    val leader = results.statewide.maxByOrNull { it.votes }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            SectionCard(
                title = if (results.status == "final") "Final unofficial results" else "Unofficial results",
                subtitle = results.pctReporting?.let { "${formatShare(it)}% of precincts reporting" }
                    ?: "Precinct count not reported",
            ) {
                if (leader != null && results.totalVotes > 0) {
                    val name = if (leader.candidateId == CandidateIds.MARSHALL) "Marshall" else "Hamilton"
                    val runnerUp = results.statewide.filter { it != leader }.maxByOrNull { it.votes }
                    val gap = runnerUp?.let { leader.pct - it.pct }
                    HeroNumber(
                        value = "$name ${formatShare(leader.pct)}%",
                        label = if (results.called) "Winner" else "Leading",
                        detail = gap?.let { "by ${formatShare(it)} points" },
                        caption = "Unofficial returns. The official canvass follows in the weeks " +
                            "after election day and can change these numbers.",
                    )
                    Spacer(Modifier.height(14.dp))
                }

                ShareBars(
                    rows = results.statewide.map { row ->
                        val name = if (row.candidateId == CandidateIds.MARSHALL) "Marshall" else "Hamilton"
                        Triple(
                            "$name — ${formatVotes(row.votes)}",
                            row.pct,
                            palette.forCandidate(row.candidateId),
                        )
                    },
                    maxValue = 100.0,
                )

                Spacer(Modifier.height(12.dp))
                ThinDivider()
                Spacer(Modifier.height(12.dp))
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    StatTile(
                        label = "Total votes",
                        value = formatVotes(results.totalVotes),
                        modifier = Modifier.weight(1f),
                    )
                    StatTile(
                        label = "Counties in",
                        value = "${results.counties.size} / 105",
                        modifier = Modifier.weight(1f),
                    )
                }

                Spacer(Modifier.height(8.dp))
                AsOfLabel(snapshot.ageMillis(DataFile.RESULTS, now), source = "Kansas SoS")
            }
        }

        if (results.called && results.calledFor != null) {
            item {
                SectionCard(title = "Race called") {
                    Text(
                        text = "Called for ${results.calledFor}.",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = "A call is a projection by the source, not a certified result.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (results.counties.isNotEmpty()) {
            item {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CountySort.entries.forEach { option ->
                        FilterChip(
                            selected = sort == option,
                            onClick = { sort = option },
                            label = { Text(option.label) },
                        )
                    }
                }
            }

            item {
                SectionCard(
                    title = "By county",
                    subtitle = "${results.counties.size} reporting",
                ) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        HeaderCell("County", Modifier.weight(1.4f))
                        HeaderCell("Marshall", Modifier.weight(1f))
                        HeaderCell("Hamilton", Modifier.weight(1f))
                        HeaderCell("Margin", Modifier.weight(0.9f))
                    }
                    Spacer(Modifier.height(6.dp))
                    ThinDivider()
                    Spacer(Modifier.height(6.dp))

                    sorted(results.counties, sort).forEach { county ->
                        CountyRow(county)
                    }
                }
            }
        }
    }
}

private fun sorted(counties: List<CountyResult>, sort: CountySort): List<CountyResult> = when (sort) {
    CountySort.MARGIN -> counties.sortedByDescending { it.marshallVotes - it.hamiltonVotes }
    CountySort.VOTES -> counties.sortedByDescending { it.totalVotes }
    CountySort.NAME -> counties.sortedBy { it.county }
}

@Composable
private fun HeaderCell(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text.uppercase(),
        modifier = modifier,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun CountyRow(county: CountyResult) {
    val margin = (county.marshallVotes - county.hamiltonVotes).toDouble()
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = county.county,
            modifier = Modifier.weight(1.4f),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface,
        )
        // Tabular figures here: these columns are read down, not across.
        Text(
            text = formatVotes(county.marshallVotes),
            modifier = Modifier.weight(1f),
            style = TabularNumberStyle,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = formatVotes(county.hamiltonVotes),
            modifier = Modifier.weight(1f),
            style = TabularNumberStyle,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            text = formatSigned(margin, decimals = 0),
            modifier = Modifier.weight(0.9f),
            style = TabularNumberStyle,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
    Spacer(Modifier.height(6.dp))
}
