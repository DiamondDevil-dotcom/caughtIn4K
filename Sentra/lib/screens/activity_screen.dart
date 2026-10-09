import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../providers/activity_provider.dart';
import '../providers/router_device_provider.dart';
import '../widgets/liquid_glass_surface.dart';
import '../services/router_api_service.dart';

class ActivityScreen extends StatelessWidget {
  const ActivityScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final activity = context.watch<ActivityProvider>();
    final router = context.watch<RouterDeviceProvider>();
    final fold = router.devices.where((device) {
      final name = (device['name'] as String? ?? '').toLowerCase();
      return name.contains('fold 8') || name.contains('galaxy fold');
    }).toList();

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(
          "Activity",
          style: GoogleFonts.spaceGrotesk(
            fontSize: 28,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (!RouterApiService.cloudMode)
            _liveActivity(fold.isEmpty ? null : fold.first)
          else
            Text(router.cloudFreshness),
          const SizedBox(height: 12),
          Text(
            "Recent Detections",
            style: GoogleFonts.spaceGrotesk(
              fontSize: 18,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 12),
          if (activity.lastError != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: Text(
                "${RouterApiService.cloudMode ? "Cloud unavailable" : "Router agent unreachable"}: ${activity.lastError}",
                style: const TextStyle(color: Colors.redAccent),
              ),
            ),
          if (activity.events.isEmpty && activity.lastError == null)
            const ActivityTile(
              time: "--",
              title: "No detections yet",
              subtitle: "Events appear here as devices are classified",
              color: Colors.grey,
              icon: Icons.radar,
            ),
          ...activity.events.map((event) => _eventTile(event, router.devices)),
        ],
      ),
    );
  }

  String _eventDeviceName(
    Map<String, dynamic> event,
    List<Map<String, dynamic>> devices,
  ) {
    String? usableName(Object? value) {
      if (value is! String) return null;
      final name = value.trim();
      if (name.isEmpty ||
          const {
            'unknown',
            'unknown device',
            'device',
            'iot device',
          }.contains(name.toLowerCase()) ||
          RegExp(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$').hasMatch(name)) {
        return null;
      }
      return name;
    }

    final mac = (event['mac'] as String? ?? '').trim().toLowerCase();
    if (mac.isNotEmpty) {
      for (final device in devices) {
        if ((device['mac'] as String? ?? '').trim().toLowerCase() == mac) {
          final name = usableName(device['name']);
          if (name != null) return name;
        }
      }
    }
    return usableName(event['name']) ?? 'Unnamed device';
  }

  Widget _eventTile(
    Map<String, dynamic> event,
    List<Map<String, dynamic>> devices,
  ) {
    final status = event["status"] as String? ?? "SAFE";
    final attackProbability = (event["attack_probability"] as num? ?? 0)
        .toDouble();
    final isAttack =
        status == "WARNING" ||
        status == "ALERT" ||
        status == "ATTACK" ||
        status == "BLOCKED";
    final confidence = isAttack ? attackProbability : 100 - attackProbability;
    final confidenceLabel = isAttack
        ? "attack confidence"
        : "benign confidence";
    final color =
        {
          "SAFE": Colors.green,
          "WARNING": Colors.orange,
          "ALERT": Colors.red,
          "BLOCKED": Colors.grey,
        }[status] ??
        Colors.blueGrey;
    final icon =
        {
          "SAFE": Icons.check_circle,
          "WARNING": Icons.warning_amber_rounded,
          "ALERT": Icons.error,
          "BLOCKED": Icons.block,
        }[status] ??
        Icons.radar;
    final timestamp = event["timestamp"] is num
        ? DateTime.fromMillisecondsSinceEpoch(
            (event["timestamp"] as num).toInt() * 1000,
          )
        : event["timestamp"] is String
        ? DateTime.tryParse(event["timestamp"] as String)?.toLocal()
        : null;
    final time = timestamp == null
        ? "--"
        : "${timestamp.hour.toString().padLeft(2, '0')}:"
              "${timestamp.minute.toString().padLeft(2, '0')}:"
              "${timestamp.second.toString().padLeft(2, '0')}";

    return ActivityTile(
      time: time,
      title: "${_eventDeviceName(event, devices)}: $status",
      subtitle: "${confidence.toStringAsFixed(2)}% $confidenceLabel",
      color: color,
      icon: icon,
    );
  }

  Widget _liveActivity(Map<String, dynamic>? device) {
    final status = device?["status"] as String? ?? "WAITING";
    final isAlert = status == "ALERT" || status == "BLOCKED";
    final isSafe = status == "SAFE";
    final color = isAlert
        ? Colors.redAccent
        : isSafe
        ? Colors.greenAccent
        : Colors.orangeAccent;
    final time = "Live";
    final liveDevice = device;
    final attackProbability = (device?["attack_probability"] as num? ?? 0)
        .toDouble();
    final confidence = isAlert || status == "WARNING"
        ? attackProbability
        : 100 - attackProbability;
    final confidenceLabel = isAlert || status == "WARNING"
        ? "attack confidence"
        : "benign confidence";

    return ActivityTile(
      time: time,
      title: liveDevice == null
          ? "Waiting for live traffic"
          : "Live model: ${liveDevice["prediction"] ?? status}",
      subtitle: liveDevice == null
          ? "Router telemetry stream"
          : "${liveDevice["name"] ?? "IoT device"}  |  ${confidence.toStringAsFixed(2)}% $confidenceLabel",
      color: color,
      icon: isAlert
          ? Icons.warning_amber_rounded
          : isSafe
          ? Icons.check_circle
          : Icons.radar,
    );
  }
}

class ActivityTile extends StatelessWidget {
  final String time;
  final String title;
  final String subtitle;
  final IconData icon;
  final Color color;

  const ActivityTile({
    super.key,
    required this.time,
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: LiquidGlassSurface(
        padding: const EdgeInsets.all(18),
        child: Row(
          children: [
            CircleAvatar(
              radius: 24,
              backgroundColor: color.withOpacity(.15),
              child: Icon(icon, color: color),
            ),

            const SizedBox(width: 18),

            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: GoogleFonts.spaceGrotesk(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),

                  const SizedBox(height: 4),

                  Text(
                    subtitle,
                    style: GoogleFonts.spaceGrotesk(
                      color: Theme.of(context).textTheme.bodyMedium?.color,
                    ),
                  ),
                ],
              ),
            ),

            Text(
              time,
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
