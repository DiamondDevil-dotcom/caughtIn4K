import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/router_device_provider.dart';
import '../providers/auth_provider.dart';
import '../services/router_api_service.dart';
import '../services/cloud_api_service.dart';

class DevicesScreen extends StatelessWidget {
  const DevicesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final router = context.watch<RouterDeviceProvider>();
    final canManage =
        !RouterApiService.cloudMode ||
        const {
          'owner',
          'admin',
        }.contains(context.watch<AuthProvider>().householdRole);
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Devices"),
        actions: [
          if (canManage)
            IconButton(
              tooltip: 'Add device',
              icon: const Icon(Icons.add_circle_outline),
              onPressed:
                  router.pendingControlMac != null ||
                      CloudApiService.commandUnconfirmed
                  ? null
                  : () => _showAddDeviceDialog(context),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [..._routerDevicesSection(context)],
      ),
    );
  }

  List<Widget> _routerDevicesSection(BuildContext context) {
    final router = context.watch<RouterDeviceProvider>();
    final foldDevices = router.displayedDevices.where((device) {
      final mac = (device['mac'] as String? ?? '').toLowerCase();
      return !mac.startsWith('02:00:00:00:01:');
    }).toList();

    if (foldDevices.isEmpty &&
        router.lastError == null &&
        !RouterApiService.cloudMode) {
      return const [];
    }

    return [
      Padding(
        padding: EdgeInsets.only(bottom: 12),
        child: Text(
          RouterApiService.cloudMode
              ? 'Your devices'
              : 'Live Network Devices (Router)',
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
        ),
      ),
      if (RouterApiService.cloudMode) ...[
        Text(router.cloudFreshness),
        if (router.notificationError != null)
          Text(
            router.notificationError!,
            style: const TextStyle(color: Colors.orange),
          ),
        if (CloudApiService.commandUnconfirmed) ...[
          TextButton(
            onPressed: router.pendingControlMac != null
                ? null
                : () async {
                    try {
                      final result = await context
                          .read<RouterDeviceProvider>()
                          .checkCommandStatus();
                      if (!context.mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(
                            result['status'] == 'succeeded'
                                ? 'Your Pi confirmed the device action.'
                                : 'Device action: ${result['status']}. Check before retrying.',
                          ),
                        ),
                      );
                    } catch (error) {
                      if (context.mounted) {
                        ScaffoldMessenger.of(context)
                            .showSnackBar(SnackBar(content: Text('$error')));
                      }
                    }
                  },
            child: const Text('Check command status'),
          ),
        ],
        if (foldDevices.isEmpty)
          const Text('No devices reported yet. Add a device to your home.'),
        const SizedBox(height: 12),
      ],
      if (router.lastError != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(
            '${RouterApiService.cloudMode ? "Cloud unavailable" : "Router unreachable"}: ${router.lastError}',
            style: const TextStyle(color: Colors.redAccent),
          ),
        ),
      ...foldDevices.map((device) => _routerDeviceCard(context, device)),
      const SizedBox(height: 20),
    ];
  }

  Future<void> _showAddDeviceDialog(BuildContext context) async {
    final name = TextEditingController();
    final mac = TextEditingController();
    final ip = TextEditingController();
    final formKey = GlobalKey<FormState>();
    bool busy = false;
    String? error;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => PopScope(
          canPop: !busy,
          child: AlertDialog(
            title: const Text('Add device'),
            content: SingleChildScrollView(
              child: Form(
                key: formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextFormField(
                      controller: name,
                      decoration: const InputDecoration(
                        labelText: 'Device name',
                      ),
                      validator: (value) =>
                          value == null || value.trim().isEmpty
                          ? 'Enter a name'
                          : null,
                    ),
                    TextFormField(
                      controller: mac,
                      decoration: const InputDecoration(
                        labelText: 'MAC address',
                        hintText: 'aa:bb:cc:dd:ee:ff',
                      ),
                      validator: (value) =>
                          value == null ||
                              !RegExp(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$')
                                  .hasMatch(value.trim())
                          ? 'Enter a valid MAC address'
                          : null,
                    ),
                    TextFormField(
                      controller: ip,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(
                        labelText: 'IP address (optional)',
                        hintText: 'Auto-resolved if omitted',
                      ),
                    ),
                    if (error != null)
                      Text(
                        error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: busy ? null : () => Navigator.pop(dialogContext),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: busy || CloudApiService.commandUnconfirmed
                    ? null
                    : () async {
                        if (!formKey.currentState!.validate()) return;
                        setDialogState(() {
                          busy = true;
                          error = null;
                        });
                        try {
                          await context
                              .read<RouterDeviceProvider>()
                              .registerDevice(
                                name: name.text.trim(),
                                mac: mac.text.trim().toLowerCase(),
                                ipAddress: ip.text.trim(),
                              );
                          if (dialogContext.mounted) {
                            Navigator.pop(dialogContext);
                            if (RouterApiService.cloudMode) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text(
                                    'Device added on your Pi. It may take up to 30 seconds to appear.',
                                  ),
                                ),
                              );
                            }
                          }
                        } catch (failure) {
                          if (dialogContext.mounted) {
                            setDialogState(() => error = '$failure');
                          }
                        } finally {
                          if (dialogContext.mounted) {
                            setDialogState(() => busy = false);
                          }
                        }
                      },
                child: Text(busy ? 'Waiting for Pi...' : 'Add device'),
              ),
            ],
          ),
        ),
      ),
    );
    name.dispose();
    mac.dispose();
    ip.dispose();
  }

  Widget _routerDeviceCard(BuildContext context, Map<String, dynamic> device) {
    final status = device['status'] as String? ?? 'SAFE';
    final mac = device['mac'] as String? ?? '';
    final router = context.watch<RouterDeviceProvider>();
    final cloud = RouterApiService.cloudMode;
    final blocked = device['blocked'] == true || status == 'BLOCKED';
    final canControl =
        !cloud ||
        (!router.cloudDataStale &&
            !CloudApiService.commandUnconfirmed &&
            const {
              'owner',
              'admin',
            }.contains(context.watch<AuthProvider>().householdRole));
    final colors = {
      'SAFE': Colors.green,
      'WARNING': Colors.orange,
      'ALERT': Colors.red,
      'ATTACK': Colors.red,
      'BLOCKED': Colors.grey,
    };
    final color = colors[status] ?? Colors.blueGrey;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(
                status == 'BLOCKED' ? Icons.block : Icons.wifi_tethering,
                color: color,
              ),
              title: Text(device['name'] as String? ?? mac),
              subtitle: Text('${device['ip_address']}\n$mac'),
              isThreeLine: true,
              trailing: Text(
                status,
                style: TextStyle(color: color, fontWeight: FontWeight.bold),
              ),
            ),
            const Divider(),
            if (cloud &&
                router.recentWarnings.any((event) => event['mac'] == mac))
              const Text(
                'Recent WARNING detected on this device (last 60 seconds).',
                style: TextStyle(color: Colors.orange),
              ),
            if (router.confirmedControls.containsKey(mac))
              const Text('Device action confirmed. Updating…'),
            if (cloud &&
                !const {
                  'owner',
                  'admin',
                }.contains(context.watch<AuthProvider>().householdRole))
              const Text('Read-only: owners/admins can control the network.'),
            Row(
              children: [
                if (!cloud ||
                    const {
                      'owner',
                      'admin',
                    }.contains(context.watch<AuthProvider>().householdRole))
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: !canControl || router.pendingControlMac != null
                          ? null
                          : () => _confirmDelete(context, device),
                      icon: const Icon(Icons.delete_outline),
                      label: const Text('Remove'),
                    ),
                  ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: !canControl || router.pendingControlMac != null
                        ? null
                        : () async {
                            final confirmed = await showDialog<bool>(
                              context: context,
                              builder: (dialogContext) => AlertDialog(
                                title: Text(
                                  blocked ? 'Unblock device?' : 'Block device?',
                                ),
                                content: Text(
                                  '${device['name'] ?? mac}\n$mac\n'
                                  'Only control devices on your Pi network. Blocking this phone can disconnect the app; keep another connection available to restore it.',
                                ),
                                actions: [
                                  TextButton(
                                    onPressed: () =>
                                        Navigator.pop(dialogContext, false),
                                    child: const Text('Cancel'),
                                  ),
                                  FilledButton(
                                    onPressed: () =>
                                        Navigator.pop(dialogContext, true),
                                    child: Text(blocked ? 'Unblock' : 'Block'),
                                  ),
                                ],
                              ),
                            );
                            if (confirmed != true || !context.mounted) return;
                            final router = context.read<RouterDeviceProvider>();
                            final operation = blocked
                                ? router.unblock(mac)
                                : router.block(mac);
                            operation
                                .then((_) {
                                  if (!context.mounted) return;
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                      content: Text(
                                        blocked ? 'Device unblocked.' : 'Pi confirmed blocking. Use a separate connection to restore this phone.',
                                      ),
                                    ),
                                  );
                                })
                                .catchError((Object error) {
                                  if (!context.mounted) return;
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                      content: Text(
                                        'Device action failed: $error',
                                      ),
                                    ),
                                  );
                                });
                          },
                    icon: Icon(blocked ? Icons.lock_open : Icons.block),
                    label: Text(
                      router.pendingControlMac == mac
                          ? 'Waiting for Pi...'
                          : blocked
                          ? 'Unblock'
                          : 'Block',
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmDelete(
    BuildContext context,
    Map<String, dynamic> device,
  ) async {
    final mac = device['mac'] as String? ?? '';
    final name = device['name'] as String? ?? mac;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Remove device?'),
        content: Text('$name and its detection history will be removed.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed == true && context.mounted) {
      try {
        await context.read<RouterDeviceProvider>().deleteDevice(mac);
      } catch (failure) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not remove device: $failure')),
          );
        }
      }
    }
  }
}
