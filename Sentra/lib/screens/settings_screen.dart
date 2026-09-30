import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/theme_provider.dart';
import '../providers/alert_provider.dart';
import '../providers/auth_provider.dart';
import '../providers/demo_mode_provider.dart';
import '../providers/router_device_provider.dart';
import '../widgets/liquid_glass_surface.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final themeProvider = Provider.of<ThemeProvider>(context);
    final alertProvider = context.watch<AlertProvider>();
    final demoModeProvider = context.watch<DemoModeProvider>();
    final authProvider = context.watch<AuthProvider>();
    final routerProvider = context.watch<RouterDeviceProvider>();
    final recentNotifications = [
      ...alertProvider.notifications,
      ...routerProvider.notifications,
    ]..sort((a, b) =>
        (b['timestamp'] as String).compareTo(a['timestamp'] as String));

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Settings"),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          LiquidGlassSurface(
            child: ListTile(
              leading: const Icon(Icons.account_circle_outlined),
              title: Text(authProvider.name),
              subtitle: Text(authProvider.email),
            ),
          ),

          const SizedBox(height: 15),
          LiquidGlassSurface(
            child: ListTile(
              leading: const Icon(Icons.password_outlined),
              title: const Text('Change password'),
              onTap: () => _showChangePassword(context),
            ),
          ),

          const SizedBox(height: 20),

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

          if (recentNotifications.isNotEmpty)
            LiquidGlassSurface(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(
                children: [
                  const ListTile(
                    leading: Icon(Icons.notifications_active_outlined),
                    title: Text("Recent notifications"),
                  ),
                  ...recentNotifications.take(8).map(
                    (notification) => ListTile(
                      dense: true,
                      leading: Icon(
                          ["WARNING", "ALERT", "BLOCKED"].contains(notification["status"])
                            ? Icons.warning_amber_rounded
                            : Icons.check_circle_outline,
                        color: ["WARNING", "ALERT", "BLOCKED"].contains(notification["status"])
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

          if (recentNotifications.isNotEmpty)
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

          const SizedBox(height: 20),

          LiquidGlassSurface(
            child: ListTile(
              leading: const Icon(Icons.logout, color: Colors.redAccent),
              title: const Text('Sign out'),
              subtitle: const Text('Sign out from this device'),
              onTap: () => context.read<AuthProvider>().signOut(),
            ),
          ),

          const SizedBox(height: 20),

          LiquidGlassSurface(
            child: SwitchListTile(
              secondary: const Icon(Icons.science_outlined),
              title: const Text("Demo Mode"),
              subtitle: const Text(
                "Show demonstration controls to send test traffic",
              ),
              value: demoModeProvider.enabled,
              onChanged: demoModeProvider.setEnabled,
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _showChangePassword(BuildContext context) async {
    final current = TextEditingController();
    final next = TextEditingController();
    final confirm = TextEditingController();
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Change password'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: current, obscureText: true, decoration: const InputDecoration(labelText: 'Current password')),
          TextField(controller: next, obscureText: true, decoration: const InputDecoration(labelText: 'New password')),
          TextField(controller: confirm, obscureText: true, decoration: const InputDecoration(labelText: 'Confirm new password')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancel')),
          FilledButton(
            onPressed: () async {
              if (next.text != confirm.text) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('New passwords do not match.')));
                return;
              }
              final error = await context.read<AuthProvider>().changePassword(current.text, next.text);
              if (!dialogContext.mounted) return;
              Navigator.pop(dialogContext);
              ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error ?? 'Password changed.')));
            },
            child: const Text('Save password'),
          ),
        ],
      ),
    );
    current.dispose();
    next.dispose();
    confirm.dispose();
  }
}