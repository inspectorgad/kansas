package org.ksrace.senate2026.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import org.ksrace.senate2026.format.formatShare
import org.ksrace.senate2026.ui.theme.LocalChartPalette

/**
 * Chart primitives.
 *
 * The Canvas draws geometry only — every label, tick and legend entry is a real
 * composable outside it. That keeps text at the platform's own scaling and
 * accessibility settings, and it means the axis band cannot be clipped by a
 * fixed canvas height, which is the classic way a chart card ends up with its
 * date labels cropped.
 *
 * Marks follow the house spec: 2px lines, solid hairline grid one shade off the
 * surface (never dashed), translucent band fill, and direct labels only at the
 * endpoint rather than a number on every point.
 */

private const val LINE_WIDTH_DP = 2f
private const val GRID_WIDTH_DP = 1f

/** One series for the trend chart. */
data class Series(
    val label: String,
    val color: Color,
    val values: List<Double>,
    /** Half-width of the uncertainty ribbon at each point, in the same units. */
    val band: List<Double>? = null,
)

/**
 * A time-series line chart with an optional uncertainty ribbon.
 *
 * Both candidate lines share one y-axis. There is deliberately no second axis:
 * two scales on one chart is the single most misleading thing a chart can do,
 * and here both series are already in the same unit (percentage points).
 */
@Composable
fun TrendChart(
    series: List<Series>,
    modifier: Modifier = Modifier,
    height: Dp = 180.dp,
    gridLines: Int = 4,
    startLabel: String? = null,
    endLabel: String? = null,
) {
    val palette = LocalChartPalette.current
    val populated = series.filter { it.values.isNotEmpty() }
    if (populated.isEmpty()) return

    // Scale to the data plus any ribbon, padded so lines never touch the edge.
    val lows = populated.map { s ->
        s.values.indices.minOf { i -> s.values[i] - (s.band?.getOrNull(i) ?: 0.0) }
    }
    val highs = populated.map { s ->
        s.values.indices.maxOf { i -> s.values[i] + (s.band?.getOrNull(i) ?: 0.0) }
    }
    val rawMin = lows.min()
    val rawMax = highs.max()
    val pad = ((rawMax - rawMin) * 0.12).coerceAtLeast(0.5)
    val minY = rawMin - pad
    val maxY = rawMax + pad
    val span = (maxY - minY).coerceAtLeast(0.001)

    val description = populated.joinToString("; ") { s ->
        "${s.label} from ${formatShare(s.values.first())} to ${formatShare(s.values.last())}"
    }

    Column(modifier = modifier) {
        Legend(populated.map { it.label to it.color })
        Spacer(Modifier.height(8.dp))

        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(height)
                .semantics { contentDescription = description },
        ) {
            val lineWidth = LINE_WIDTH_DP.dp.toPx()
            val inset = lineWidth
            val plotHeight = size.height - inset * 2
            val plotWidth = size.width

            fun yFor(value: Double): Float =
                inset + (((maxY - value) / span) * plotHeight).toFloat()

            fun xFor(index: Int, count: Int): Float =
                if (count <= 1) plotWidth / 2f else plotWidth * index / (count - 1).toFloat()

            // Grid: solid hairlines, recessive, behind everything.
            repeat(gridLines + 1) { step ->
                val y = inset + plotHeight * step / gridLines
                drawLine(
                    color = palette.grid,
                    start = Offset(0f, y),
                    end = Offset(plotWidth, y),
                    strokeWidth = GRID_WIDTH_DP.dp.toPx(),
                )
            }

            // Ribbons first, so the lines read on top of them.
            populated.forEach { s ->
                val band = s.band ?: return@forEach
                drawRibbon(s, band, { i, c -> xFor(i, c) }, { v -> yFor(v) }, palette.band)
            }

            populated.forEach { s ->
                val path = Path()
                s.values.forEachIndexed { index, value ->
                    val x = xFor(index, s.values.size)
                    val y = yFor(value)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(
                    path = path,
                    color = s.color,
                    style = Stroke(width = lineWidth, cap = StrokeCap.Round),
                )

                // Endpoint marker, ringed in the surface color so overlapping
                // series stay legible where the lines cross.
                val lastX = xFor(s.values.lastIndex, s.values.size)
                val lastY = yFor(s.values.last())
                drawCircle(palette.surface, radius = lineWidth * 2.4f, center = Offset(lastX, lastY))
                drawCircle(s.color, radius = lineWidth * 1.6f, center = Offset(lastX, lastY))
            }
        }

        if (startLabel != null || endLabel != null) {
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                AxisTick(startLabel.orEmpty())
                AxisTick(endLabel.orEmpty())
            }
        }
    }
}

