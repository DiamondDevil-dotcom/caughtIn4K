import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppTheme {
  // ===== COLORS =====
  static const Color background = Color(0xFF0B1220);
  static const Color surface = Color(0xFF131E2D);

  static const Color primary = Color(0xFF64E3A1);

  static const Color success = Color(0xFF64E3A1);
  static const Color danger = Color(0xFFFF6B6B);
  static const Color warning = Color(0xFFFFC857);

  static const Color textPrimary = Colors.white;
  static const Color textSecondary = Color(0xFF8A97B2);
  static const Color lightBackground = Color(0xFFF3F7F8);
  static const Color lightSurface = Color(0xFFFFFFFF);
  static const Color lightTextPrimary = Color(0xFF12202A);
  static const Color lightTextSecondary = Color(0xFF52616B);

  static const PageTransitionsTheme pageTransitions = PageTransitionsTheme(
    builders: {
      TargetPlatform.android: CupertinoPageTransitionsBuilder(),
      TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
    },
  );

  static ThemeData darkTheme = ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    fontFamily: GoogleFonts.spaceGrotesk().fontFamily,

    scaffoldBackgroundColor: background,

    colorScheme: const ColorScheme.dark(
      primary: primary,
      secondary: primary,
      surface: surface,
    ),

    appBarTheme: const AppBarTheme(
      backgroundColor: background,
      elevation: 0,
      centerTitle: false,
      foregroundColor: Colors.white,
      titleTextStyle: TextStyle(
        color: Colors.white,
        fontSize: 24,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.2,
      ),
    ),

    cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(
            color: Colors.white10,
        ),
        ),
    ),

    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: primary,
        foregroundColor: Colors.black,
        minimumSize: const Size(double.infinity, 55),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
        ),
      ),
    ),

    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: primary,
        foregroundColor: Colors.black,
        minimumSize: const Size(double.infinity, 55),
        textStyle: const TextStyle(
          fontWeight: FontWeight.w700,
          letterSpacing: 0.1,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
        ),
      ),
    ),

    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: surface,
      elevation: 0,
      height: 72,
      indicatorColor: primary,
      labelTextStyle: WidgetStatePropertyAll(
        TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
      ),
      iconTheme: const WidgetStatePropertyAll(
        IconThemeData(size: 22),
      ),
    ),

    dividerColor: Colors.white10,

    iconTheme: const IconThemeData(
      color: primary,
    ),

    textTheme: GoogleFonts.spaceGroteskTextTheme(const TextTheme(
      headlineLarge: TextStyle(
        color: textPrimary,
        fontWeight: FontWeight.bold,
      ),
      headlineMedium: TextStyle(
        color: textPrimary,
        fontWeight: FontWeight.bold,
      ),
      titleLarge: TextStyle(
        color: textPrimary,
        fontWeight: FontWeight.w600,
      ),
      bodyLarge: TextStyle(
        color: textPrimary,
      ),
      bodyMedium: TextStyle(
        color: textSecondary,
      ),
    )),
    pageTransitionsTheme: pageTransitions,
  );

  static ThemeData lightTheme = ThemeData(
    useMaterial3: true,
    brightness: Brightness.light,
    scaffoldBackgroundColor: lightBackground,
    colorScheme: const ColorScheme.light(
      primary: Color(0xFF168B63),
      secondary: Color(0xFF168B63),
      surface: lightSurface,
      onSurface: lightTextPrimary,
      onPrimary: Colors.white,
    ),
    fontFamily: GoogleFonts.spaceGrotesk().fontFamily,
    appBarTheme: const AppBarTheme(
      backgroundColor: lightBackground,
      foregroundColor: lightTextPrimary,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: lightTextPrimary,
        fontSize: 24,
        fontWeight: FontWeight.w700,
      ),
    ),
    cardTheme: CardThemeData(
      color: lightSurface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: Color(0x180F252D)),
      ),
    ),
    dividerColor: const Color(0x1A12202A),
    iconTheme: const IconThemeData(color: Color(0xFF168B63)),
    textTheme: GoogleFonts.spaceGroteskTextTheme(const TextTheme(
      headlineLarge: TextStyle(color: lightTextPrimary, fontWeight: FontWeight.bold),
      headlineMedium: TextStyle(color: lightTextPrimary, fontWeight: FontWeight.bold),
      titleLarge: TextStyle(color: lightTextPrimary, fontWeight: FontWeight.w600),
      bodyLarge: TextStyle(color: lightTextPrimary),
      bodyMedium: TextStyle(color: lightTextSecondary),
    )),
    navigationBarTheme: const NavigationBarThemeData(
      backgroundColor: lightSurface,
    ),
    pageTransitionsTheme: pageTransitions,
  );
}