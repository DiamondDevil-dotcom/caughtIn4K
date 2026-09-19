import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../providers/alert_provider.dart';
import '../widgets/liquid_glass_surface.dart';

class ActivityScreen extends StatelessWidget {
  const ActivityScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final alert = context.watch<AlertProvider>().result;

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
          _liveActivity(alert),
          const SizedBox(height: 6),

          const ActivityTile(
            time: "10:45 PM",
            title: "Port Scan Blocked",
            subtitle: "Amazon Alexa",
            color: Colors.red,
            icon: Icons.security,
          ),

          const ActivityTile(
            time: "10:42 PM",
            title: "AI Scan Completed",
            subtitle: "All Devices",
            color: Colors.green,
            icon: Icons.check_circle,
          ),

          const ActivityTile(
            time: "10:38 PM",
            title: "Device Authenticated",
            subtitle: "Smart DVR",
            color: Colors.blue,
            icon: Icons.verified_user,
          ),

          const ActivityTile(
            time: "10:31 PM",
            title: "Camera Connected",
            subtitle: "Front Door Camera",
            color: Colors.orange,
            icon: Icons.videocam,
          ),
        ],
      ),
    );
  }

  Widget _liveActivity(Map<String, dynamic>? alert) {
    final status = alert?["status"] as String? ?? "WAITING";
    final hasResult = alert?["timestamp"] != null;
    final isAlert = status == "ALERT";
    final isSafe = status == "SAFE";
    final color = isAlert
        ? Colors.redAccent
        : isSafe
            ? Colors.greenAccent
            : Colors.orangeAccent;
    final timestamp = DateTime.tryParse(alert?["timestamp"] as String? ?? "");
    final time = timestamp == null
        ? "Live"
        : "${timestamp.hour.toString().padLeft(2, '0')}:"
            "${timestamp.minute.toString().padLeft(2, '0')}:"
            "${timestamp.second.toString().padLeft(2, '0')}";

    return ActivityTile(
      time: time,
      title: hasResult
          ? "Live model: ${alert?["prediction"] ?? status}"
          : "Waiting for live traffic",
      subtitle: hasResult
          ? "${alert?["device"] ?? "IoT Device"}  |  ${alert?["confidence"] ?? 0}% confidence"
          : "Global model stream",
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
              child: Icon(
                icon,
                color: color,
              ),
            ),

            const SizedBox(width:18),

            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [

                  Text(
                    title,
                    style: GoogleFonts.spaceGrotesk(
                      fontSize:18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),

                  const SizedBox(height:4),

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