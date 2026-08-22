package org.ksrace.senate2026.ui.settings

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.data.DataFile
import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.format.formatAge
import org.ksrace.senate2026.ui.components.SectionCard
import org.ksrace.senate2026.ui.components.ThinDivider
import org.ksrace.senate2026.work.RefreshWorker

/**
 * Settings, and the app's own accounting of itself.
 *
 * The sources section is not decoration. An election tracker that will not say
 * where its numbers came from is asking to be trusted on faith, so every source
 * the current data drew on is listed with its licence, and every file's real age
 * is shown — including the ones that failed to refresh.
 */
@Composable
fun SettingsScreen(
    snapshot: RaceSnapshot,
    now: Long,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val prefs = remember {
        context.getSharedPreferences(RefreshWorker.PREFS, Context.MODE_PRIVATE)
    }
    var notificationsEnabled by remember {
        mutableStateOf(prefs.getBoolean(RefreshWorker.KEY_NOTIFICATIONS_ENABLED, true))
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            SectionCard(title = "Notifications") {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            text = "Alert me to changes",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = "New polls, market moves over five points, new FEC filings, " +
                                "rating changes, and results on election night.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(
                        checked = notificationsEnabled,
                        onCheckedChange = { enabled ->
                            notificationsEnabled = enabled
                            prefs.edit()
                                .putBoolean(RefreshWorker.KEY_NOTIFICATIONS_ENABLED, enabled)
                                .apply()
                        },
                    )
                }
            }
        }

        item {
            SectionCard(
                title = "Data",
                subtitle = "Collected every 20 minutes; the app checks about every 15",
            ) {
                DataFile.core.forEach { file ->
                    val age = snapshot.ageMillis(file, now)
                    val problem = snapshot.problems[file]
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            text = file.fileName.removeSuffix(".json"),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            // A failure is shown next to the age, not instead of
                            // it: the number on screen is still the last good one.
                            text = if (problem != null) {
                                "${formatAge(age)} · ${problem}"
                            } else {
                                formatAge(age)
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(6.dp))
                }
                Spacer(Modifier.height(4.dp))
                TextButton(onClick = onRefresh) { Text("Refresh now") }
            }
        }

        item {
            SectionCard(
                title = "Sources",
                subtitle = "Where every figure in this app comes from",
            ) {
                val credits = buildList {
                    addAll(snapshot.polls?.attribution.orEmpty())
                    addAll(snapshot.markets?.attribution.orEmpty())
                    addAll(snapshot.finance?.attribution.orEmpty())
                    addAll(snapshot.news?.attribution.orEmpty())
                    addAll(snapshot.ads?.attribution.orEmpty())
                    addAll(snapshot.ground?.attribution.orEmpty())
                    addAll(snapshot.results?.attribution.orEmpty())
                }.distinctBy { it.url }

                if (credits.isEmpty()) {
                    Text(
                        text = "No data has loaded yet.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                credits.forEachIndexed { index, credit ->
                    if (index > 0) {
                        Spacer(Modifier.height(8.dp))
                        ThinDivider()
                        Spacer(Modifier.height(8.dp))
                    }
                    Text(
                        text = credit.name,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    listOfNotNull(credit.license, credit.note).forEach { line ->
                        Text(
                            text = line,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }

        item {
            SectionCard(title = "What this app does not know") {
                listOf(
                    "There is no live vote share before election night. Polls arrive a few per " +
                        "week; only the market probability updates continuously, and that is a " +
                        "probability of winning, not a share of the vote.",
                    "The polling average describes polls. It is not a forecast, and it does not " +
                        "model turnout or the systematic polling error seen in recent cycles.",
                    "Advance-ballot coverage is partial — the counties with public dashboards " +
                        "only, which lean more urban than the state.",
                    "Ad spending is a floor. The FCC political file covers broadcast; cable, " +
                        "streaming, digital and mail largely do not appear.",
                ).forEachIndexed { index, line ->
                    if (index > 0) Spacer(Modifier.height(8.dp))
                    Text(
                        text = "· $line",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        item {
            SectionCard(title = "About") {
                Text(
                    text = "An independent tracker of the 2026 Kansas U.S. Senate race. Not " +
                        "affiliated with either campaign, any election authority, or any news " +
                        "organisation.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
