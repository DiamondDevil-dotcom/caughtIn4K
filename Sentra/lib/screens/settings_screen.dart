import 'package:flutter/services.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/theme_provider.dart';
import '../providers/alert_provider.dart';
import '../providers/auth_provider.dart';
import '../providers/activity_provider.dart';
import '../providers/demo_mode_provider.dart';
import '../providers/router_device_provider.dart';
import '../services/router_api_service.dart';
import '../widgets/liquid_glass_surface.dart';
import '../services/cloud_api_service.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final themeProvider = Provider.of<ThemeProvider>(context);
    final alertProvider = context.watch<AlertProvider>();
    final demoModeProvider = context.watch<DemoModeProvider>();
    final authProvider = context.watch<AuthProvider>();
    final routerProvider = context.watch<RouterDeviceProvider>();
    final canManageHousehold = const {'owner', 'admin'}.contains(authProvider.householdRole);
    final recentNotifications =
        [if (!RouterApiService.cloudMode) ...alertProvider.notifications, ...routerProvider.notifications]..sort(
          (a, b) =>
              (b['timestamp'] as String).compareTo(a['timestamp'] as String),
        );

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(title: const Text("Settings")),
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
          if (authProvider.householdRole == null && !RouterApiService.cloudMode)
            LiquidGlassSurface(
              child: ListTile(
                leading: const Icon(Icons.router_outlined),
                title: const Text('Claim gateway'),
                subtitle: const Text('Enter the one-time setup code from your Pi'),
                onTap: () => _showClaimGateway(context),
              ),
            )
          else
            LiquidGlassSurface(
              child: ListTile(
                leading: const Icon(Icons.home_outlined),
                title: const Text('Household access'),
                subtitle: Text('Role: ${authProvider.householdRole}'),
              ),
            ),
          if (canManageHousehold) ...[
            const SizedBox(height: 15),
            LiquidGlassSurface(
              child: ListTile(
                leading: const Icon(Icons.person_add_alt_1_outlined),
                title: const Text('Invite household member'),
                subtitle: const Text('Create a one-time invitation code'),
                onTap: () => _showInviteMember(context),
              ),
            ),
          ],

          const SizedBox(height: 15),
          LiquidGlassSurface(
            child: ListTile(
              leading: const Icon(Icons.password_outlined),
              title: const Text('Change password'),
              onTap: () => _showChangePassword(context),
            ),
          ),

          const SizedBox(height: 15),
          LiquidGlassSurface(child: ListTile(
            leading: const Icon(Icons.cloud_outlined),
            title: const Text('Your home'),
            subtitle: Text(CloudApiService.gatewayName ?? 'Home'),
            onTap: () {
              context.read<RouterDeviceProvider>().clearCachedData();
              context.read<ActivityProvider>().clearCachedData();
              context.read<AuthProvider>().chooseAnotherHome();
            },
          )),
          const SizedBox(height: 15),
          if (!RouterApiService.cloudMode)
          LiquidGlassSurface(
            child: ListTile(
              leading: const Icon(Icons.cloud_sync_outlined),
              title: const Text('Gateway / Server URL'),
              subtitle: Text(
                RouterApiService.baseUrl,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
              trailing: const Icon(Icons.arrow_forward_ios, size: 16),
              onTap: () => _showServerSettings(context),
            ),
          ),

          const SizedBox(height: 20),

          LiquidGlassSurface(
            child: SwitchListTile(
              secondary: Icon(
                themeProvider.isDark ? Icons.dark_mode : Icons.light_mode,
              ),
              title: const Text("Dark Mode"),
              subtitle: const Text("Switch between light and dark themes"),
              value: themeProvider.isDark,
              onChanged: (value) {
                themeProvider.toggleTheme(value);
              },
            ),
          ),

          const SizedBox(height: 20),

          if (!RouterApiService.cloudMode) LiquidGlassSurface(
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
                  ...recentNotifications
                      .take(8)
                      .map(
                        (notification) => ListTile(
                          dense: true,
                          leading: Icon(
                            [
                                  "WARNING",
                                  "ALERT",
                                  "BLOCKED",
                                ].contains(notification["status"])
                                ? Icons.warning_amber_rounded
                                : Icons.check_circle_outline,
                            color:
                                [
                                  "WARNING",
                                  "ALERT",
                                  "BLOCKED",
                                ].contains(notification["status"])
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

          if (recentNotifications.isNotEmpty) const SizedBox(height: 15),

          const LiquidGlassSurface(
            child: ListTile(
              leading: Icon(Icons.info_outline),
              title: Text("About caughtIn4K"),
              subtitle: Text("AI Powered IoT Security\nVersion 1.0.0"),
            ),
          ),

          const SizedBox(height: 20),

          LiquidGlassSurface(
            child: ListTile(
              leading: const Icon(Icons.logout, color: Colors.redAccent),
              title: const Text('Sign out'),
              subtitle: const Text('Sign out from this device'),
              onTap: () => _signOut(context),
            ),
          ),

          const SizedBox(height: 20),

          if (!RouterApiService.cloudMode) LiquidGlassSurface(
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

  Future<void> _signOut(BuildContext context) async {
    context.read<RouterDeviceProvider>().clearCachedData();
    context.read<ActivityProvider>().clearCachedData();
    context.read<AlertProvider>().clearCachedData();
    await context.read<AuthProvider>().signOut();
  }

  Future<void> _showClaimGateway(BuildContext context) async {
    final code = TextEditingController();
    final messenger = ScaffoldMessenger.of(context);
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Claim this gateway'),
        content: TextField(
          controller: code,
          decoration: const InputDecoration(labelText: 'One-time Pi setup code'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              final error = await context.read<AuthProvider>().claimGateway(code.text);
              if (!dialogContext.mounted) return;
              Navigator.pop(dialogContext);
              messenger.showSnackBar(
                SnackBar(content: Text(error ?? 'Gateway claimed for this household.')),
              );
            },
            child: const Text('Claim gateway'),
          ),
        ],
      ),
    );
    code.dispose();
  }

  Future<void> _showInviteMember(BuildContext context) async {
    final email = TextEditingController();
    var role = 'member';
    String? error;
    String? inviteCode;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Invite household member'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Member email'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: role,
                decoration: const InputDecoration(labelText: 'Role'),
                items: [
                  const DropdownMenuItem(value: 'member', child: Text('Member')),
                  if (context.read<AuthProvider>().householdRole == 'owner')
                    const DropdownMenuItem(value: 'admin', child: Text('Admin')),
                ],
                onChanged: (value) {
                  if (value != null) setDialogState(() => role = value);
                },
              ),
              if (error != null) Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              if (inviteCode != null) ...[
                const SizedBox(height: 12),
                const Text('Share this code with the invited account:'),
                SelectableText(inviteCode!),
              ],
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: Text(inviteCode == null ? 'Cancel' : 'Done'),
            ),
            if (inviteCode != null)
              TextButton(
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: inviteCode!));
                  if (dialogContext.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Invitation code copied.')),
                    );
                  }
                },
                child: const Text('Copy code'),
              )
            else
              FilledButton(
                onPressed: () async {
                  try {
                    final result = await RouterApiService.createHouseholdInvite(
                      email: email.text.trim(),
                      role: role,
                    );
                    if (!dialogContext.mounted) return;
                    setDialogState(() {
                      inviteCode = result['invite_code'] as String?;
                      error = inviteCode == null ? 'The server did not return an invitation code.' : null;
                    });
                  } catch (exception) {
                    if (dialogContext.mounted) {
                      setDialogState(() => error = exception.toString().replaceFirst(RegExp(r'^Exception:\s*'), ''));
                    }
                  }
                },
                child: const Text('Create code'),
              ),
          ],
        ),
      ),
    );
    email.dispose();
  }

  Future<void> _showChangePassword(BuildContext context) async {
    final current = TextEditingController();
    final next = TextEditingController();
    final confirm = TextEditingController();
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Change password'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: current,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Current password'),
            ),
            TextField(
              controller: next,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'New password'),
            ),
            TextField(
              controller: confirm,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'Confirm new password',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              if (next.text != confirm.text) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('New passwords do not match.')),
                );
                return;
              }
              final error = await context.read<AuthProvider>().changePassword(
                current.text,
                next.text,
              );
              if (error == null && RouterApiService.cloudMode && context.mounted) {
                await context.read<AuthProvider>().signOut();
              }
              if (!dialogContext.mounted) return;
              Navigator.pop(dialogContext);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(error ?? 'Password changed.')),
              );
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

  Future<void> _showServerSettings(BuildContext context) async {
    final controller = TextEditingController(text: RouterApiService.baseUrl);
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setModalState) => AlertDialog(
          title: const Text('Gateway / Server URL'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Use the Render gateway for devices, model status and training on any internet connection. The Pi tunnel is configured on Render, not here.',
                  style: TextStyle(fontSize: 13),
                ),
                const SizedBox(height: 14),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ActionChip(
                      avatar: const Icon(Icons.public, size: 16),
                      label: const Text('Shared Render Gateway'),
                      onPressed: () {
                        setModalState(() {
                          controller.text = 'https://caughtin4k.onrender.com';
                        });
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: controller,
                  decoration: const InputDecoration(
                    labelText: 'Server URL',
                    hintText: 'https://...',
                    border: OutlineInputBorder(),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                final newUrl = controller.text.trim();
                final previousUrl = RouterApiService.baseUrl;
                final auth = context.read<AuthProvider>();
                final router = context.read<RouterDeviceProvider>();
                final activity = context.read<ActivityProvider>();
                final messenger = ScaffoldMessenger.of(context);
                try {
                  await RouterApiService.setBaseUrl(newUrl);
                  if (previousUrl != RouterApiService.baseUrl) {
                    router.clearCachedData();
                    activity.clearCachedData();
                    await auth.signOut();
                  }
                  if (!dialogContext.mounted) return;
                  Navigator.pop(dialogContext);
                  messenger.showSnackBar(
                    SnackBar(
                      content: Text(
                        'Gateway saved: $newUrl. Sign in to verify access.',
                      ),
                    ),
                  );
                } catch (error) {
                  if (!dialogContext.mounted) return;
                  messenger.showSnackBar(
                    SnackBar(content: Text('Could not save gateway: $error')),
                  );
                }
              },
              child: const Text('Save & Apply'),
            ),
          ],
        ),
      ),
    );
    controller.dispose();
  }
}
