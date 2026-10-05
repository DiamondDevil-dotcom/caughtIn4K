import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'services/router_api_service.dart';
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
import 'services/push_notification_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    await RouterApiService.init();
  } on PlatformException {
    runApp(const StartupFailureApp());
    return;
  } on FormatException {
    runApp(const StartupFailureApp());
    return;
  }
  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AlertProvider()),
        ChangeNotifierProvider(create: (_) => ThemeProvider()),
        ChangeNotifierProvider(create: (_) => AuthProvider()..load()),
        ChangeNotifierProvider(create: (_) => DeviceProvider()..load()),
        ChangeNotifierProvider(
          create: (_) => RouterDeviceProvider()..startPolling(),
        ),
        ChangeNotifierProvider(create: (_) => DemoModeProvider()..load()),
        ChangeNotifierProvider(
          create: (_) => ActivityProvider()..startPolling(),
        ),
      ],
      child: const NyxisApp(),
    ),
  );
}

class StartupFailureApp extends StatelessWidget {
  const StartupFailureApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    home: Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Your secure account could not be loaded. Retry, or contact support before changing a network action.',
              ),
              FilledButton(onPressed: main, child: const Text('Retry')),
            ],
          ),
        ),
      ),
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
      builder: (context, child) => ValueListenableBuilder<String?>(
        valueListenable: PushNotificationService.error,
        builder: (context, error, _) => Column(
          children: [
            if (error != null)
              Material(
                color: Theme.of(context).colorScheme.errorContainer,
                child: SafeArea(
                  bottom: false,
                  child: ListTile(
                    title: Text(error),
                    trailing: TextButton(
                      onPressed: PushNotificationService.syncSafely,
                      child: const Text('Retry'),
                    ),
                  ),
                ),
              ),
            Expanded(child: child ?? const SizedBox.shrink()),
          ],
        ),
      ),
    );
  }
}
