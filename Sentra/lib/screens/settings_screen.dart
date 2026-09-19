import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/theme_provider.dart';
import '../providers/alert_provider.dart';
import '../widgets/liquid_glass_surface.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final themeProvider = Provider.of<ThemeProvider>(context);
    final alertProvider = context.watch<AlertProvider>();

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Settings"),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          LiquidGlassSurface(
            child: SwitchListTile(
              secondary: Icon(
                themeProvider.isDark
                    ? Icons.dark_mode
                    : Icons.light_mode,
              ),
              title: const Text("Dark Mode"),
              subtitle: const Text(
                "Switch between light and dark themes",
              ),
              value: themeProvider.isDark,
              onChanged: (value) {
                themeProvider.toggleTheme(value);
              },
            ),
          ),

          const SizedBox(height: 20),

          LiquidGlassSurface(
            child: SwitchListTile(
              secondary: const Icon(Icons.notifications_none),
              title: const Text("Live notifications"),
              subtitle: Text(
                alertProvider.notificationsEnabled
                    ? "Global model alerts are enabled"
                    : "Global model alerts are muted",
              ),
              value: alertProvider.notificationsEnabled,
              onChanged: alertProvider.setNotificationsEnabled,
            ),
          ),

          const SizedBox(height: 15),

          if (alertProvider.notifications.isNotEmpty)
            LiquidGlassSurface(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(
                children: [
                  const ListTile(
                    leading: Icon(Icons.notifications_active_outlined),
                    title: Text("Recent notifications"),
                  ),
                  ...alertProvider.notifications.take(8).map(
                    (notification) => ListTile(
                      dense: true,
                      leading: Icon(
                        notification["status"] == "ALERT"
                            ? Icons.warning_amber_rounded
                            : Icons.check_circle_outline,
                        color: notification["status"] == "ALERT"
                            ? Colors.redAccent
                            : Colors.green,
                      ),
                      title: Text(
                        "${notification["device"]}: ${notification["prediction"]}",
                      ),
                      subtitle: Text(
                        "${notification["confidence"]}% confidence",
                      ),
                    ),
                  ),
                ],
              ),
            ),

          if (alertProvider.notifications.isNotEmpty)
            const SizedBox(height: 15),

          const LiquidGlassSurface(
            child: ListTile(
              leading: Icon(Icons.info_outline),
              title: Text("About caughtIn4K"),
              subtitle: Text(
                "AI Powered IoT Security\nVersion 1.0.0",
              ),
            ),
          ),
        ],
      ),
    );
  }
}