package org.ksrace.senate2026.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * The app's chrome is deliberately neutral. Reds and blues carry candidate
 * identity in the data, so if the surrounding UI also leaned red or blue the
 * chrome would read as an endorsement.
 */
private val LightScheme = lightColorScheme(
    primary = Color(0xFF1B2A4A),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFDCE3F0),
    onPrimaryContainer = Color(0xFF101B33),
    secondary = Color(0xFF4A5568),
    background = Color(0xFFFCFCFB),
    onBackground = Color(0xFF0B0B0B),
    surface = Color(0xFFFCFCFB),
    onSurface = Color(0xFF0B0B0B),
    surfaceVariant = Color(0xFFF1F1EE),
    onSurfaceVariant = Color(0xFF52514E),
    outlineVariant = Color(0xFFE6E5E1),
)

private val DarkScheme = darkColorScheme(
    primary = Color(0xFFAFC2E8),
    onPrimary = Color(0xFF14203A),
    primaryContainer = Color(0xFF25324F),
    onPrimaryContainer = Color(0xFFDCE3F0),
    secondary = Color(0xFFB4BCCB),
    background = Color(0xFF141413),
    onBackground = Color(0xFFF5F5F2),
    surface = Color(0xFF1A1A19),
    onSurface = Color(0xFFF5F5F2),
    surfaceVariant = Color(0xFF262625),
    onSurfaceVariant = Color(0xFFC3C2B7),
    outlineVariant = Color(0xFF2C2C2A),
)

/**
 * One sans throughout, including the hero figure — a display or serif face on a
 * big number reads as decoration. Hero and stat values use proportional figures;
 * only table rows and axis ticks get tabular alignment.
 */
private val AppTypography = Typography().let { base ->
    base.copy(
        displaySmall = base.displaySmall.copy(
            fontFamily = FontFamily.SansSerif,
            fontWeight = FontWeight.SemiBold,
        ),
        headlineMedium = base.headlineMedium.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        labelSmall = base.labelSmall.copy(
            fontSize = 11.sp,
            letterSpacing = 0.4.sp,
        ),
    )
}

/** The one style that wants aligned digits: table and axis numerals. */
val TabularNumberStyle: TextStyle
    @Composable get() = MaterialTheme.typography.bodyMedium.copy(
        fontFeatureSettings = "tnum",
    )

@Composable
fun KansasSenateTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    /** Material You, where the platform offers it. Charts keep their own hues. */
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val scheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> DarkScheme
        else -> LightScheme
    }
    val palette = if (darkTheme) DarkChartPalette else LightChartPalette

    CompositionLocalProvider(LocalChartPalette provides palette) {
        MaterialTheme(
            colorScheme = scheme,
            typography = AppTypography,
            content = content,
        )
    }
}
