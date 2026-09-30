import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/device.dart';

class DeviceProvider extends ChangeNotifier {
  static const _storageKey = 'connected_devices';
  final List<Device> _devices = [];

  List<Device> get devices => List.unmodifiable(_devices);
  List<String> get deviceNames => _devices.map((device) => device.name).toList();

  Future<void> load() async {
    final preferences = await SharedPreferences.getInstance();
    final stored = preferences.getString(_storageKey);
    if (stored == null) {
      _devices.add(const Device(
        id: 'raspberry-pi-node-1',
        name: 'Raspberry Pi Node 1',
        location: 'Home network',
        ip: 'Set your Pi IP',
        mac: 'Not configured',
        manufacturer: 'Raspberry Pi',
        firmware: 'Pi telemetry agent',
      ));
      await _save();
    } else {
      final entries = jsonDecode(stored) as List<dynamic>;
      _devices.addAll(entries
          .map((entry) => Device.fromJson(entry))
          .where((device) => device.id != 'raspberry-pi-node-1'));
      await _save();
    }
    notifyListeners();
  }

  Future<void> add(Device device) async {
    _devices.add(device);
    await _save();
    notifyListeners();
  }

  Future<void> remove(String id) async {
    _devices.removeWhere((device) => device.id == id);
    await _save();
    notifyListeners();
  }

  Future<void> _save() async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(
      _storageKey,
      jsonEncode(_devices.map((device) => device.toJson()).toList()),
    );
  }
}