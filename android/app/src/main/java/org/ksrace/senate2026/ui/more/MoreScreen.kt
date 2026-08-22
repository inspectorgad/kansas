package org.ksrace.senate2026.ui.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.ui.components.ThinDivider

/** Where the app puts the trackers that do not earn a permanent tab. */
enum class MoreDestination(val title: String, val subtitle: String) {
    RESULTS("Election night results", "County-by-county returns"),
    ADS("Advertising", "Broadcast buys and digital spend"),
    GROUND("Registration and early voting", "Party registration and advance ballots"),
    SETTINGS("Sources and settings", "Where the numbers come from"),
}

@Composable
fun MoreScreen(
    snapshot: RaceSnapshot,
    onOpen: (MoreDestination) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth()) {
        MoreDestination.entries.forEach { destination ->
            val subtitle = when (destination) {
                // Results are the headline on election night and dormant before
                // it; saying which avoids a dead-looking row for months.
                MoreDestination.RESULTS -> if (snapshot.resultsAreLive) {
                    "Counting now"
                } else {
                    "Opens when counting begins on November 3"
                }
                MoreDestination.ADS -> destination.subtitle
                MoreDestination.GROUND -> destination.subtitle
                MoreDestination.SETTINGS -> destination.subtitle
            }

            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable { onOpen(destination) }
                    .padding(horizontal = 16.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        text = destination.title,
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Icon(
                    imageVector = Icons.Filled.ChevronRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            ThinDivider(Modifier.padding(horizontal = 16.dp))
        }
        Spacer(Modifier.height(16.dp))
    }
}
