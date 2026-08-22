package org.ksrace.senate2026.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * Chart and candidate colors.
 *
 * Party hues are domain-mandated — in American political coverage red means
 * Republican and blue means Democrat, and inventing a different mapping would
 * actively mislead readers. So the hues are fixed, but they are still chosen to
 * pass a colorblind-separation check rather than assumed safe:
 *
 *   light  #C93A2E / #2E6DB4  → CVD ΔE 20.2 (protan), normal-vision ΔE 29.0
 *   dark   #E4574A / #4A90D9  → CVD ΔE 21.1 (protan), normal-vision ΔE 28.8
 *
 * Both pass the lightness band, chroma floor, CVD separation, normal-vision
 * floor and 3:1 contrast checks against their own surface. The dark values are
 * separately stepped for the dark surface, not a lightened flip of the light
 * ones.
 *
 * Color is never the only carrier of identity: every chart is direct-labelled
 * at the endpoints and every list row names the candidate in text.
 */
@Immutable
data class ChartPalette(
    val marshall: Color,
    val hamilton: Color,
    /** Translucent fill for the poll aggregate's uncertainty band. */
    val band: Color,
    /** Hairline grid and axis rules: one shade off the surface, solid, never dashed. */
    val grid: Color,
    val surface: Color,
) {
    fun forCandidate(candidateId: String): Color =
        if (candidateId == "hamilton") hamilton else marshall
}

val LightChartPalette = ChartPalette(
    marshall = Color(0xFFC93A2E),
    hamilton = Color(0xFF2E6DB4),
    band = Color(0x1F5C6470),
    grid = Color(0xFFE6E5E1),
    surface = Color(0xFFFCFCFB),
)

val DarkChartPalette = ChartPalette(
    marshall = Color(0xFFE4574A),
    hamilton = Color(0xFF4A90D9),
    band = Color(0x2E9AA3B2),
    grid = Color(0xFF2C2C2A),
    surface = Color(0xFF1A1A19),
)

val LocalChartPalette = staticCompositionLocalOf { LightChartPalette }
