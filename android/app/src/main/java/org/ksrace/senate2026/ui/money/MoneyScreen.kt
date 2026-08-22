package org.ksrace.senate2026.ui.money

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
import org.ksrace.senate2026.data.model.CandidateFinance
import org.ksrace.senate2026.data.model.CandidateIds
import org.ksrace.senate2026.format.formatDollars
import org.ksrace.senate2026.format.formatIsoDate
import org.ksrace.senate2026.format.formatShare
import org.ksrace.senate2026.format.formatShortDollars
import org.ksrace.senate2026.ui.components.AsOfLabel
import org.ksrace.senate2026.ui.components.EmptyState
import org.ksrace.senate2026.ui.components.SectionCard
import org.ksrace.senate2026.ui.components.ShareBars
import org.ksrace.senate2026.ui.components.StatTile
import org.ksrace.senate2026.ui.components.ThinDivider
import org.ksrace.senate2026.ui.theme.LocalChartPalette
import org.ksrace.senate2026.ui.theme.TabularNumberStyle

/**
 * The money.
 *
 * Outside spending is given the same prominence as the campaigns' own filings.
 * In a race projected around $50 million, independent expenditures are often the
 * larger half, and a tracker that buried them would understate the money by a
 * wide margin.
 *
 * Every figure is labelled with the reporting period it comes from. FEC filings
 * are periodic, so a candidate total can be months old while outside-spending
 * notices arrive within 24 hours — showing them side by side without saying so
 * would invite a false comparison.
 */
