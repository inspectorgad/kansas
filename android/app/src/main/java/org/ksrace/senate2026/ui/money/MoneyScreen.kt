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
import org.ksrace.senate2026.data.model.DonorDetail
import org.ksrace.senate2026.data.model.DonorGroup
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

        marshall?.let { record ->
            item { CandidateDetail("Roger Marshall", record) }
            record.donors?.takeIf { it.hasAnything }?.let { donors ->
                item { DonorMix("Roger Marshall", donors) }
                if (donors.largeDonors.isNotEmpty()) {
                    item { LargestDonors("Roger Marshall", donors) }
                }
                if (donors.committeeDonors.isNotEmpty()) {
                    item { CommitteeDonors("Roger Marshall", record, donors) }
                }
            }
            if (record.donorStates.isNotEmpty()) {
                item { DonorStates("Roger Marshall", record) }
            }
            if (record.affiliatedCommittees.isNotEmpty()) {
                item { AffiliatedCommittees("Roger Marshall", record) }
            }
        }
        hamilton?.let { record ->
            item { CandidateDetail("Adam Hamilton", record) }
            record.donors?.takeIf { it.hasAnything }?.let { donors ->
                item { DonorMix("Adam Hamilton", donors) }
                if (donors.largeDonors.isNotEmpty()) {
                    item { LargestDonors("Adam Hamilton", donors) }
                }
                if (donors.committeeDonors.isNotEmpty()) {
                    item { CommitteeDonors("Adam Hamilton", record, donors) }
                }
            }
            if (record.donorStates.isNotEmpty()) {
                item { DonorStates("Adam Hamilton", record) }
            }
            if (record.affiliatedCommittees.isNotEmpty()) {
                item { AffiliatedCommittees("Adam Hamilton", record) }
            }
        }

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

/**
 * Where one campaign's money comes from, in aggregate.
 *
 * The itemization caveat is the card's subtitle rather than a footnote, because
 * it is not a disclaimer — it changes what the numbers mean. Donors are named
 * only above $200 for the cycle, so a named list describes a campaign's larger
 * givers and under-represents a small-dollar campaign the most. In this race that
 * cuts one way: Hamilton raises about 70% of his money in state on a small-dollar
 * profile, so his named donors cover a smaller share of his total than Marshall's
 * do of his. Putting the two lists side by side without saying that would invite
 * exactly the wrong comparison.
 */
@Composable
private fun DonorMix(name: String, donors: DonorDetail) {
    SectionCard(
        title = "Who funds $name",
        subtitle = donors.itemizedNote,
    ) {
        val itemized = donors.itemizedTotal
        val unitemized = donors.unitemizedTotal
        if (itemized != null || unitemized != null) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                unitemized?.let {
                    StatTile(
                        label = "Under \$200",
                        value = formatShortDollars(it),
                        caption = "no names disclosed",
                        modifier = Modifier.weight(1f),
                    )
                }
                itemized?.let {
                    StatTile(
                        label = "Itemized",
                        value = formatShortDollars(it),
                        caption = "donors named",
                        modifier = Modifier.weight(1f),
                    )
                }
            }
            val total = (itemized ?: 0.0) + (unitemized ?: 0.0)
            if (total > 0 && unitemized != null) {
                Spacer(Modifier.height(8.dp))
                Text(
                    text = "${formatShare(unitemized / total * 100.0)}% of individual money " +
                        "came from donors too small to name.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(12.dp))
            ThinDivider()
            Spacer(Modifier.height(12.dp))
        }

        GroupList("Top employers", donors.topEmployers)
        GroupList("Top occupations", donors.topOccupations)
        GroupList(
            "Where the large money is",
            donors.topCities,
            note = "Cities ranked by donations of \$1,000 or more only — the FEC " +
                "groups all giving by state and ZIP, never by city.",
        )
    }
}

