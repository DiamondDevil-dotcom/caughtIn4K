import 'package:flutter/material.dart';
import 'theme/app_theme.dart';
import 'screens/splash_screen.dart';
import 'package:provider/provider.dart';
import 'providers/theme_provider.dart';
import 'providers/alert_provider.dart';
import 'providers/auth_provider.dart';
import 'providers/device_provider.dart';
import 'providers/router_device_provider.dart';
import 'providers/demo_mode_provider.dart';
import 'providers/activity_provider.dart';

void main() {
  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(
          create: (_) => AlertProvider(),
        ),
        ChangeNotifierProvider(
          create: (_) => ThemeProvider(),
        ),
        ChangeNotifierProvider(
          create: (_) => AuthProvider()..load(),
        ),
        ChangeNotifierProvider(
          create: (_) => DeviceProvider()..load(),
        ),
        ChangeNotifierProvider(
          create: (_) => RouterDeviceProvider()..startPolling(),
        ),
        ChangeNotifierProvider(
          create: (_) => DemoModeProvider()..load(),
        ),
        ChangeNotifierProvider(
          create: (_) => ActivityProvider()..startPolling(),
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