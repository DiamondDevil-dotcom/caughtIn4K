import 'package:flutter/material.dart';
import 'theme/app_theme.dart';
import 'screens/splash_screen.dart';
import 'package:provider/provider.dart';
import 'providers/theme_provider.dart';
import 'providers/alert_provider.dart';

void main() {
  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(
          create: (_) => AlertProvider()..startListening(),
        ),
        ChangeNotifierProvider(
          create: (_) => ThemeProvider(),
        ),
      ],
      child: const NyxisApp(),
    ),
  );
}

class NyxisApp extends StatelessWidget {
  const NyxisApp({super.key});

  @override
Widget build(BuildContext context) {
  final themeProvider = Provider.of<ThemeProvider>(context);

  return MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'caughtIn4K',

    themeMode: themeProvider.themeMode,

    theme: AppTheme.lightTheme,
    darkTheme: AppTheme.darkTheme,

    home: const SplashScreen(),
  );
  }
}