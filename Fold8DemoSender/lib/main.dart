import 'dart:convert';
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() {
  runApp(const Fold8UltraSenderApp());
}

class Fold8UltraSenderApp extends StatelessWidget {
  const Fold8UltraSenderApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'caughtIn4K Demo Data Sender',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF6EE7B7),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFF07131D),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFF112330),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: BorderSide.none,
          ),
        ),
      ),
      home: const SenderHomePage(),
    );
  }
}

class SenderHomePage extends StatefulWidget {
  const SenderHomePage({super.key});

  @override
  State<SenderHomePage> createState() => _SenderHomePageState();
}

class _SenderHomePageState extends State<SenderHomePage> {
  static const String _device = String.fromEnvironment(
    'SENDER_DEVICE_NAME',
    defaultValue: 'Galaxy S26 Ultra',
  );
  static const List<List<double>> _normalSamples = <List<double>>[
    [2040708.8, 0, 0, 0, 0, 0, 1, 6885, 351.4, 0.0033692836761474, 5.5, 51.37602988175922, 1814773.306476049, 38.5],
    [1316921.1, 0, 0, 0, 0, 0, 1, 1541.7, 54, 166521297.9600573, 13.5, 14.189893972479284, 5830.422316713137, 244.6],
    [2778496.2, 0, 0, 0, 0, 0, 1, 5610, 50, 166522778.4173835, 13.5, 27.27128643119084, 329113.3750098472, 244.6],
  ];
  static const List<List<double>> _attackSamples = <List<double>>[
    [13003.2001953125, 0, 0, 0, 0, 0, 0, 1714.4000244140625, 60, 166853984, 13.5, 14.780466079711914, 4108.95166015625, 244.60000610351562],
    [350092.03125, 0, 0, 0, 0, 0, 1, 11604.0595703125, 772.489990234375, 83250016, 9.5, 45.54241180419922, 123196.859375, 141.5500030517578],
    [451535, 0, 0, 0, 0, 0, 1, 13317.5498046875, 582.239990234375, 82947080, 9.5, 48.85536575317383, 469626.46875, 141.5500030517578],
  ];

  final TextEditingController _routerApiUrlController = TextEditingController(
    text: const String.fromEnvironment(
      'ROUTER_API_URL',
      defaultValue: 'http://192.168.50.1:8001',
    ),
  );
  final TextEditingController _ipController = TextEditingController(
    text: const String.fromEnvironment(
      'FOLD_DEVICE_IP',
      defaultValue: '',
    ),
  );
  final TextEditingController _macController = TextEditingController(
    text: const String.fromEnvironment(
      'FOLD_DEVICE_MAC',
      defaultValue: '02:00:00:00:00:99',
    ),
  );

