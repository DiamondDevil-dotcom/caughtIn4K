import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'dart:convert';

import 'setup_qr_screen.dart';

import '../providers/auth_provider.dart';
import '../services/cloud_api_service.dart';

class CloudGatewayScreen extends StatefulWidget {
  const CloudGatewayScreen({super.key});

  @override
  State<CloudGatewayScreen> createState() => _CloudGatewayScreenState();
}

class _CloudGatewayScreenState extends State<CloudGatewayScreen> {
  late Future<List<Map<String, dynamic>>> _choices;
  final setup = TextEditingController();
  final homeName = TextEditingController(text: 'My home');
  final invite = TextEditingController();
  String? error;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    _choices = load();
  }

  Future<List<Map<String, dynamic>>> load({bool auto = true}) async {
    final choices = await CloudApiService.gateways();
    if (auto &&
        choices.length == 1 &&
        mounted &&
        !context.read<AuthProvider>().choosingHome) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          context.read<AuthProvider>().selectCloudGateway(choices.single);
        }
      });
    }
    return choices;
  }

  @override
  void dispose() {
    setup.dispose();
    homeName.dispose();
    invite.dispose();
    super.dispose();
  }

  Future<void> join(bool pairing) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (pairing) {
        final label = jsonDecode(setup.text.trim());
        if (label is! Map ||
            label['version'] != 1 ||
            label['gateway_id'] is! String ||
            label['pairing_code'] is! String) {
          throw const FormatException(
            'Use the caughtIn4K setup QR label supplied with your Pi.',
          );
        }
        await CloudApiService.request(
          'POST',
          '/cloud/gateways/pair',
          expected: 201,
          body: {
            'gateway_id': label['gateway_id'],
            'pairing_code': label['pairing_code'],
            'household_name': homeName.text.trim(),
          },
        );
      } else {
        await CloudApiService.request(
          'POST',
          '/cloud/household-invites/accept',
          body: {'invite_code': invite.text.trim()},
        );
      }
      if (mounted) setState(() => _choices = load());
    } catch (exception) {
      if (mounted) setState(() => error = '$exception');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Your smart home'),
      actions: [
        IconButton(
          onPressed: () => context.read<AuthProvider>().signOut(),
          icon: const Icon(Icons.logout),
          tooltip: 'Sign out',
        ),
      ],
    ),
    body: FutureBuilder<List<Map<String, dynamic>>>(
      future: _choices,
      builder: (context, result) {
        if (result.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (result.hasError) {
          return Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Could not load gateways: ${result.error}',
                  textAlign: TextAlign.center,
                ),
                TextButton(
                  onPressed: () => setState(() => _choices = load()),
                  child: const Text('Retry'),
                ),
              ],
            ),
          );
        }
        final choices = result.data!;
        return ListView(
          padding: const EdgeInsets.all(24),
          children: [
            ...choices.map(
              (gateway) => ListTile(
                leading: const Icon(Icons.home_outlined),
                title: Text(gateway['household_name'] as String? ?? 'Home'),
                subtitle: Text(
                  '${gateway['name'] ?? "Gateway"} · ${gateway['role']}',
                ),
                onTap: busy
                    ? null
                    : () => context.read<AuthProvider>().selectCloudGateway(
                        gateway,
                      ),
              ),
            ),
            const Text(
              'Pair your Pi to create a home, or join a home with an invitation.',
            ),
            TextField(
              controller: homeName,
              decoration: const InputDecoration(labelText: 'Home name'),
            ),
            TextField(
              controller: setup,
              decoration: const InputDecoration(
                labelText: 'Pi setup label (or scan QR)',
              ),
            ),
            TextButton.icon(
              onPressed: busy
                  ? null
                  : () async {
                      final value = await Navigator.push<String>(
                        context,
                        MaterialPageRoute(
                          builder: (_) => const SetupQrScreen(),
                        ),
                      );
                      if (value != null && mounted) {
                        setState(() => setup.text = value);
                      }
                    },
              icon: const Icon(Icons.qr_code_scanner),
              label: const Text('Scan Pi setup QR'),
            ),
            FilledButton(
              onPressed: busy ? null : () => join(true),
              child: const Text('Pair my Pi'),
            ),
            const Divider(),
            TextField(
              controller: invite,
              decoration: const InputDecoration(
                labelText: 'Household invitation code',
              ),
            ),
            FilledButton(
              onPressed: busy ? null : () => join(false),
              child: const Text('Join home'),
            ),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        );
      },
    ),
  );
}
