package org.ksrace.senate2026.ui.news

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.data.DataFile
import org.ksrace.senate2026.data.RaceSnapshot
import org.ksrace.senate2026.data.model.NewsItem
import org.ksrace.senate2026.format.formatAge
import org.ksrace.senate2026.format.parseInstant
import org.ksrace.senate2026.ui.components.AsOfLabel
import org.ksrace.senate2026.ui.components.EmptyState
import org.ksrace.senate2026.ui.components.ThinDivider

/**
 * Coverage of the race.
 *
 * Headline, outlet and link only — tapping opens the publisher's own page. These
 * are working newsrooms, several of them paywalled, and reproducing their
 * reporting inside a third-party app would take their traffic while they carry
 * the cost of the journalism.
 */
@Composable
fun NewsScreen(snapshot: RaceSnapshot, now: Long, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val payload = snapshot.news

    if (payload == null || payload.items.isEmpty()) {
        EmptyState(
            message = "No coverage yet",
            detail = "Reporting on this race from Kansas newsrooms will appear here.",
            modifier = modifier,
        )
        return
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(0.dp),
    ) {
        items(payload.items.size) { index ->
            val item = payload.items[index]
            NewsRow(
                item = item,
                now = now,
                onOpen = {
                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(item.url))
                    try {
                        context.startActivity(intent)
                    } catch (_: ActivityNotFoundException) {
                        // No browser installed; nothing useful to fall back to.
                    }
                },
            )
            if (index < payload.items.lastIndex) {
                ThinDivider(Modifier.padding(horizontal = 16.dp))
            }
        }

        item {
            Spacer(Modifier.height(12.dp))
            Column(Modifier.padding(horizontal = 16.dp)) {
                AsOfLabel(snapshot.ageMillis(DataFile.NEWS, now))
                Text(
                    text = "Headlines link to the publisher. Sources: " +
                        payload.attribution.joinToString(", ") { it.name },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // Only worth explaining when some are on screen.
                val official = payload.items.count { it.isOfficial }
                if (official > 0) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = "$official of ${payload.items.size} items are marked " +
                            "Government source: published on an official .gov site rather " +
                            "than reported by a newsroom. An officeholder has a press " +
                            "operation and a challenger does not, so these do not fall " +
                            "evenly between the two candidates.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun NewsRow(item: NewsItem, now: Long, onOpen: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Text(
            text = item.title,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(4.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            // Coloured rather than grey, because this is the one piece of metadata
            // on the row that changes how the headline above it should be read.
            if (item.isOfficial) {
                Text(
                    text = "Government source",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary,
                )
                Text(
                    text = "·",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = item.source,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            val age = parseInstant(item.publishedAt)?.let { now - it.toEpochMilli() }
            if (age != null) {
                Text(
                    text = "· ${formatAge(age)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (item.mentions.size == 2) {
                Text(
                    text = "· both candidates",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        item.summary?.let { summary ->
            Spacer(Modifier.height(6.dp))
            Text(
                text = summary,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
