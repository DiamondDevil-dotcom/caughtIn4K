import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../widgets/liquid_glass_button.dart';

class AlertScreen extends StatelessWidget {
  final String device;
  final String attack;
  final String confidence;

  const AlertScreen({
    super.key,
    required this.device,
    required this.attack,
    required this.confidence,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xff0B0B0F),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [

              const SizedBox(height: 40),

              const Icon(
                Icons.warning_rounded,
                color: Colors.red,
                size: 90,
              ),

              const SizedBox(height: 25),

              Text(
                "INTRUSION DETECTED",
                style: GoogleFonts.spaceGrotesk(
                  fontSize: 30,
                  fontWeight: FontWeight.bold,
                  color: Colors.red,
                ),
              ),

              const SizedBox(height: 40),

              _info("Device", device),
              _info("Attack", attack),
              _info("Confidence", confidence),
              _info("Status", "Blocked"),

              const Spacer(),

              LiquidGlassButton(
                icon: const Icon(Icons.check_rounded),
                label: "Dismiss",
                destructive: true,
                onPressed: () {
                  Navigator.pop(context);
                },
              ),

              const SizedBox(height: 18),
            ],
          ),
        ),
      ),
    );
  }

  Widget _info(String title, String value) {
    return Card(
      margin: const EdgeInsets.only(bottom: 15),
      child: ListTile(
        title: Text(title),
        trailing: Text(
          value,
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
      ),
    );
  }
}