@Composable
fun MoneyScreen(snapshot: RaceSnapshot, now: Long, modifier: Modifier = Modifier) {
    val palette = LocalChartPalette.current
    val finance = snapshot.finance

    if (finance == null || finance.candidates.isEmpty()) {
        EmptyState(
            message = "No filings yet",
            detail = "Campaign finance figures appear after the first FEC report of the cycle.",
            modifier = modifier,
        )
        return
    }

    val marshall = finance.candidates[CandidateIds.MARSHALL]
    val hamilton = finance.candidates[CandidateIds.HAMILTON]
    val outside = finance.outsideSpending

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            SectionCard(
                title = "Raised this cycle",
                subtitle = coverageNote(marshall, hamilton),
            ) {
                ShareBars(
                    rows = listOfNotNull(
                        marshall?.let { Triple("Marshall", it.totalReceipts, palette.marshall) },
                        hamilton?.let { Triple("Hamilton", it.totalReceipts, palette.hamilton) },
                    ),
                    valueLabel = { formatShortDollars(it) },
                )
                Spacer(Modifier.height(12.dp))
                ThinDivider()
                Spacer(Modifier.height(12.dp))
                ShareBars(
                    rows = listOfNotNull(
                        marshall?.let { Triple("Marshall cash on hand", it.cashOnHand, palette.marshall) },
                        hamilton?.let { Triple("Hamilton cash on hand", it.cashOnHand, palette.hamilton) },
                    ),
                    valueLabel = { formatShortDollars(it) },
                )
                Spacer(Modifier.height(8.dp))
                AsOfLabel(snapshot.ageMillis(DataFile.FINANCE, now), source = "FEC")
            }
        }

        marshall?.let { item { CandidateDetail("Roger Marshall", it) } }
        hamilton?.let { item { CandidateDetail("Adam Hamilton", it) } }

        if (outside.total > 0) {
            item {
                SectionCard(
                    title = "Outside spending",
                    subtitle = "Independent expenditures — not controlled by either campaign",
                ) {
                    StatTile(
                        label = "Total reported",
                        value = formatShortDollars(outside.total),
                    )
                    Spacer(Modifier.height(12.dp))

                    val forMarshall = outside.supporting[CandidateIds.MARSHALL] ?: 0.0
                    val againstMarshall = outside.opposing[CandidateIds.MARSHALL] ?: 0.0
                    val forHamilton = outside.supporting[CandidateIds.HAMILTON] ?: 0.0
                    val againstHamilton = outside.opposing[CandidateIds.HAMILTON] ?: 0.0

                    ShareBars(
                        rows = listOf(
                            Triple("Supporting Marshall", forMarshall, palette.marshall),
                            Triple("Opposing Marshall", againstMarshall, palette.hamilton),
                            Triple("Supporting Hamilton", forHamilton, palette.hamilton),
                            Triple("Opposing Hamilton", againstHamilton, palette.marshall),
                        ),
                        valueLabel = { formatShortDollars(it) },
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "Bars are coloured by which side the money helps, so an " +
                            "\"opposing\" bar carries the opponent's colour.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            if (outside.topSpenders.isNotEmpty()) {
                item {
                    SectionCard(title = "Biggest outside spenders") {
                        outside.topSpenders.take(10).forEachIndexed { index, spender ->
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
                                        text = spender.committeeName,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurface,
                                    )
                                    Text(
                                        text = spenderStance(spender.supports, spender.opposes),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Text(
                                    text = formatShortDollars(spender.amount),
                                    style = TabularNumberStyle,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                        }
                    }
                }
            }
        }

        if (finance.filings.isNotEmpty()) {
            item {
                SectionCard(title = "Recent filings") {
                    finance.filings.take(10).forEachIndexed { index, filing ->
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
                                    text = filing.committeeName,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                                Text(
                                    text = listOfNotNull(
                                        filing.formType,
                                        filing.reportType,
                                        formatIsoDate(filing.date),
                                    ).joinToString(" · "),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            filing.totalReceipts?.let { amount ->
                                Text(
                                    text = formatShortDollars(amount),
                                    style = TabularNumberStyle,
                                    color = MaterialTheme.colorScheme.onSurface,
                                )
                            }
                        }
                    }
                }
            }
        }

        item {
            Text(
                text = "Source: Federal Election Commission. Candidate totals are as of the " +
                    "last periodic report and can be months old; outside-spending notices are " +
                    "filed within 24 to 48 hours.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CandidateDetail(name: String, finance: CandidateFinance) {
    SectionCard(
        title = name,
        subtitle = finance.committeeName,
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            StatTile(
                label = "Spent",
                value = formatShortDollars(finance.totalDisbursements),
                modifier = Modifier.weight(1f),
            )
            StatTile(
                label = "On hand",
                value = formatShortDollars(finance.cashOnHand),
                modifier = Modifier.weight(1f),
            )
            finance.burnRateMonthly?.let { burn ->
                StatTile(
                    label = "Burn / month",
                    value = formatShortDollars(burn),
                    caption = "cycle average",
                    modifier = Modifier.weight(1f),
                )
            }
        }

        Spacer(Modifier.height(12.dp))
        ThinDivider()
        Spacer(Modifier.height(12.dp))

        DetailRow("From individuals", formatDollars(finance.individualContributions))
        finance.smallDollarContributions?.let {
            DetailRow("Small donors (unitemized, under \$200)", formatDollars(it))
        }
        DetailRow("From PACs", formatDollars(finance.pacContributions))
        finance.inStatePct?.let { pct ->
            DetailRow(
                "From Kansas",
                "${formatShare(pct)}% of itemized individual donations",
            )
        }
        if (finance.debtsOwed > 0) {
            DetailRow("Debts owed", formatDollars(finance.debtsOwed))
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = TabularNumberStyle,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
    Spacer(Modifier.height(6.dp))
}

private fun spenderStance(supports: String?, opposes: String?): String {
    val supporting = supports?.let { "supports ${it.replaceFirstChar(Char::titlecase)}" }
    val opposing = opposes?.let { "opposes ${it.replaceFirstChar(Char::titlecase)}" }
    return listOfNotNull(supporting, opposing).joinToString(", ").ifEmpty { "unattributed" }
}

private fun coverageNote(vararg records: CandidateFinance?): String? {
    val dates = records.filterNotNull().mapNotNull { it.coverageEndDate }.distinct()
    val formatted = dates.mapNotNull { formatIsoDate(it) }
    return when {
        formatted.isEmpty() -> null
        formatted.size == 1 -> "Through ${formatted.first()}"
        // Different reporting periods are not comparable without saying so.
        else -> "Through ${formatted.joinToString(" / ")} (different reporting periods)"
    }
}
