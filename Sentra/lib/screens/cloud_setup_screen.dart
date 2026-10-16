import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/cloud_api_service.dart';

class CloudSetupScreen extends StatefulWidget {
  const CloudSetupScreen({super.key, required this.gateway});

  final Map<String, dynamic> gateway;

  @override
  State<CloudSetupScreen> createState() => _CloudSetupScreenState();
}

class _CloudSetupScreenState extends State<CloudSetupScreen> {
  final _form = GlobalKey<FormState>();
  final _ssid = TextEditingController();
  final _password = TextEditingController();
  Timer? _timer;
  Map<String, dynamic>? _status;
  String? _error;
  String? _attempt;
  bool _saving = false;
  bool _polling = false;
  bool _showPassword = false;
  int _generation = 0;

  String get _path =>
      '/cloud/households/${widget.gateway['household_id']}'
      '/gateways/${widget.gateway['gateway_id']}/setup';
  bool get _canConfigure => {'owner', 'admin'}.contains(widget.gateway['role']);

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _ssid.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _refresh({bool afterSave = false}) async {
    if (_polling || (_saving && !afterSave)) return;
    _polling = true;
    final generation = _generation;
    try {
      final status = await CloudApiService.request('GET', _path);
      if (status['ready'] is! bool ||
          status['recent_contact'] is! bool ||
          status['configured'] is! bool ||
          status['expired'] is! bool ||
          status['checks'] is! Map<String, dynamic>) {
        throw const FormatException('Invalid gateway setup status.');
      }
      if (mounted && generation == _generation) {
        setState(() {
          _status = status;
          _error = null;
        });
      }
    } catch (exception) {
      if (mounted && generation == _generation) {
        setState(() {
          // A failed refresh must not leave an old "ready" button enabled.
          _status = null;
          _error = '$exception';
        });
      }
    } finally {
      _polling = false;
    }
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _generation++;
      _error = null;
      _status = null;
      _attempt ??= CloudApiService.newSetupRequestId();
    });
    try {
      final result = await CloudApiService.request(
        'PUT',
        _path,
        body: {
          'request_id': _attempt,
          'ssid': _ssid.text,
          'password': _password.text,
        },
      );
      if (result['request_id'] != _attempt) {
        throw const FormatException(
          'The service did not acknowledge this Wi-Fi setup attempt.',
        );
      }
      if (!mounted) return;
      _password.clear();
      _attempt = null;
      await _refresh(afterSave: true);
    } catch (exception) {
      if (mounted) setState(() => _error = '$exception');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    final recent = status?['recent_contact'] == true;
    final checks = status?['checks'] as Map<String, dynamic>? ?? {};
    final pending =
        status?['request_id'] != null &&
        status?['configured'] != true &&
        status?['expired'] != true;
    return Scaffold(
      appBar: AppBar(title: const Text('Set up your caughtIn4K')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Text(
            'Connect your caughtIn4K to your home router with an Ethernet cable, '
            'then connect its power supply. Keep Ethernet connected.',
          ),
          const SizedBox(height: 16),
          Text(
            recent
                ? 'Gateway connected'
                : 'Waiting for your gateway to connect',
          ),
          const Text(
            'Your IoT devices will join the new Wi-Fi network below. '
            'This does not change your home router Wi-Fi.',
          ),
          if (_canConfigure)
            Form(
              key: _form,
              child: Column(
                children: [
                  TextFormField(
                    controller: _ssid,
                    enabled: !_saving,
                    decoration: const InputDecoration(
                      labelText: 'IoT Wi-Fi name',
                    ),
                    onChanged: (_) => _attempt = null,
                    validator: (value) {
                      final name = value ?? '';
                      if (utf8.encode(name).isEmpty ||
                          utf8.encode(name).length > 32 ||
                          name.codeUnits.any((c) => c < 32 || c == 127)) {
                        return 'Use a name of 1–32 bytes without control characters.';
                      }
                      return null;
                    },
                  ),
                  TextFormField(
                    controller: _password,
                    enabled: !_saving,
                    obscureText: !_showPassword,
                    autocorrect: false,
                    enableSuggestions: false,
                    decoration: InputDecoration(
                      labelText: 'IoT Wi-Fi password',
                      suffixIcon: IconButton(
                        tooltip: _showPassword
                            ? 'Hide password'
                            : 'Show password',
                        onPressed: () =>
                            setState(() => _showPassword = !_showPassword),
                        icon: Icon(
                          _showPassword
                              ? Icons.visibility_off
                              : Icons.visibility,
                        ),
                      ),
                    ),
                    onChanged: (_) => _attempt = null,
                    validator: (value) {
                      final password = value ?? '';
                      if (password.length < 8 ||
                          password.length > 63 ||
                          password.codeUnits.any((c) => c < 32 || c > 126)) {
                        return 'Use 8–63 printable ASCII characters.';
                      }
                      return null;
                    },
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: _saving ? null : _save,
                    child: Text(
                      _saving ? 'Sending Wi-Fi settings…' : 'Set up IoT Wi-Fi',
                    ),
                  ),
                ],
              ),
            )
          else
            const Text(
              'A household owner or admin must choose the Wi-Fi settings.',
            ),
          if (pending)
            const Text(
              'Wi-Fi settings sent. Waiting for the Pi to apply and check them.',
            ),
          if (status?['expired'] == true)
            const Text(
              'This setup attempt expired. Reconnect the Pi and send your Wi-Fi settings again.',
            ),
          if (status?['error_code'] != null)
            const Text(
              'The Pi could not apply the Wi-Fi settings. Check its Ethernet and power, then try again.',
            ),
          const SizedBox(height: 16),
          for (final entry in const {
            'ethernet': 'Ethernet uplink',
            'wifi': 'IoT Wi-Fi access point',
            'router': 'Gateway service',
            'model': 'Local model loaded',
            'firewall': 'Network controls loaded',
          }.entries)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(
                recent && checks[entry.key] == true
                    ? Icons.check_circle_outline
                    : Icons.hourglass_empty,
              ),
              title: Text(entry.value),
            ),
          const Text(
            'Setup checks confirm network and service availability, not validated '
            'live threat detection. Packet capture remains in observation mode.',
          ),
          if (_error != null)
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          TextButton(
            onPressed: _refresh,
            child: const Text('Refresh setup checks'),
          ),
          FilledButton(
            onPressed: status?['ready'] == true && !_saving
                ? () => Navigator.pop(context, true)
                : null,
            child: const Text('Open my home'),
          ),
        ],
      ),
    );
  }
}
