import 'dart:async';
import 'package:flutter/material.dart';

import '../services/notification_service.dart';
import '../services/router_api_service.dart';

/// Polls the Pi's router-mode IDS agent for live per-device status
/// (SAFE / WARNING / ALERT / BLOCKED) and exposes block/unblock actions.
/// Fires a notification the moment any device's status actually changes,
/// so alerts stay in sync with the real detection pipeline in real time.
class RouterDeviceProvider extends ChangeNotifier {
  List<Map<String, dynamic>> devices = [];
  Map<String, dynamic>? federatedStatus;
  String? federatedStatusError;
  bool federatedTrainingStarting = false;
  String? federatedTrainingMessage;
  final List<Map<String, dynamic>> notifications = [];
  String? lastError;
  Timer? _pollingTimer;
  Timer? _federatedPollingTimer;
  final Map<String, String> _lastStatusByMac = {};

  void startPolling() {
    _fetch();
    _fetchFederatedStatus();
    _pollingTimer ??= Timer.periodic(
      const Duration(seconds: 2),
      (_) => _fetch(),
    );
    _federatedPollingTimer ??= Timer.periodic(
      const Duration(seconds: 15),
      (_) => _fetchFederatedStatus(),
    );
  }

  Future<void> _fetchFederatedStatus() async {
    try {
      federatedStatus = await RouterApiService.federatedStatus();
      federatedStatusError = null;
      final training = federatedStatus?['training'];
      if (training is Map<String, dynamic> && training['state'] == 'running') {
        federatedTrainingMessage =
            'Federated training is running: round ${training['current_round'] ?? 0}/${training['total_rounds'] ?? 10}.';
      } else if (training is Map<String, dynamic> &&
          training['state'] == 'completed') {
        federatedTrainingMessage = 'Federated training completed.';
      }
    } catch (error) {
      federatedStatusError = error.toString();
    }
    notifyListeners();
  }

  Future<void> startFederatedTraining() async {
    if (federatedTrainingStarting) return;
    federatedTrainingStarting = true;
    federatedTrainingMessage = null;
    notifyListeners();
    try {
      final result = await RouterApiService.startFederatedTraining();
      federatedTrainingMessage = result["message"] as String? ?? "Federated training started.";
      await _fetchFederatedStatus();
    } catch (error) {
      federatedTrainingMessage = error
          .toString()
          .replaceFirst(RegExp(r'^Exception:\s*'), '');
    } finally {
      federatedTrainingStarting = false;
      notifyListeners();
    }
  }

  Future<void> _fetch() async {
    try {
      final fetched = await RouterApiService.devices();
      _notifyOnChanges(fetched);
      devices = fetched;
      lastError = null;
    } catch (error) {
      lastError = error.toString();
    }
    notifyListeners();
  }

  void _notifyOnChanges(List<Map<String, dynamic>> fetched) {
    for (final device in fetched) {
      final mac = device['mac'] as String?;
      final status = device['status'] as String?;
      if (mac == null || status == null) continue;

      final previous = _lastStatusByMac[mac];
      _lastStatusByMac[mac] = status;
      if (previous == status) continue;

      notifications.insert(0, {
        'device': device['name'] as String? ?? mac,
        'prediction': device['prediction'] as String? ?? status,
        'status': status,
        'confidence': device['attack_probability'] as num? ?? 0,
        'timestamp': DateTime.now().toIso8601String(),
      });
      if (notifications.length > 30) notifications.removeLast();

      NotificationService.showStatus(
        device: device['name'] as String? ?? mac,
        status: status,
        prediction: device['prediction'] as String? ?? status,
        confidence: device['attack_probability'] as num? ?? 0,
      );
    }
  }

  Future<void> block(String mac) async {
    await RouterApiService.block(mac);
    await _fetch();
  }

  Future<void> unblock(String mac) async {
    await RouterApiService.unblock(mac);
    await _fetch();
  }

  Future<void> registerDevice({
    required String name,
    required String mac,
    required String ipAddress,
  }) async {
    await RouterApiService.registerDevice(
      name: name,
      mac: mac,
      ipAddress: ipAddress,
    );
    await _fetch();
  }

  Future<void> deleteDevice(String mac) async {
    await RouterApiService.deleteDevice(mac);
    devices = devices.where((device) => device['mac'] != mac).toList();
    _lastStatusByMac.remove(mac);
    notifyListeners();
  }

  @override
  void dispose() {
    _pollingTimer?.cancel();
    _federatedPollingTimer?.cancel();
    super.dispose();
  }
}