  bool _isSending = false;
  bool _streaming = false;
  Timer? _streamTimer;
  String _status = 'Ready to send telemetry.';
  String _attackConfidence = '—';
  bool _lastRequestWasAttack = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _startNormalStream());
  }

  @override
  void dispose() {
    _routerApiUrlController.dispose();
    _ipController.dispose();
    _macController.dispose();
    _streamTimer?.cancel();
    super.dispose();
  }

  void _startNormalStream() {
    _streamTimer?.cancel();
    setState(() {
      _streaming = true;
      _status = 'Live normal telemetry is running.';
    });
    _sendTelemetry(attack: false);
    _streamTimer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => _sendTelemetry(attack: false),
    );
  }

  Future<void> _sendTelemetry({required bool attack}) async {
    final baseUrl = _routerApiUrlController.text.trim().replaceFirst(
          RegExp(r'/+$'),
          '',
        );
    if (baseUrl.isEmpty) {
      setState(() => _status = 'Enter a router API URL first.');
      return;
    }

    Uri endpoint;
    try {
      endpoint = Uri.parse('$baseUrl/telemetry');
      if (endpoint.scheme != 'http' && endpoint.scheme != 'https') {
        throw const FormatException('Unsupported URL scheme');
      }
    } on FormatException {
      setState(() => _status = 'Enter a valid HTTP or HTTPS router URL.');
      return;
    }

    final ip = _ipController.text.trim();
    final mac = _macController.text.trim().toLowerCase();
    if (!RegExp(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$').hasMatch(mac)) {
      setState(() => _status = 'Enter the Fold MAC in aa:bb:cc:dd:ee:ff format.');
      return;
    }
    final payload = <String, dynamic>{
      'device': _device,
      'mac': mac,
      'features': (attack ? _attackSamples : _normalSamples)[
        DateTime.now().microsecondsSinceEpoch %
            (attack ? _attackSamples.length : _normalSamples.length)
      ],
      'traffic_type': attack ? 'attack' : 'normal',
    };
    if (ip.isNotEmpty) {
      payload['ip_address'] = ip;
    }

    setState(() {
      _isSending = true;
      _lastRequestWasAttack = attack;
      _status = 'Sending one ${attack ? 'attack' : 'normal'} demo sample...';
      _attackConfidence = '—';
    });

    try {
      final response = await http
          .post(
            endpoint,
            headers: const <String, String>{
              'Content-Type': 'application/json',
              'Accept': 'application/json',
            },
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 15));

      String confidence = '—';
      String prediction = '';
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          final value = decoded['attack_probability'] ??
              decoded['attack_confidence'] ??
              decoded['confidence'] ??
              decoded['attackConfidence'];
          if (value is num) {
            final displayed = attack ? value.toDouble() : 100 - value.toDouble();
            confidence = '${displayed.toStringAsFixed(2)}%';
          } else if (value != null) {
            confidence = '${value.toString()}%';
          }
          prediction = (decoded['prediction'] ?? decoded['status'] ?? '').toString();
        }
      } on FormatException {
        // A non-JSON response is still reported by its HTTP status.
      }

      if (!mounted) return;
      setState(() {
        _isSending = false;
        _attackConfidence = confidence;
        _status = response.statusCode >= 200 && response.statusCode < 300
            ? 'Telemetry accepted${prediction.isEmpty ? '' : ': $prediction'} (${response.statusCode}).'
            : 'Request failed (${response.statusCode}).';
      });
    } on Exception catch (error) {
      if (!mounted) return;
      setState(() {
        _isSending = false;
        _status = 'Unable to send telemetry: ${error.toString().replaceFirst('Exception: ', '')}';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Demo Data Sender'),
        centerTitle: false,
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: <Widget>[
            const SizedBox(height: 18),
            Image.asset(
              'assets/caughtIn4K Test.png',
              width: 64,
              height: 64,
              fit: BoxFit.contain,
              semanticLabel: 'caughtIn4K',
            ),
            const SizedBox(height: 16),
            Text(
              'caughtIn4K Demo Data Sender',
              textAlign: TextAlign.center,
              style: theme.textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            Text(
              'Send labeled normal and attack samples to the Pi gateway.',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(color: Colors.white60),
            ),
            const SizedBox(height: 28),
            TextField(
              controller: _routerApiUrlController,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Router API URL',
                hintText: 'http://<PI_IP>:8001',
                prefixIcon: Icon(Icons.router),
              ),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _ipController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Device IP',
                hintText: '10.170.97.x',
                prefixIcon: Icon(Icons.lan),
              ),
            ),
            const SizedBox(height: 20),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text('Device', style: theme.textTheme.labelLarge),
                    const SizedBox(height: 6),
                    const Text(_device),
                    const SizedBox(height: 10),
                    Text('Device MAC address', style: theme.textTheme.labelLarge),
                    const SizedBox(height: 4),
                    Text(
                      'The Pi identifies the connected phone from its network lease. This MAC is used only if that lookup is unavailable.',
                      style: theme.textTheme.bodySmall?.copyWith(color: Colors.white60),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _macController,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        hintText: 'aa:bb:cc:dd:ee:ff',
                        prefixIcon: Icon(Icons.fingerprint),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _isSending ? null : () => _sendTelemetry(attack: false),
              icon: const Icon(Icons.play_arrow),
              label: const Text('Send Normal Demo Once'),
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(56)),
            ),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              onPressed: _isSending ? null : () => _sendTelemetry(attack: true),
              icon: const Icon(Icons.warning_amber),
              label: const Text('Send Attack Demo Once'),
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(56)),
            ),
            if (_isSending) ...<Widget>[
              const SizedBox(height: 20),
              const LinearProgressIndicator(),
            ],
            const SizedBox(height: 20),
            Card(
              color: theme.colorScheme.surfaceContainerHighest,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text('Response', style: theme.textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Text(_status),
                    if (_streaming) ...[
                      const SizedBox(height: 8),
                      Text('Sending one model sample every 10 seconds.'),
                    ],
                    const SizedBox(height: 8),
                    Text(
                      '${_lastRequestWasAttack ? 'Attack' : 'Benign'} confidence: $_attackConfidence',
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: _lastRequestWasAttack
                            ? theme.colorScheme.error
                            : null,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
