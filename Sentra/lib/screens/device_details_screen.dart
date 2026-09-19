import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/device.dart';

class DeviceDetailsScreen extends StatelessWidget {
  final Device device;

  const DeviceDetailsScreen({
    super.key,
    required this.device,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(device.name),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(25),
              child: Column(
                children: [
                  CircleAvatar(
                    radius: 40,
                    backgroundColor: device.safe
                        ? Colors.green.withOpacity(.15)
                        : Colors.red.withOpacity(.15),
                    child: Icon(
                      device.safe
                          ? Icons.shield
                          : Icons.warning_rounded,
                      color: device.safe
                          ? Colors.green
                          : Colors.red,
                      size: 40,
                    ),
                  ),

                  const SizedBox(height: 15),

                  Text(
                    device.safe
                        ? "Protected"
                        : "Threat Detected",
                    style: GoogleFonts.spaceGrotesk(
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                    ),
                  ),

                  if (!device.safe)
                    Padding(
                      padding: const EdgeInsets.only(top: 10),
                      child: Text(
                        device.attack ?? "",
                        style: const TextStyle(
                          color: Colors.red,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 20),

          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.location_on),
                  title: const Text("Location"),
                  subtitle: Text(device.location),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.language),
                  title: const Text("IP Address"),
                  subtitle: Text(device.ip),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.memory),
                  title: const Text("MAC Address"),
                  subtitle: Text(device.mac),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.business),
                  title: const Text("Manufacturer"),
                  subtitle: Text(device.manufacturer),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: const Icon(Icons.system_update),
                  title: const Text("Firmware"),
                  subtitle: Text(device.firmware),
                ),
              ],
            ),
          ),

          const SizedBox(height: 20),

          Text(
            "Recent Activity",
            style: GoogleFonts.spaceGrotesk(
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),

          const SizedBox(height: 10),

          const Card(
            child: Column(
              children: [
                ListTile(
                  leading: Icon(
                    Icons.check_circle,
                    color: Colors.green,
                  ),
                  title: Text("Device Connected"),
                ),
                Divider(height: 1),
                ListTile(
                  leading: Icon(
                    Icons.check_circle,
                    color: Colors.green,
                  ),
                  title: Text("Authentication Successful"),
                ),
                Divider(height: 1),
                ListTile(
                  leading: Icon(
                    Icons.check_circle,
                    color: Colors.green,
                  ),
                  title: Text("Network Scan Completed"),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}