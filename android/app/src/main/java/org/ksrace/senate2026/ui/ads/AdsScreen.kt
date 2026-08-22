package org.ksrace.senate2026.ui.ads

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
import org.ksrace.senate2026.data.model.CandidateIds
import org.ksrace.senate2026.format.formatIsoDate
import org.ksrace.senate2026.format.formatShortDollars
import org.ksrace.senate2026.ui.components.AsOfLabel
import org.ksrace.senate2026.ui.components.EmptyState
import org.ksrace.senate2026.ui.components.SectionCard
import org.ksrace.senate2026.ui.components.Series
import org.ksrace.senate2026.ui.components.ShareBars
import org.ksrace.senate2026.ui.components.StatTile
import org.ksrace.senate2026.ui.components.ThinDivider
import org.ksrace.senate2026.ui.components.TrendChart
import org.ksrace.senate2026.ui.theme.LocalChartPalette
import org.ksrace.senate2026.ui.theme.TabularNumberStyle

/**
 * Advertising.
 *
 * The caveat here is load-bearing enough to sit at the top of the screen rather
 * than in a footnote: these are broadcast filings only. Cable, streaming, digital
 * and mail do not appear in the FCC's political file, so the totals are a floor
 * on what is being spent, not a measure of it.
 */
@Composable
fun AdsScreen(snapshot: RaceSnapshot, now: Long, modifier: Modifier = Modifier) {
    val palette = LocalChartPalette.current
    val ads = snapshot.ads

    if (ads == null || (ads.broadcast.filings.isEmpty() && !ads.digital.available)) {
        EmptyState(
            message = "No ad buys recorded yet",
            detail = "Broadcast filings from Kansas stations will appear here as they are posted " +
                "to the FCC's political file.",
            modifier = modifier,
        )
        return
    }

    val broadcast = ads.broadcast

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text(
                text = "Broadcast television and radio only. Cable, streaming, digital and mail " +
                    "are not in the FCC's political file, so these figures are a floor on total " +
                    "spending rather than a measure of it.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (broadcast.total > 0) {
            item {
                SectionCard(title = "Reported broadcast spending") {
                    StatTile(label = "Total", value = formatShortDollars(broadcast.total))
                    Spacer(Modifier.height(12.dp))
                    ShareBars(
                        rows = listOfNotNull(
                            broadcast.totalBySide[CandidateIds.MARSHALL]?.let {
                                Triple("Marshall campaign", it, palette.marshall)
                            },
                            broadcast.totalBySide[CandidateIds.HAMILTON]?.let {
                                Triple("Hamilton campaign", it, palette.hamilton)
                            },
                            broadcast.totalBySide["outside"]?.let {
                                Triple("Outside groups", it, MaterialTheme.colorScheme.onSurfaceVariant)
                            },
                        ),
                        valueLabel = { formatShortDollars(it) },
                    )
                    broadcast.totalBySide["unattributed"]?.let { amount ->
                        Spacer(Modifier.height(10.dp))
                        Text(
                            text = "${formatShortDollars(amount)} could not be attributed to " +
                                "either side. Station filings name the advertiser, and a group's " +
                                "name often does not say who it helps.",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    AsOfLabel(snapshot.ageMillis(DataFile.ADS, now), source = "FCC")
                }
            }
        }

        if (broadcast.byWeek.size >= 3) {
            item {
                SectionCard(
                    title = "Spending by week",
                    subtitle = "By flight start date",
                ) {
                    TrendChart(
                        series = listOf(
                            Series(
                                label = "Marshall",
                                color = palette.marshall,
                                values = broadcast.byWeek.map { it.marshall },
                            ),
                            Series(
                                label = "Hamilton",
                                color = palette.hamilton,
                                values = broadcast.byWeek.map { it.hamilton },
                            ),
                        ),
                        startLabel = formatIsoDate(broadcast.byWeek.first().weekStart),
                        endLabel = formatIsoDate(broadcast.byWeek.last().weekStart),
                    )
                }
            }
        }

        if (broadcast.byMarket.isNotEmpty()) {
            item {
                SectionCard(title = "By media market") {
                    broadcast.byMarket.sortedByDescending { it.total }.forEach { market ->
                        Text(
                            text = market.market,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Spacer(Modifier.height(4.dp))
                        ShareBars(
                            rows = listOf(
                                Triple("Marshall", market.marshall, palette.marshall),
                                Triple("Hamilton", market.hamilton, palette.hamilton),
                            ),
                            valueLabel = { formatShortDollars(it) },
                        )
                        Spacer(Modifier.height(12.dp))
                    }
                }
            }
        }

        item {
            SectionCard(
                title = "Digital",
                subtitle = if (ads.digital.available) "Meta Ad Library" else null,
            ) {
                if (!ads.digital.available) {
                    Text(
                        text = ads.digital.unavailableReason
                            ?: "Digital ad spending is not being collected.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    ShareBars(
                        rows = listOfNotNull(
                            ads.digital.totalBySide[CandidateIds.MARSHALL]?.let {
                                Triple("Marshall", it, palette.marshall)
                            },
                            ads.digital.totalBySide[CandidateIds.HAMILTON]?.let {
                                Triple("Hamilton", it, palette.hamilton)
                            },
                        ),
                        valueLabel = { formatShortDollars(it) },
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "Meta reports spending as a range, not a figure. These are range " +
                            "midpoints and are estimates.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (broadcast.filings.isNotEmpty()) {
            item {
                SectionCard(
                    title = "Recent filings",
                    subtitle = "${broadcast.filings.size} on file",
                ) {
                    broadcast.filings.take(25).forEachIndexed { index, filing ->
                        if (index > 0) {
                            Spacer(Modifier.height(8.dp))
                            ThinDivider()
                            Spacer(Modifier.height(8.dp))
                        }
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    text = filing.advertiser,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                Text(
                                    text = listOfNotNull(
                                        filing.station,
                                        filing.market,
                                        formatIsoDate(filing.flightStart),
                                        if (filing.isOutsideGroup) "outside group" else null,
                                    ).joinToString(" · "),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(
                                text = filing.amount?.let { formatShortDollars(it) } ?: "—",
                                style = TabularNumberStyle,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                    }
                }
            }
        }
    }
}
