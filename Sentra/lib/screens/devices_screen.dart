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
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Devices"),
        actions: [
          if (!RouterApiService.cloudMode) IconButton(
            tooltip: 'Add device',
            icon: const Icon(Icons.add_circle_outline),
            onPressed: () => _showAddDeviceDialog(context),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          ..._routerDevicesSection(context),
        ],
      ),
    );
  }

  List<Widget> _routerDevicesSection(BuildContext context) {
    final router = context.watch<RouterDeviceProvider>();
    final foldDevices = router.devices.where((device) {
      final mac = (device['mac'] as String? ?? '').toLowerCase();
      return !mac.startsWith('02:00:00:00:01:');
    }).toList();

    if (foldDevices.isEmpty && router.lastError == null && !RouterApiService.cloudMode) {
      return const [];
    }

    return [
      Padding(
        padding: EdgeInsets.only(bottom: 12),
        child: Text(
          RouterApiService.cloudMode ? 'Household devices (cloud snapshot)' : 'Live Network Devices (Router)',
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
        ),
      ),
      if (RouterApiService.cloudMode) ...[
          Text(router.cloudFreshness),
          if (CloudApiService.lastCommandId != null) ...[
            SelectableText('Last command: ${CloudApiService.lastCommandId}'),
            TextButton(
              onPressed: router.pendingControlMac != null ? null : () async {
                try {
                  final result = await CloudApiService.commandStatus();
                  if (!context.mounted) return;
                  if (result['status'] == 'succeeded' && CloudApiService.lastCommandMac != null) {
                    context.read<RouterDeviceProvider>().recordConfirmedControl(
                      CloudApiService.lastCommandMac!, CloudApiService.lastCommandAction == 'block',
                      completedAt: DateTime.tryParse(result['completed_at'] as String? ?? ''),
                    );
                  }
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text('Command: ${result['status']}. '
                        'Only succeeded means Pi-confirmed enforcement. Unknown requires checking Pi/device state.'),
                  ));
                  context.read<RouterDeviceProvider>().refresh();
                } catch (error) {
                  if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
                }
              },
              child: const Text('Check command status'),
            ),
          ],
          if (foldDevices.isEmpty) const Text('No devices in this gateway snapshot yet.'),
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
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Add device'),
        content: SingleChildScrollView(
          child: Form(
            key: formKey,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextFormField(controller: name, decoration: const InputDecoration(labelText: 'Device name'), validator: (value) => value == null || value.trim().isEmpty ? 'Enter a name' : null),
            TextFormField(controller: mac, decoration: const InputDecoration(labelText: 'MAC address', hintText: 'aa:bb:cc:dd:ee:ff'), validator: (value) => value == null || !RegExp(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$').hasMatch(value.trim()) ? 'Enter a valid MAC address' : null),
            TextFormField(controller: ip, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'IP address (optional)', hintText: 'Auto-resolved if omitted')),
          ])),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancel')),
          FilledButton(
            onPressed: () async {
              if (!formKey.currentState!.validate()) return;
              await context.read<RouterDeviceProvider>().registerDevice(name: name.text.trim(), mac: mac.text.trim().toLowerCase(), ipAddress: ip.text.trim());
              if (dialogContext.mounted) Navigator.pop(dialogContext);
            },
            child: const Text('Add device'),
          ),
        ],
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
    final blocked = router.confirmedControls[mac] ?? (device['blocked'] == true || status == 'BLOCKED');
    final canControl = !cloud || (!router.cloudDataStale && !CloudApiService.commandUnconfirmed &&
        const {'owner', 'admin'}.contains(context.watch<AuthProvider>().householdRole));
    final colors = {
      'SAFE': Colors.green,
      'WARNING': Colors.orange,
      'ALERT': Colors.red,
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
            if (router.confirmedControls.containsKey(mac))
              const Text('Pi confirmed the command; waiting for the next snapshot.'),
            if (cloud && !const {'owner', 'admin'}.contains(context.watch<AuthProvider>().householdRole))
              const Text('Read-only: owners/admins can control the network.'),
            Row(
              children: [
                if (!cloud) Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _confirmDelete(context, device),
                    icon: const Icon(Icons.delete_outline),
                    label: const Text('Remove'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: !canControl || router.pendingControlMac != null ? null : () async {
                      final confirmed = await showDialog<bool>(
                        context: context,
                        builder: (dialogContext) => AlertDialog(
                          title: Text(blocked ? 'Unblock device?' : 'Block device?'),
                          content: Text('${device['name'] ?? mac}\n$mac\n'
                              'Only control devices on your Pi network. Blocking this phone can disconnect the app; keep another connection available to restore it.'),
                          actions: [
                            TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
                            FilledButton(onPressed: () => Navigator.pop(dialogContext, true), child: Text(blocked ? 'Unblock' : 'Block')),
                          ],
                        ),
                      );
                      if (confirmed != true || !context.mounted) return;
                      final router = context.read<RouterDeviceProvider>();
                      final operation = blocked
                          ? router.unblock(mac)
                          : router.block(mac);
                      operation.then((_) {
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text(
                              blocked
                                  ? 'Device unblocked.'
                                  : 'Pi confirmed blocking. Use a separate connection to restore this phone.',
                            ),
                          ),
                        );
                      }).catchError((Object error) {
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('Device action failed: $error')),
                        );
                      });
                    },
                    icon: Icon(
                      blocked ? Icons.lock_open : Icons.block,
                    ),
                    label: Text(
                      router.pendingControlMac == mac ? 'Waiting for Pi...' : blocked ? 'Unblock' : 'Block',
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

  Future<void> _confirmDelete(BuildContext context, Map<String, dynamic> device) async {
    final mac = device['mac'] as String? ?? '';
    final name = device['name'] as String? ?? mac;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Remove device?'),
        content: Text('$name and its detection history will be removed.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(dialogContext, true), child: const Text('Remove')),
        ],
      ),
    );
    if (confirmed == true && context.mounted) {
      await context.read<RouterDeviceProvider>().deleteDevice(mac);
    }
  }

}