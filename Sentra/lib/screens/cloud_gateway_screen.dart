import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'setup_qr_screen.dart';
import 'cloud_setup_screen.dart';
import 'assistant_screen.dart';
import '../models/setup_label.dart';

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
  final orderReference = TextEditingController();
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
          openGateway(choices.single);
        }
      });
    }
    return choices;
  }

  Future<void> openGateway(Map<String, dynamic> gateway) async {
    if (gateway['consumer_setup'] == true) {
      final ready = await Navigator.push<bool>(
        context,
        MaterialPageRoute(builder: (_) => CloudSetupScreen(gateway: gateway)),
      );
      if (!mounted || ready != true) return;
    }
    if (mounted) context.read<AuthProvider>().selectCloudGateway(gateway);
  }

  @override
  void dispose() {
    setup.dispose();
    homeName.dispose();
    invite.dispose();
    orderReference.dispose();
    super.dispose();
  }

  Future<void> join(bool pairing) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (pairing) {
        final label = SetupLabel.parse(setup.text.trim());
        final paired = await CloudApiService.request(
          'POST',
          '/cloud/gateways/pair',
          expected: 201,
          body: {
            'gateway_id': label.gatewayId,
            'pairing_code': label.pairingCode,
            'household_name': homeName.text.trim(),
          },
        );
        final choices = await load(auto: false);
        if (!mounted) return;
        setState(() {
          _choices = Future.value(choices);
        });
        final gateway = choices.singleWhere(
          (gateway) => gateway['gateway_id'] == paired['gateway_id'],
          orElse: () => throw const FormatException(
            'The Pi was paired, but its home could not be loaded. Refresh your homes to resume setup.',
          ),
        );
        setup.clear();
        await openGateway(gateway);
      } else {
        await CloudApiService.request(
          'POST',
          '/cloud/household-invites/accept',
          body: {'invite_code': invite.text.trim()},
        );
      }
      if (mounted && !pairing) {
        setState(() {
          _choices = load();
        });
      }
    } catch (exception) {
      if (mounted) setState(() => error = '$exception');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> emailSetupQr() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final label = SetupLabel.parse(setup.text.trim());
      final result = await CloudApiService.request(
        'POST',
        '/cloud/gateways/email-setup-qr',
        body: {
          'gateway_id': label.gatewayId,
          'pairing_code': label.pairingCode,
        },
      );
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(result['message'] as String)));
      }
    } catch (exception) {
      if (mounted) setState(() => error = '$exception');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> replaceSetupQr() async {
    final order = orderReference.text.trim();
    if (order.isEmpty) {
      setState(() => error = 'Enter the order reference for this Pi.');
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await CloudApiService.request(
        'POST',
        '/cloud/gateways/replace-setup-qr',
        body: {'order_reference': order},
      );
      if (mounted) {
        setup.clear();
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(result['message'] as String)));
      }
    } catch (exception) {
      if (mounted) setState(() => error = '$exception');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      leading: IconButton(
        tooltip: 'AI help',
        icon: const Icon(Icons.chat_bubble_outline),
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const AssistantScreen()),
        ),
      ),
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
                  onPressed: () => setState(() {
                    _choices = load();
                  }),
                  child: const Text('Retry'),
                ),
              ],
            ),
          );
        }
        final choices = result.data!;
        return Column(
          children: [
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(24),
                children: [
                  ...choices.map(
                    (gateway) => ListTile(
                      leading: const Icon(Icons.home_outlined),
                      title: Text(
                        gateway['household_name'] as String? ?? 'Home',
                      ),
                      subtitle: Text(
                        '${gateway['name'] ?? "Gateway"} · ${gateway['role']}',
                      ),
                      onTap: busy ? null : () => openGateway(gateway),
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
                  TextButton.icon(
                    onPressed: busy ? null : emailSetupQr,
                    icon: const Icon(Icons.mail_outline),
                    label: const Text('Email my setup QR'),
                  ),
                  const Text(
                    'Scan or enter your new Pi label first. A copy is sent only to your '
                    'verified account email. It expires at the original time and works '
                    'only until the Pi is paired. Existing homes are not changed.',
                  ),
                  const Divider(),
                  const Text(
                    'Lost your QR before pairing? Request a replacement using the '
                    'order linked to your verified email. This invalidates earlier '
                    'QR codes. Already paired? Sign in to your existing home instead.',
                  ),
                  TextField(
                    controller: orderReference,
                    decoration: const InputDecoration(
                      labelText: 'Pi order reference',
                    ),
                  ),
                  TextButton.icon(
                    onPressed: busy ? null : replaceSetupQr,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Request replacement setup QR'),
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
                ],
              ),
            ),
          ],
        );
      },
    ),
  );
}
