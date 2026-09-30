import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/device.dart';
import '../screens/device_details_screen.dart';
import 'liquid_glass_surface.dart';

class DeviceCard extends StatelessWidget {
  final Device device;

  const DeviceCard({
    super.key,
    required this.device,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: LiquidGlassSurface(
        child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => DeviceDetailsScreen(device: device),
            ),
          );
        },
        child: ListTile(
          contentPadding: const EdgeInsets.all(18),
          leading: CircleAvatar(
            radius: 26,
            backgroundColor: device.safe
                ? Colors.green.withOpacity(.15)
                : Colors.red.withOpacity(.15),
            child: Icon(
              device.safe ? Icons.shield : Icons.warning_rounded,
              color: device.safe ? Colors.green : Colors.red,
            ),
          ),
          title: Text(
            device.name,
            style: GoogleFonts.spaceGrotesk(
              fontWeight: FontWeight.bold,
              fontSize: 18,
            ),
          ),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 4),
              Text(device.location),
              const SizedBox(height: 6),
              Text("${device.ip}  |  ${device.mac}"),
              const SizedBox(height: 6),
              Text(
                device.safe
                    ? "Protected"
                    : (device.attack ?? "Threat Detected"),
                style: TextStyle(
                  color: device.safe ? Colors.green : Colors.red,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
          trailing: const Icon(Icons.chevron_right),
        ),
        ),
      ),
    );
  }
}