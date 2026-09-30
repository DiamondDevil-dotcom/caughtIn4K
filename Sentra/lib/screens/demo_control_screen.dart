import 'dart:math';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../data/demo_samples.dart';
import '../services/router_api_service.dart';
import '../widgets/liquid_glass_button.dart';

/// Demonstration-only screen: sends real labeled feature rows to the router
/// agent so a reviewer can see SAFE -> WARNING -> ALERT -> BLOCKED live,
/// without needing real attack traffic. Only reachable when Demo Mode is
/// enabled in Settings.
class DemoControlScreen extends StatefulWidget {
  const DemoControlScreen({super.key});

  @override
  State<DemoControlScreen> createState() => _DemoControlScreenState();
}

class _DemoControlScreenState extends State<DemoControlScreen> {
  static const _defaultDevice = "Galaxy Fold 8 Ultra";
  static const _defaultMac = "02:00:00:00:00:99";

  final _random = Random();
  final _deviceController = TextEditingController(text: _defaultDevice);
  final _macController = TextEditingController(text: _defaultMac);
  final _ipController = TextEditingController();
  bool _sending = false;
  String? _lastResult;
  String? _error;

  @override
  void dispose() {
    _deviceController.dispose();
    _macController.dispose();
    _ipController.dispose();
    super.dispose();
  }

  Future<void> _send(List<List<double>> samples) async {
    setState(() {
      _sending = true;
      _error = null;
    });

    try {
      final features = samples[_random.nextInt(samples.length)];
      final result = await RouterApiService.sendTelemetry(
        device: _deviceController.text.trim().isEmpty
            ? _defaultDevice
            : _deviceController.text.trim(),
        mac: _macController.text.trim().isEmpty
            ? _defaultMac
            : _macController.text.trim(),
        ipAddress: _ipController.text,
        features: features,
      );
      if (!mounted) return;
      setState(() {
        _lastResult =
            "${result["status"]} — attack confidence ${result["attack_probability"]}%";
        _sending = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.toString();
        _sending = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: Text(
          "Demo Controls",
          style: GoogleFonts.spaceGrotesk(fontWeight: FontWeight.bold, fontSize: 26),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            "For live demonstrations only. Sends real labeled traffic samples "
            "to the router agent as the connected Galaxy Fold 8 Ultra so the "
            "pipeline reacts exactly like it would to a real device.",
            style: GoogleFonts.spaceGrotesk(
              color: Theme.of(context).textTheme.bodyMedium?.color,
            ),
          ),
          const SizedBox(height: 30),
          TextField(
            controller: _deviceController,
            decoration: const InputDecoration(
              labelText: "Demonstration device",
              prefixIcon: Icon(Icons.phone_android),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _ipController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: "Device IP",
              prefixIcon: Icon(Icons.language),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _macController,
            decoration: const InputDecoration(
              labelText: "Demo MAC identity",
              prefixIcon: Icon(Icons.memory),
            ),
          ),
          const SizedBox(height: 20),
          LiquidGlassButton(
            label: _sending ? "Sending..." : "Send Normal Traffic",
            icon: const Icon(Icons.check_circle_outline),
            onPressed: _sending ? null : () => _send(demoBenignSamples),
          ),
          const SizedBox(height: 16),
          LiquidGlassButton(
            label: _sending ? "Sending..." : "Send Attack Traffic",
            icon: const Icon(Icons.warning_amber_rounded),
            destructive: true,
            onPressed: _sending ? null : () => _send(demoAttackSamples),
          ),
          const SizedBox(height: 24),
          if (_lastResult != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Text(_lastResult!),
              ),
            ),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: Colors.redAccent)),
        ],
      ),
    );
  }
}
