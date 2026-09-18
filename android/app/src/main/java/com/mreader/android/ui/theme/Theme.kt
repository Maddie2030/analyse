package com.mreader.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

// Native Android mirror of the web application's Tailwind palette.
val Ink50 = Color(0xFFF3EFE7)
val Ink100 = Color(0xFFE5E0D6)
val Ink200 = Color(0xFFC9C3B5)
val Ink300 = Color(0xFFA8A193)
val Ink400 = Color(0xFF7D7666)
val Ink500 = Color(0xFF5C5648)
val Ink600 = Color(0xFF423D33)
val Ink700 = Color(0xFF2E2A23)
val Ink800 = Color(0xFF1F1C17)
val Ink900 = Color(0xFF15130F)
val Ink950 = Color(0xFF0C0B09)

val Brand50 = Color(0xFFFFF2ED)
val Brand100 = Color(0xFFFFE0D4)
val Brand200 = Color(0xFFFFC1A9)
val Brand300 = Color(0xFFFF9A78)
val Brand400 = Color(0xFFEF806C)
val Brand500 = Color(0xFFE05A3F)
val Brand600 = Color(0xFFC84327)
val Brand700 = Color(0xFFA3351D)
val Brand800 = Color(0xFF7A2818)
val Brand900 = Color(0xFF5C1F14)
val Brand950 = Color(0xFF351C1B)
val Gold400 = Color(0xFFE8B96A)

private val MReaderColors = darkColorScheme(
    primary = Brand400,
    onPrimary = Color.White,
    primaryContainer = Brand950,
    onPrimaryContainer = Brand100,
    secondary = Gold400,
    onSecondary = Ink950,
    secondaryContainer = Ink700,
    onSecondaryContainer = Ink50,
    tertiary = Brand300,
    background = Ink950,
    onBackground = Ink50,
    surface = Ink900,
    onSurface = Ink50,
    surfaceVariant = Ink800,
    onSurfaceVariant = Ink300,
    outline = Ink700,
    outlineVariant = Ink800,
    error = Color(0xFFFF8A80),
    onError = Ink950,
)

private val MReaderTypography = Typography(
    displaySmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Bold,
        fontSize = 32.sp,
        lineHeight = 37.sp,
        letterSpacing = (-0.4f).sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Bold,
        fontSize = 27.sp,
        lineHeight = 32.sp,
        letterSpacing = (-0.2f).sp,
    ),
    headlineSmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Bold,
        fontSize = 23.sp,
        lineHeight = 28.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 20.sp,
        lineHeight = 25.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 21.sp,
    ),
    titleSmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 19.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 21.sp,
    ),
    bodySmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 18.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 18.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 14.sp,
    ),
)

private val MReaderShapes = Shapes(
    extraSmall = RoundedCornerShape(7.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

@Composable
fun MReaderTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = MReaderColors,
        typography = MReaderTypography,
        shapes = MReaderShapes,
        content = content,
    )
}
