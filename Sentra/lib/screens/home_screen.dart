import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:percent_indicator/linear_percent_indicator.dart';
import 'package:provider/provider.dart';

import '../providers/alert_provider.dart';
import '../widgets/liquid_glass_button.dart';
import 'alert_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  bool isScanning = false;
  String? scanError;

  Future<void> _scanNetwork() async {
    final provider = context.read<AlertProvider>();
    setState(() {
      isScanning = true;
      scanError = null;
    });

    try {
      await provider.scanNetwork();
      if (!mounted) return;
      setState(() {
        isScanning = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        scanError = error.toString();
        isScanning = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = Provider.of<AlertProvider>(context);
    final alert = provider.result;

    final status = alert?["status"] as String? ?? "WAITING";
    final bool safe = status == "SAFE" || status == "WAITING";
    final bool uncertain = status == "UNCERTAIN";
    final double confidence = alert?["confidence"] is num
      ? (alert!["confidence"] as num).toDouble() / 100
      : 0.0;
    final results = provider.scanResults;
    final deviceCount = results.isEmpty ? 0 : results.length;
    final threatCount = results.where((item) => item["status"] == "ALERT").length;

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
          Text(
            "Good Evening ",
            style: GoogleFonts.spaceGrotesk(
              fontSize: 18,
              color: Theme.of(context).textTheme.bodyMedium?.color,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            safe
              ? (uncertain ? "Traffic needs more evidence." : "Everything looks secure.")
              : "Threat detected!",
            style: GoogleFonts.spaceGrotesk(
              fontSize: 30,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 25),

          // Main Status Card
          Card(
            child: Padding(
              padding: const EdgeInsets.all(22),
              child: Column(
                children: [
                  Icon(
                    uncertain
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
                    uncertain
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
                      ? "Your network is secure."
                      : uncertain
                          ? "Confidence: ${alert?["confidence"]}%\nCollecting more traffic..."
                          : "${alert!["prediction"]}\nConfidence: ${alert["confidence"]}%",
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
                            device: "IoT Device",
                            attack: alert!["prediction"],
                            confidence: "${alert["confidence"]}%",
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

          LiquidGlassButton(
            onPressed: isScanning ? null : _scanNetwork,
            icon: isScanning
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.search_rounded),
            label: isScanning ? "Scanning..." : "Scan Network",
          ),

          if (scanError != null) ...[
            const SizedBox(height: 12),
            Text(
              scanError!,
              style: const TextStyle(color: Colors.redAccent),
            ),
          ],

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

          Text(
            "Recent Activity",
            style: GoogleFonts.spaceGrotesk(
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),

          const SizedBox(height: 12),

          const SizedBox(height: 12),
          _recentActivity(provider),

          if (results.isNotEmpty) ...[
            const SizedBox(height: 25),
            Text(
              "Global Model Scan",
              style: GoogleFonts.spaceGrotesk(
                fontSize: 20,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 12),
            ...results.map(_scanResultCard),
          ],
        ],
      ),
    );
  }

  Widget _recentActivity(AlertProvider provider) {
    if (provider.notifications.isEmpty) {
      return Card(
        child: ListTile(
          leading: const Icon(Icons.radar),
          title: const Text("No scan activity yet"),
          subtitle: const Text("Press Scan Network to begin"),
        ),
      );
    }

    return Card(
      child: Column(
        children: provider.notifications.take(3).map((event) {
          final isAlert = event["status"] == "ALERT";
          return ListTile(
            leading: Icon(
              isAlert ? Icons.warning_amber_rounded : Icons.check_circle,
              color: isAlert ? Colors.redAccent : Colors.green,
            ),
            title: Text(
              "${event["device"]}: ${event["prediction"]}",
            ),
            subtitle: Text("${event["confidence"]}% confidence"),
          );
        }).toList(),
      ),
    );
  }

  Widget _scanResultCard(Map<String, dynamic> result) {
    final status = result["status"] as String? ?? "NO_DATA";
    final isAlert = status == "ALERT";
    final isSafe = status == "SAFE";
    final color = isAlert
        ? Colors.red
        : isSafe
            ? Colors.green
            : Colors.orange;

    return Card(
      child: ListTile(
        leading: Icon(
          isAlert ? Icons.warning_rounded : Icons.devices,
          color: color,
        ),
        title: Text(result["device"] as String? ?? "Unknown device"),
        subtitle: Text(
          status == "NO_DATA"
              ? "No traffic telemetry received"
              : "${result["prediction"]} - ${result["confidence"]}% confidence",
        ),
        trailing: Text(
          status,
          style: TextStyle(color: color, fontWeight: FontWeight.bold),
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