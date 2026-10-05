import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/api_service.dart';
import '../services/notification_service.dart';
import '../services/push_notification_service.dart';

class AlertProvider extends ChangeNotifier {
  Map<String, dynamic>? result;
  List<Map<String, dynamic>> scanResults = [];
  final List<Map<String, dynamic>> notifications = [];
  bool notificationsEnabled = true;
  final Map<String, String> _lastNotifiedStatus = {};
  Timer? _pollingTimer;

  AlertProvider() {
    _loadNotificationPreference();
  }

  Future<void> _loadNotificationPreference() async {
    final prefs = await SharedPreferences.getInstance();
    notificationsEnabled = prefs.getBool("notificationsEnabled") ?? true;
    notifyListeners();
  }

  Future<void> setNotificationsEnabled(bool value) async {
    if (value) await NotificationService.initialize();
    await PushNotificationService.sync(enabled: value);
    notificationsEnabled = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool("notificationsEnabled", value);
    notifyListeners();
  }

  void clearCachedData() {
    result = null;
    scanResults = [];
    notifications.clear();
    _lastNotifiedStatus.clear();
    notifyListeners();
  }

  void startListening() {
    fetchLatestTraffic();
    _pollingTimer ??= Timer.periodic(
      const Duration(seconds: 2),
      (_) => fetchLatestTraffic(),
    );
  }

  Future<void> fetchLatestTraffic() async {
    try {
      result = await ApiService.latestTraffic();
      _recordNotification(result!);

      notifyListeners();
    } catch (e) {
      debugPrint(e.toString());
    }
  }

  Future<Map<String, dynamic>> scanNetwork(List<String> deviceNames) async {
    final response = await ApiService.scanNetwork(deviceNames);
    final allResults = List<Map<String, dynamic>>.from(
      response["devices"] ?? [],
    );
    final liveResults = allResults
        .where((item) => item["timestamp"] != null)
        .toList();
    final results = liveResults.isNotEmpty ? liveResults : allResults;
    scanResults = results;
    if (results.isNotEmpty) {
      final withData = results.where((item) => item["timestamp"] != null);
      if (withData.isNotEmpty) {
        final prioritized = withData.toList()
          ..sort((a, b) {
            final aAlert = a["status"] == "ALERT" ? 0 : 1;
            final bAlert = b["status"] == "ALERT" ? 0 : 1;
            return aAlert.compareTo(bAlert);
          });
        result = prioritized.first;
        _recordNotification(result!);
      }
    }
    notifyListeners();
    return response;
  }

  void _recordNotification(Map<String, dynamic> event) {
    if (!notificationsEnabled || event["timestamp"] == null) return;
    final timestamp = event["timestamp"] as String;
    if (notifications.any((item) => item["timestamp"] == timestamp)) return;

    notifications.insert(0, {
      "device": event["device"] ?? "IoT Device",
      "prediction": event["prediction"] ?? "Unknown",
      "status": event["status"] ?? "WAITING",
      "confidence": event["confidence"] ?? 0,
      "timestamp": timestamp,
    });
    final device = event["device"] as String? ?? "IoT Device";
    final status = event["status"] as String? ?? "WAITING";
    final previousStatus = _lastNotifiedStatus[device];
    if (previousStatus == null || previousStatus != status) {
      _lastNotifiedStatus[device] = status;
      NotificationService.showStatus(
        device: device,
        status: status,
        prediction: event["prediction"] as String? ?? "Unknown",
        confidence: event["confidence"] as num? ?? 0,
      );
    }
    if (notifications.length > 30) notifications.removeLast();
  }

  @override
  void dispose() {
    _pollingTimer?.cancel();
    super.dispose();
  }
}