@Composable
private fun GroupList(heading: String, groups: List<DonorGroup>, note: String? = null) {
    if (groups.isEmpty()) return
    Text(
        text = heading,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurface,
    )
    Spacer(Modifier.height(6.dp))
    groups.take(6).forEach { group ->
        DetailRow(
            label = group.label,
            value = formatShortDollars(group.amount),
        )
    }
    note?.let {
        Text(
            text = it,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    Spacer(Modifier.height(12.dp))
}

/**
 * Named individuals, largest first.
 *
 * These are public record — federal law requires the disclosure — but the FEC's
 * sale-or-use restriction forbids using contributor information to solicit
 * contributions or for any commercial purpose, so the card says so rather than
 * leaving a reader to assume this is a mailing list.
 */
@Composable
private fun LargestDonors(name: String, donors: DonorDetail) {
    SectionCard(
        title = "$name's largest donors",
        subtitle = donors.largeDonorCoverage,
    ) {
        donors.largeDonors.forEachIndexed { index, donor ->
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
                        text = donor.name,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    val detail = listOfNotNull(
                        donor.place,
                        donor.occupation?.takeIf { it.isNotBlank() },
                        donor.employer?.takeIf { it.isNotBlank() },
                    ).joinToString(" · ")
                    if (detail.isNotEmpty()) {
                        Text(
                            text = detail,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Column {
                    Text(
                        text = formatDollars(donor.amount),
                        style = TabularNumberStyle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    if (donor.gifts > 1) {
                        Text(
                            text = "${donor.gifts} gifts",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        Text(
            text = "Public record under federal disclosure. FEC rules forbid using " +
                "contributor information to solicit contributions or for commercial " +
                "purposes.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * Organizations giving directly to a campaign.
 *
 * A separate card from the individuals rather than one merged list, because the
 * split between the two is the most striking thing in this data: committee money
 * is 37% of Marshall's receipts and under 1% of Hamilton's. Merging them would
 * bury exactly the comparison worth making.
 *
 * A transfer is labelled, because it is not a donation — it is the candidate
 * moving money in from another committee of their own, and Marshall's $638,753
 * from an earlier committee would otherwise read as somebody's generosity.
 */
@Composable
private fun CommitteeDonors(name: String, finance: CandidateFinance, donors: DonorDetail) {
    val organizational = finance.pacContributions + finance.partyContributions
    val share = if (finance.totalReceipts > 0) {
        organizational / finance.totalReceipts * 100.0
    } else {
        0.0
    }
    // Grouped, and each group carries what the FEC says the whole category came
    // to. Ranking across all of them put six large transfers at the top and left
    // thirteen PACs standing in for two hundred.
    val groups = listOf(
        Triple("Political action committees", "pac", finance.pacContributions),
        Triple("Committee transfers", "transfer", finance.transfersIn),
        Triple("Party committees", "party", finance.partyContributions),
    )

    SectionCard(
        title = "$name's organizational donors",
        subtitle = "${formatDollars(organizational)} from committees and parties, " +
            "${formatShare(share)}% of everything raised",
    ) {
        groups.forEach { (heading, kind, reported) ->
            val rows = donors.committeeDonors.filter { it.kind == kind }
            if (rows.isEmpty()) return@forEach

            Spacer(Modifier.height(4.dp))
            Text(
                text = heading,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                // Capped lists say so. An uncapped one is everything there is, and
                // claiming "12 largest of X" when 3 exist would invent a remainder.
                text = if (rows.size >= 12) {
                    "${rows.size} largest · ${formatDollars(rows.sumOf { it.amount })} " +
                        "of ${formatDollars(reported)} reported"
                } else {
                    formatDollars(rows.sumOf { it.amount })
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(6.dp))

            rows.forEach { donor ->
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = donor.name,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        text = formatDollars(donor.amount),
                        style = TabularNumberStyle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                Spacer(Modifier.height(4.dp))
            }
            Spacer(Modifier.height(4.dp))
            ThinDivider()
        }

        Spacer(Modifier.height(12.dp))
        Text(
            text = donors.committeeDonorNote,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * Committees the candidate controls beyond the campaign itself.
 *
 * Marshall has a leadership PAC whose money appears in none of his campaign
 * totals. Hamilton, holding no office, has only the campaign. Showing the
 * campaign alone would make the incumbent's operation look smaller than it is.
 */
@Composable
private fun AffiliatedCommittees(name: String, finance: CandidateFinance) {
    SectionCard(
        title = "$name's other committees",
        subtitle = "Separate from the campaign. None of this money is in the totals above.",
    ) {
        finance.affiliatedCommittees.forEachIndexed { index, committee ->
            if (index > 0) {
                Spacer(Modifier.height(8.dp))
                ThinDivider()
                Spacer(Modifier.height(8.dp))
            }
            Text(
                text = committee.name,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = committee.designationFull ?: committee.designation ?: "Committee",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (committee.receipts != null || committee.cashOnHand != null) {
                Spacer(Modifier.height(8.dp))
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    committee.receipts?.let {
                        StatTile(
                            label = "Raised",
                            value = formatShortDollars(it),
                            modifier = Modifier.weight(1f),
                        )
                    }
                    committee.disbursements?.let {
                        StatTile(
                            label = "Spent",
                            value = formatShortDollars(it),
                            modifier = Modifier.weight(1f),
                        )
                    }
                    committee.cashOnHand?.let {
                        StatTile(
                            label = "On hand",
                            value = formatShortDollars(it),
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        }
    }
}

/**
 * Where a campaign's itemized money comes from, by state.
 *
 * The share is of money that can be located, not of everything raised: Schedule A
 * carries itemized receipts, and the FEC never records a state for an unitemized
 * donation. The footnote says how much is unplaced rather than letting the
 * percentages imply a completeness they do not have.
 */
@Composable
private fun DonorStates(name: String, finance: CandidateFinance) {
    val states = finance.donorStates
    val located = states.sumOf { it.amount }
    val shown = states.take(8)

    SectionCard(
        title = "Where $name's money comes from",
        subtitle = "${states.size} states and territories",
    ) {
        shown.forEachIndexed { index, entry ->
            if (index > 0) Spacer(Modifier.height(8.dp))
            val home = entry.state == "KS"
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = entry.label,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (home) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    },
                )
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(
                        text = "${formatShare(entry.pct)}%",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = formatDollars(entry.amount),
                        style = TabularNumberStyle,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }

        if (states.size > shown.size) {
            val rest = states.drop(shown.size)
            Spacer(Modifier.height(8.dp))
            ThinDivider()
            Spacer(Modifier.height(8.dp))
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "${rest.size} more",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = formatDollars(rest.sumOf { it.amount }),
                    style = TabularNumberStyle,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Spacer(Modifier.height(12.dp))
        val unplaced = finance.individualContributions - located
        Text(
            text = if (unplaced > 0) {
                "Itemized individual donations only. A further " +
                    "${formatDollars(unplaced)} came from donors under the \$200 " +
                    "disclosure floor, whose state is never recorded."
            } else {
                "Itemized individual donations only."
            },
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
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
        if (finance.partyContributions > 0) {
            DetailRow("From party committees", formatDollars(finance.partyContributions))
        }
        if (finance.transfersIn > 0) {
            // Not a donation: the candidate moving money in from a committee of
            // their own. Listed with the receipts because the FEC counts it as
            // one, named plainly because nobody gave it.
            DetailRow(
                "Transferred from own committee",
                formatDollars(finance.transfersIn),
            )
        }
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
