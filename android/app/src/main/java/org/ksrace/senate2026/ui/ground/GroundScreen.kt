package org.ksrace.senate2026.ui.ground

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
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.data.DataFile
import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.format.formatSigned
import org.ksrace.senate2026.format.formatVotes
import org.ksrace.senate2026.ui.components.AsOfLabel
import org.ksrace.senate2026.ui.components.EmptyState
import org.ksrace.senate2026.ui.components.SectionCard
import org.ksrace.senate2026.ui.components.ShareBars
import org.ksrace.senate2026.ui.components.StatTile
import org.ksrace.senate2026.ui.components.ThinDivider
import org.ksrace.senate2026.ui.theme.LocalChartPalette
import org.ksrace.senate2026.ui.theme.TabularNumberStyle

/**
 * Registration and early voting.
 *
 * The coverage caveat is stated before any number is shown, because this is the
 * screen most likely to be misread. Kansas publishes no statewide daily
 * early-vote feed, so advance figures cover only the counties running public
 * dashboards — five urban-leaning counties holding roughly half the state's
 * voters. Read as a state sample, they would point the wrong way.
 */
@Composable
fun GroundScreen(snapshot: RaceSnapshot, now: Long, modifier: Modifier = Modifier) {
    val palette = LocalChartPalette.current
    val ground = snapshot.ground

    val registration = ground?.registration
    val advance = ground?.advanceBallots

    if (ground == null || (registration?.byCounty.isNullOrEmpty() && advance?.counties.isNullOrEmpty())) {
        EmptyState(
            message = "No ground-game data yet",
            detail = "Voter registration figures and, closer to election day, advance-ballot " +
                "returns will appear here.",
            modifier = modifier,
        )
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        registration?.statewide?.let { statewide ->
            item {
                SectionCard(
                    title = "Registered voters",
                    subtitle = "Statewide",
                ) {
                    ShareBars(
                        rows = listOf(
                            Triple("Republican", statewide.republican.toDouble(), palette.marshall),
                            Triple("Democratic", statewide.democrat.toDouble(), palette.hamilton),
                            Triple(
                                "Unaffiliated",
                                statewide.unaffiliated.toDouble(),
                                MaterialTheme.colorScheme.onSurfaceVariant,
                            ),
                        ),
                        valueLabel = { formatVotes(it.toInt()) },
                    )
                    Spacer(Modifier.height(12.dp))
                    ThinDivider()
                    Spacer(Modifier.height(12.dp))
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        StatTile(
                            label = "Total",
                            value = formatVotes(statewide.total),
                            modifier = Modifier.weight(1f),
                        )
                        StatTile(
                            label = "R − D gap",
                            value = formatSigned(statewide.partyGap.toDouble(), decimals = 0),
                            caption = "registrations",
                            modifier = Modifier.weight(1f),
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "Registration is not a vote. Kansas has elected Democrats " +
                            "statewide while carrying a large Republican registration edge.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(4.dp))
                    AsOfLabel(snapshot.ageMillis(DataFile.GROUND, now), source = "Kansas SoS")
                }
            }
        }

        if (advance != null && advance.counties.isNotEmpty()) {
            item {
                SectionCard(
                    title = "Advance ballots",
                    subtitle = "${advance.countiesCovered.size} counties covered",
                ) {
                    Text(
                        text = advance.coverageNote,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))

                    val returned = advance.counties.mapNotNull { it.mailBallotsReturned }.sum()
                    val inPerson = advance.counties.mapNotNull { it.inPersonVotes }.sum()
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        StatTile(
                            label = "Mail returned",
                            value = formatVotes(returned),
                            modifier = Modifier.weight(1f),
                        )
                        StatTile(
                            label = "In person",
                            value = formatVotes(inPerson),
                            modifier = Modifier.weight(1f),
                        )
                    }

                    Spacer(Modifier.height(12.dp))
                    ThinDivider()
                    Spacer(Modifier.height(8.dp))

                    advance.counties.forEach { county ->
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    text = "${county.county} County",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                Text(
                                    text = listOfNotNull(
                                        county.mailBallotsSent?.let { "${formatVotes(it)} mailed" },
                                        county.mailBallotsReturned?.let { "${formatVotes(it)} returned" },
                                        county.inPersonVotes?.let { "${formatVotes(it)} in person" },
                                    ).joinToString(" · ").ifEmpty { "no figures published" },
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(
                                text = county.totalAdvance?.let { formatVotes(it) } ?: "—",
                                style = TabularNumberStyle,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                }
            }
        }

        if (registration != null && registration.byCounty.isNotEmpty()) {
            item {
                SectionCard(
                    title = "Registration by county",
                    subtitle = "${registration.byCounty.size} counties",
                ) {
                    registration.byCounty
                        .sortedByDescending { it.total }
                        .take(20)
                        .forEach { county ->
                            Row(
                                Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    text = county.county,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurface,
                                    modifier = Modifier.weight(1f),
                                )
                                Text(
                                    text = formatSigned(county.partyGap.toDouble(), decimals = 0),
                                    style = TabularNumberStyle,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                            Spacer(Modifier.height(6.dp))
                        }
                    Text(
                        text = "Figures are the Republican minus Democratic registration gap. " +
                            "The twenty largest counties are shown.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
