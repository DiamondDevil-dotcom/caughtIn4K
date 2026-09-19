import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../data/devices.dart';
import '../models/device.dart';
import '../providers/alert_provider.dart';
import '../widgets/device_card.dart';

class DevicesScreen extends StatelessWidget {
  const DevicesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final alert = Provider.of<AlertProvider>(context).result;

    final List<Device> updatedDevices = devices.map((device) {
      if (alert != null) {
        return Device(
          name: device.name,
          location: device.location,
          ip: device.ip,
          mac: device.mac,
          manufacturer: device.manufacturer,
          firmware: device.firmware,
          safe: false,
          attack: alert["prediction"],
        );
      }
      return device;
    }).toList();

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Devices"),
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(20),
        itemCount: updatedDevices.length,
        itemBuilder: (context, index) {
          return DeviceCard(
            device: updatedDevices[index],
          );
        },
      ),
    );
  }
}