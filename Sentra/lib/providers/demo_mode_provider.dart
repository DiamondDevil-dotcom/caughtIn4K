import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Persists whether the demonstration-only controls (fake data buttons) are
/// visible. Off by default so end users never see them.
class DemoModeProvider extends ChangeNotifier {
  static const _storageKey = 'demo_mode_enabled';
  bool _enabled = false;

  bool get enabled => _enabled;

  Future<void> load() async {
    final preferences = await SharedPreferences.getInstance();
    _enabled = preferences.getBool(_storageKey) ?? false;
    notifyListeners();
  }

  Future<void> setEnabled(bool value) async {
    _enabled = value;
    final preferences = await SharedPreferences.getInstance();
    await preferences.setBool(_storageKey, value);
    notifyListeners();
  }
}
