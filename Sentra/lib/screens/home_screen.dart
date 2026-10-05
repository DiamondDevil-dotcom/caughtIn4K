import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:percent_indicator/linear_percent_indicator.dart';
import 'package:provider/provider.dart';

import '../providers/alert_provider.dart';
import '../providers/router_device_provider.dart';
import '../widgets/liquid_glass_button.dart';
import 'alert_screen.dart';
import '../services/router_api_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  Widget build(BuildContext context) {
    final provider = Provider.of<AlertProvider>(context);
    final alert = RouterApiService.cloudMode ? null : provider.result;
    final routerProvider = context.watch<RouterDeviceProvider>();
    final routerDevices = routerProvider.devices;
    final nowSeconds = DateTime.now().millisecondsSinceEpoch / 1000;
    final onlineDevices = routerDevices.where((device) {
      if (RouterApiService.cloudMode) return true;
      final lastSeen = (device['last_seen'] as num?)?.toDouble();
      return device['online'] == true ||
          (lastSeen != null && nowSeconds - lastSeen <= 60);
    }).toList()
      ..sort((a, b) {
        const priority = {
          'BLOCKED': 4,
          'ALERT': 3,
          'ATTACK': 3,
          'WARNING': 2,
          'SAFE': 1,
        };
        final statusOrder = (priority[b['status']] ?? 0)
            .compareTo(priority[a['status']] ?? 0);
        if (statusOrder != 0) return statusOrder;
        final aNamed = (a['name'] as String? ?? '').toLowerCase() != 'unknown device';
        final bNamed = (b['name'] as String? ?? '').toLowerCase() != 'unknown device';
        if (aNamed != bNamed) return bNamed ? 1 : -1;
        return ((b['last_seen'] as num?)?.toDouble() ?? 0)
            .compareTo((a['last_seen'] as num?)?.toDouble() ?? 0);
      });
    final liveRouterDevice = onlineDevices.isEmpty ? null : onlineDevices.first;

    final status = liveRouterDevice?["status"] as String? ??
        alert?["status"] as String? ??
        "WAITING";
    final bool safe = status == "SAFE" || status == "WAITING";
    final bool uncertain = status == "WARNING" || status == "UNCERTAIN";
    final double confidence = liveRouterDevice?["attack_probability"] is num
      ? (liveRouterDevice!["attack_probability"] as num).toDouble() / 100
      : alert?["confidence"] is num
        ? (alert!["confidence"] as num).toDouble() / 100
      : 0.0;
    final deviceCount = onlineDevices.length;
    final threatCount = onlineDevices.where(
        (device) => device['status'] == 'WARNING' ||
          device['status'] == 'ALERT' || device['status'] == 'ATTACK' ||
          device['status'] == 'BLOCKED',
    ).length;

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(
          "caughtIn4K",
          style: GoogleFonts.spaceGrotesk(
            fontWeight: FontWeight.bold,
            fontSize: 28,
          ),
        ),
        centerTitle: false,
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (RouterApiService.cloudMode) ...[
            Text(routerProvider.cloudFreshness),
            if (routerProvider.lastError != null)
              Text('Cloud unavailable: ${routerProvider.lastError}'),
            const SizedBox(height: 12),
          ],
          Text(
            "Network overview",
            style: GoogleFonts.spaceGrotesk(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: Theme.of(context).textTheme.bodyMedium?.color,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            RouterApiService.cloudMode
              ? 'Last-known household monitoring'
              : safe
              ? (uncertain ? "Traffic needs more evidence." : "Everything looks secure.")
              : "Threat detected!",
            style: GoogleFonts.spaceGrotesk(
              fontSize: 28,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 20),

          // Main Status Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(22),
              child: Column(
                children: [
                  Icon(
                    RouterApiService.cloudMode && routerProvider.cloudDataStale
                      ? Icons.cloud_off
                      : uncertain
                      ? Icons.help_outline_rounded
                      : safe
                        ? Icons.verified_user
                        : Icons.warning_rounded,
                    color: uncertain
                      ? Colors.orange
                      : safe
                        ? Colors.green
                        : Colors.red,
                    size: 65,
                  ),
                  const SizedBox(height: 15),

                  Text(
                    RouterApiService.cloudMode && routerProvider.cloudDataStale
                      ? 'Data stale'
                      : RouterApiService.cloudMode && liveRouterDevice == null
                      ? 'No device data'
                      : uncertain
                      ? "Uncertain"
                      : safe
                        ? "Protected"
                        : "Threat Detected",
                    style: GoogleFonts.spaceGrotesk(
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                    ),
                  ),

                  const SizedBox(height: 8),

                  Text(
                    safe
                        ? (liveRouterDevice == null
                          ? "Waiting for Raspberry Pi telemetry."
                          : RouterApiService.cloudMode
                            ? '${onlineDevices.length} devices in the latest Pi snapshot.'
                            : "Monitoring ${onlineDevices.length} connected IoT ${onlineDevices.length == 1 ? "device" : "devices"}.")
                      : uncertain
                          ? "Rising attack confidence: ${liveRouterDevice?["attack_probability"] ?? alert?["confidence"]}%\nMonitoring closely..."
                          : "${liveRouterDevice?["prediction"] ?? alert?["prediction"]}\nConfidence: ${liveRouterDevice?["attack_probability"] ?? alert?["confidence"]}%",
                      textAlign: TextAlign.center,
                      style: GoogleFonts.spaceGrotesk(
                      color: Theme.of(context).textTheme.bodyMedium?.color,
                      fontSize: 17,
                    ),
                  ),

                  const SizedBox(height: 20),

                  LinearPercentIndicator(
                    lineHeight: 10,
                    percent: safe ? 1.0 : confidence.clamp(0.0, 1.0),
                    animation: true,
                    barRadius: const Radius.circular(20),
                    progressColor: uncertain
                      ? Colors.orange
                      : safe
                        ? Colors.green
                        : Colors.red,
                    backgroundColor: Theme.of(context).dividerColor,
                  ),

                  if (!safe) ...[
                    const SizedBox(height: 20),
                    LiquidGlassButton(
                      label: "View Details",
                      icon: const Icon(Icons.arrow_forward_rounded),
                      onPressed: () {
                        Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => AlertScreen(
                            device: liveRouterDevice?["name"] ?? "IoT Device",
                            attack: liveRouterDevice?["prediction"] ?? alert?["prediction"] ?? "Attack",
                            confidence: "${liveRouterDevice?["attack_probability"] ?? alert?["confidence"]}%",
                          ),
                        ),
                      );
                    },
                    ),
                  ],
                ],
              ),
            ),
          ),

          const SizedBox(height: 25),

          Row(
            children: [
              Expanded(
                child: _statCard(
                  "Devices",
                  deviceCount.toString(),
                  Icons.devices,
                  Colors.cyan,
                ),
              ),
              const SizedBox(width: 15),
              Expanded(
                child: _statCard(
                  "Threats",
                  threatCount.toString(),
                  Icons.security,
                  safe ? Colors.green : Colors.red,
                ),
              ),
            ],
          ),

          const SizedBox(height: 20),
          _federatedModelCard(routerProvider),
        ],
      ),
    );
  }

  Widget _federatedModelCard(RouterDeviceProvider provider) {
    if (RouterApiService.cloudMode) {
      final model = provider.federatedStatus?['cloud_model'];
      return Card(child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Pi model (cloud metadata)', style: TextStyle(fontWeight: FontWeight.bold)),
          Text(model is Map && model['available'] == true
              ? 'Checkpoint available: ${model['checkpoint_name'] ?? "unnamed"}'
              : 'Model availability not confirmed.'),
          const Text('Cloud snapshots do not report federated rounds or aggregation. '
              'Federated training runs separately on the laptop and Pi; remote training controls are not available here.'),
        ]),
      ));
    }
    final status = provider.federatedStatus;
    final training = status?['training'] is Map<String, dynamic>
        ? status!['training'] as Map<String, dynamic>
        : null;
    final trainingRunning = training?['state'] == 'running';
    final round = status?['federated_round'];
    final updatedAt = status?['updated_at'];
    final syncedAt = updatedAt is num
        ? DateTime.fromMillisecondsSinceEpoch((updatedAt * 1000).round()).toLocal()
        : null;
    final syncedLabel = syncedAt == null
        ? 'Sync time unavailable'
        : 'Updated ${syncedAt.hour.toString().padLeft(2, '0')}:${syncedAt.minute.toString().padLeft(2, '0')}';

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.hub_outlined, color: Colors.cyan),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Federated model',
                    style: GoogleFonts.spaceGrotesk(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                ),
                Text(
                  status?['aggregation'] as String? ?? 'Checking',
                  style: const TextStyle(color: Colors.cyan, fontWeight: FontWeight.w600),
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (provider.federatedStatusError != null)
              Text(
                'Model status unavailable: ${provider.federatedStatusError}',
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              )
            else if (status == null)
              const Text('Checking the Pi model checkpoint…')
            else ...[
              Text(
                round is num && round > 0
                    ? 'Pi has global model from round $round'
                    : status['status'] == 'federated'
                        ? 'Pi has received a federated global model'
                        : 'Pi is using its pretrained model',
              ),
              const SizedBox(height: 4),
              Text(
                '$syncedLabel  ·  ${status['feature_count'] ?? '—'} input features',
                style: TextStyle(color: Theme.of(context).textTheme.bodyMedium?.color),
              ),
              const SizedBox(height: 10),
              Text(
                'Laptop: coordinator + local trainer  ·  Pi: local trainer + gateway IDS',
                style: GoogleFonts.spaceGrotesk(fontSize: 12),
              ),
            ],
            if (training != null) ...[
              const SizedBox(height: 10),
              Text(
                'Training: ${training['state']}  ·  round ${training['current_round'] ?? 0}/${training['total_rounds'] ?? 10}',
                style: TextStyle(color: Theme.of(context).textTheme.bodyMedium?.color),
              ),
            ],
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: provider.federatedTrainingStarting || trainingRunning
                    ? null
                    : provider.startFederatedTraining,
                icon: provider.federatedTrainingStarting
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.sync_rounded),
                label: Text(provider.federatedTrainingStarting
                    ? 'Starting federated training…'
                  : trainingRunning
                    ? 'Training in progress'
                    : 'Update global model'),
              ),
            ),
            if (provider.federatedTrainingMessage != null) ...[
              const SizedBox(height: 8),
              Text(
                provider.federatedTrainingMessage!,
                style: TextStyle(
                  color: provider.federatedTrainingMessage!.startsWith('Exception:')
                      ? Theme.of(context).colorScheme.error
                      : Theme.of(context).textTheme.bodyMedium?.color,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _statCard(
    String title,
    String value,
    IconData icon,
    Color color,
  ) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          children: [
            Icon(
              icon,
              color: color,
              size: 32,
            ),
            const SizedBox(height: 10),
            Text(
              value,
              style: GoogleFonts.spaceGrotesk(
                fontSize: 28,
                fontWeight: FontWeight.bold,
              ),
            ),
            Text(
              title,
              style: GoogleFonts.spaceGrotesk(
                color: Theme.of(context).textTheme.bodyMedium?.color,
              ),
            ),
          ],
        ),
      ),
    );
  }
}