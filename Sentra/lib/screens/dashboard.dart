import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:percent_indicator/circular_percent_indicator.dart';

class Dashboard extends StatefulWidget {
  const Dashboard({super.key});

  @override
  State<Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<Dashboard> {
  Map<String, dynamic>? result;
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: ListView(
            children: [

              Text(
                "caughtIn4K",
                style: GoogleFonts.orbitron(
                  color: Colors.cyanAccent,
                  fontSize: 30,
                  fontWeight: FontWeight.bold,
                ),
              ),

              const SizedBox(height: 5),

              Text(
                "Nothing Escapes Detection.",
                style: GoogleFonts.poppins(
                  color: Colors.white70,
                  fontSize: 14,
                ),
              ),

              const SizedBox(height: 35),

              Center(
                child: CircularPercentIndicator(
                  radius: 90,
                  lineWidth: 12,
                  animation: true,
                  animationDuration: 1800,
                    percent: result == null
                      ? 0
                      : ((result!["confidence"] as num) / 100).clamp(0.0, 1.0),
                  circularStrokeCap: CircularStrokeCap.round,
                  progressColor: Colors.cyanAccent,
                  backgroundColor: Colors.white12,
                  center: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.shield,
                        color: Colors.greenAccent,
                        size: 42,
                      ),
                      SizedBox(height: 10),
                      Text(
                        result == null
                        ? "Loading..."
                        : "${(result!["confidence"] as num).toStringAsFixed(2)}%",
                        style: GoogleFonts.orbitron(
                          fontSize: 28,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      Text(
                        "AI Confidence",
                        style: GoogleFonts.poppins(
                          fontSize: 12,
                          color: Colors.white60,
                        ),
                      )
                    ],
                  ),
                ),
              ),

              const SizedBox(height: 35),

              Row(
                children: [

                  Expanded(
                    child: _statCard(
                      "Threats",
                      "14",
                      Colors.redAccent,
                      Icons.warning,
                    ),
                  ),

                  SizedBox(width: 15),

                  Expanded(
                    child: _statCard(
                      "Devices",
                      "3",
                      Colors.greenAccent,
                      Icons.devices,
                    ),
                  ),
                ],
              ),

              const SizedBox(height: 30),

              Text(
                "Connected Devices",
                style: GoogleFonts.orbitron(
                  fontSize: 18,
                  color: Colors.white,
                ),
              ),

              const SizedBox(height: 15),

              _device("Alexa", true),
              _device("DVR", true),
              _device("Security Camera", true),

              const SizedBox(height: 30),

              Text(
                "Recent Activity",
                style: GoogleFonts.orbitron(
                  fontSize: 18,
                ),
              ),

              const SizedBox(height: 10),

              _activity(
                  Icons.check_circle,
                  Colors.green,
                  "Normal Traffic"),

              _activity(
                  Icons.warning_amber_rounded,
                  Colors.orange,
                  "Port Scan Detected"),

              _activity(
                  Icons.security,
                  Colors.red,
                  "DDoS Attempt Blocked"),

              _activity(
                  Icons.check_circle,
                  Colors.green,
                  "Device Authenticated"),
            ],
          ),
        ),
      ),
    );
  }

  Widget _statCard(
      String title,
      String value,
      Color color,
      IconData icon,
      ) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xff151922),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 34),
          SizedBox(height: 12),
          Text(
            value,
            style: GoogleFonts.orbitron(
              fontSize: 34,
              color: color,
              fontWeight: FontWeight.bold,
            ),
          ),
          Text(
            title,
            style: GoogleFonts.poppins(),
          ),
        ],
      ),
    );
  }

  Widget _device(String name, bool safe) {
    return Card(
      color: const Color(0xff151922),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
      ),
      child: ListTile(
        leading: Icon(
          Icons.memory,
          color: Colors.cyanAccent,
        ),
        title: Text(
          name,
          style: GoogleFonts.poppins(),
        ),
        trailing: Container(
          padding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 5),
          decoration: BoxDecoration(
            color: safe ? Colors.green : Colors.red,
            borderRadius: BorderRadius.circular(30),
          ),
          child: Text(
            safe ? "SAFE" : "ALERT",
          ),
        ),
      ),
    );
  }

  Widget _activity(
      IconData icon,
      Color color,
      String text,
      ) {
    return Card(
      color: const Color(0xff151922),
      child: ListTile(
        leading: Icon(icon, color: color),
        title: Text(
          text,
          style: GoogleFonts.poppins(),
        ),
      ),
    );
  }
}