private fun DrawScope.drawRibbon(
    series: Series,
    band: List<Double>,
    xFor: (Int, Int) -> Float,
    yFor: (Double) -> Float,
    fill: Color,
) {
    val count = series.values.size
    if (count < 2) return
    val path = Path()
    series.values.forEachIndexed { index, value ->
        val x = xFor(index, count)
        val y = yFor(value + (band.getOrNull(index) ?: 0.0))
        if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    for (index in series.values.indices.reversed()) {
        val x = xFor(index, count)
        val y = yFor(series.values[index] - (band.getOrNull(index) ?: 0.0))
        path.lineTo(x, y)
    }
    path.close()
    drawPath(path = path, color = fill)
}

/**
 * A bare trend line, no axis or legend, for use inside a stat tile.
 */
@Composable
fun Sparkline(
    values: List<Double>,
    color: Color,
    modifier: Modifier = Modifier,
) {
    if (values.size < 2) return
    val min = values.min()
    val max = values.max()
    val span = (max - min).coerceAtLeast(0.0001)

    Canvas(modifier = modifier.semantics { contentDescription = "Trend sparkline" }) {
        val strokeWidth = LINE_WIDTH_DP.dp.toPx()
        val usableHeight = size.height - strokeWidth * 2
        val path = Path()
        values.forEachIndexed { index, value ->
            val x = size.width * index / (values.size - 1).toFloat()
            val y = strokeWidth + (((max - value) / span) * usableHeight).toFloat()
            if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        drawPath(path, color, style = Stroke(width = strokeWidth, cap = StrokeCap.Round))
    }
}

/**
 * Two candidate shares as opposing bars.
 *
 * A two-slice pie would be the obvious wrong answer here; so would a one-bar bar
 * chart per candidate. Opposing bars on a shared scale make the gap — the only
 * quantity anyone cares about — directly visible.
 */
@Composable
fun ShareBars(
    rows: List<Triple<String, Double, Color>>,
    modifier: Modifier = Modifier,
    maxValue: Double? = null,
    valueLabel: (Double) -> String = { formatShare(it) + "%" },
) {
    val ceiling = (maxValue ?: rows.maxOfOrNull { it.second } ?: 1.0).coerceAtLeast(0.001)

    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        rows.forEach { (label, value, color) ->
            Column {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = label,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = valueLabel(value),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                Spacer(Modifier.height(4.dp))
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant),
                ) {
                    val fraction = (value / ceiling).coerceIn(0.0, 1.0).toFloat()
                    if (fraction > 0f) {
                        Box(
                            Modifier
                                .fillMaxWidth(fraction)
                                .height(8.dp)
                                // 4px rounded data end, anchored at the baseline.
                                .clip(RoundedCornerShape(4.dp))
                                .background(color),
                        )
                    }
                }
            }
        }
    }
}

/** Identity is never carried by color alone: every series is named here too. */
@Composable
fun Legend(entries: List<Pair<String, Color>>, modifier: Modifier = Modifier) {
    if (entries.size < 2) return // one series needs no legend; the title names it
    Row(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        entries.forEach { (label, color) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(color))
                Spacer(Modifier.width(6.dp))
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    // Text wears ink, not the series color; the dot carries identity.
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun AxisTick(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}
