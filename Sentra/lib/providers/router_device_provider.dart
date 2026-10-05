import 'dart:async';

import 'package:flutter/material.dart';

import '../services/notification_service.dart';
import '../services/router_api_service.dart';
import '../services/cloud_api_service.dart';

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
  bool _fetchingDevices = false;
  bool _fetchingFederatedStatus = false;
  bool _disposed = false;
  DateTime? _lastCloudFetch;
  String? pendingControlMac;
  final Map<String, bool> confirmedControls = {};
  final Map<String, DateTime> _confirmedAt = {};
  final Map<String, DateTime> _removedAt = {};

  List<Map<String, dynamic>> get displayedDevices => devices
      .where((device) => !_removedAt.containsKey(device['mac']))
      .map((device) {
        final override = confirmedControls[device['mac']];
        if (override == null) return device;
        return {
          ...device,
          'blocked': override,
          'status': override
              ? 'BLOCKED'
              : device['status'] == 'BLOCKED'
              ? 'SAFE'
              : device['status'],
        };
      })
      .toList();

  void recordConfirmedControl(
    String mac,
    bool blocked, {
    DateTime? completedAt,
  }) {
    confirmedControls[mac] = blocked;
    _confirmedAt[mac] = completedAt ?? DateTime.now();
    if (!_disposed) notifyListeners();
  }

  void recordConfirmedRemoval(String mac, {DateTime? completedAt}) {
    _removedAt[mac] = completedAt ?? DateTime.now();
    confirmedControls.remove(mac);
    _confirmedAt.remove(mac);
    _lastStatusByMac.remove(mac);
    if (!_disposed) notifyListeners();
  }

  Future<Map<String, dynamic>> checkCommandStatus() async {
    final version = RouterApiService.sessionGeneration;
    final mac = CloudApiService.lastCommandMac;
    final action = CloudApiService.lastCommandAction;
    final result = await CloudApiService.commandStatus();
    if (version != RouterApiService.sessionGeneration || _disposed) {
      throw Exception(
        'Home changed. Check command status in the original home.',
      );
    }
    if (result['status'] == 'succeeded' && mac != null) {
      final completed = DateTime.tryParse(
        result['completed_at'] as String? ?? '',
      );
      if (action == 'remove') {
        recordConfirmedRemoval(mac, completedAt: completed);
      } else if (action == 'block' || action == 'unblock') {
        recordConfirmedControl(mac, action == 'block', completedAt: completed);
      }
    }
    await refresh();
    return result;
  }

  bool get cloudDataStale {
    final snapshot = CloudApiService.lastSnapshot;
    final observed = DateTime.tryParse(
      snapshot?['observed_at'] as String? ?? '',
    );
    return lastError != null ||
        snapshot == null ||
        snapshot['data_stale'] == true ||
        snapshot['recent_contact'] != true ||
        observed == null ||
        DateTime.now().difference(observed).inSeconds > 90;
  }

  String get cloudFreshness => cloudDataStale
      ? 'Your home is offline or updates are delayed. Showing the last update.'
      : 'Your home is connected. Updates may take up to 30 seconds.';

  void clearCachedData() {
    devices = [];
    federatedStatus = null;
    federatedStatusError = null;
    federatedTrainingMessage = null;
    notifications.clear();
    _lastStatusByMac.clear();
    lastError = null;
    confirmedControls.clear();
    _confirmedAt.clear();
    _removedAt.clear();
    _lastCloudFetch = null;
    notifyListeners();
  }

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

  Future<void> refresh() async {
    _lastCloudFetch = null;
    await _fetch();
  }

  Future<void> _fetchFederatedStatus() async {
    if (_disposed ||
        RouterApiService.cloudMode ||
        _fetchingFederatedStatus ||
        !RouterApiService.hasSession) {
      return;
    }
    _fetchingFederatedStatus = true;
    final requestedUrl = RouterApiService.baseUrl;
    final requestedSession = RouterApiService.sessionGeneration;
    try {
      final fetched = await RouterApiService.federatedStatus();
      if (_disposed ||
          requestedUrl != RouterApiService.baseUrl ||
          requestedSession != RouterApiService.sessionGeneration) {
        return;
      }
      federatedStatus = fetched;
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
      if (_disposed ||
          requestedUrl != RouterApiService.baseUrl ||
          requestedSession != RouterApiService.sessionGeneration) {
        return;
      }
      federatedStatusError = error.toString();
    } finally {
      _fetchingFederatedStatus = false;
    }
    if (!_disposed) notifyListeners();
  }

  Future<void> startFederatedTraining() async {
    if (federatedTrainingStarting) return;
    federatedTrainingStarting = true;
    federatedTrainingMessage = null;
    notifyListeners();
    try {
      final result = await RouterApiService.startFederatedTraining();
      federatedTrainingMessage =
          result["message"] as String? ?? "Federated training started.";
      await _fetchFederatedStatus();
    } catch (error) {
      federatedTrainingMessage = error.toString().replaceFirst(
        RegExp(r'^Exception:\s*'),
        '',
      );
    } finally {
      federatedTrainingStarting = false;
      notifyListeners();
    }
  }

  Future<void> _fetch() async {
    if (_disposed || _fetchingDevices || !RouterApiService.hasSession) return;
    if (RouterApiService.cloudMode &&
        _lastCloudFetch != null &&
        DateTime.now().difference(_lastCloudFetch!).inSeconds < 15) {
      notifyListeners();
      return;
    }
    _lastCloudFetch = RouterApiService.cloudMode ? DateTime.now() : null;
    _fetchingDevices = true;
    final requestedUrl = RouterApiService.baseUrl;
    final requestedSession = RouterApiService.sessionGeneration;
    try {
      final fetched = await RouterApiService.devices();
      if (_disposed ||
          requestedUrl != RouterApiService.baseUrl ||
          requestedSession != RouterApiService.sessionGeneration) {
        return;
      }
      if (!RouterApiService.cloudMode) _notifyOnChanges(fetched);
      if (RouterApiService.cloudMode) {
        federatedStatus = {
          'cloud_model': CloudApiService.lastSnapshot?['model'],
        };
        federatedStatusError = null;
        final observed = DateTime.tryParse(
          CloudApiService.lastSnapshot?['observed_at'] as String? ?? '',
        );
        confirmedControls.removeWhere((mac, blocked) {
          final completed = _confirmedAt[mac];
          if (observed != null &&
              completed != null &&
              !observed.isBefore(completed)) {
            _confirmedAt.remove(mac);
            return true;
          }
          return false;
        });
        _removedAt.removeWhere(
          (mac, completed) => observed != null && !observed.isBefore(completed),
        );
      }
      devices = fetched;
      lastError = null;
    } catch (error) {
      if (_disposed ||
          requestedUrl != RouterApiService.baseUrl ||
          requestedSession != RouterApiService.sessionGeneration) {
        return;
      }
      lastError = error.toString();
    } finally {
      _fetchingDevices = false;
    }
    if (!_disposed) notifyListeners();
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
    await _control(mac, true);
  }

  Future<void> unblock(String mac) async {
    await _control(mac, false);
  }

  Future<void> _control(String mac, bool blocked) async {
    if (pendingControlMac != null) {
      throw Exception('A network command is already pending.');
    }
    pendingControlMac = mac;
    final version = RouterApiService.sessionGeneration;
    notifyListeners();
    try {
      final result = blocked
          ? await RouterApiService.block(mac)
          : await RouterApiService.unblock(mac);
      if (version != RouterApiService.sessionGeneration) {
        throw Exception(
          'Session changed; reconcile command status before retrying.',
        );
      }
      if (RouterApiService.cloudMode) {
        recordConfirmedControl(
          mac,
          blocked,
          completedAt: DateTime.tryParse(
            result['completed_at'] as String? ?? '',
          ),
        );
      }
      _lastCloudFetch = null;
      await _fetch();
    } finally {
      pendingControlMac = null;
      if (!_disposed) notifyListeners();
    }
  }

  Future<void> registerDevice({
    required String name,
    required String mac,
    required String ipAddress,
  }) async {
    if (pendingControlMac != null) {
      throw Exception('A device command is already pending.');
    }
    pendingControlMac = mac;
    final version = RouterApiService.sessionGeneration;
    notifyListeners();
    try {
      await RouterApiService.registerDevice(
        name: name,
        mac: mac,
        ipAddress: ipAddress,
      );
      if (version != RouterApiService.sessionGeneration) {
        throw Exception('Home changed. Check command status.');
      }
      _lastCloudFetch = null;
      await _fetch();
    } finally {
      pendingControlMac = null;
      if (!_disposed) notifyListeners();
    }
  }

  Future<void> deleteDevice(String mac) async {
    if (pendingControlMac != null) {
      throw Exception('A device command is already pending.');
    }
    pendingControlMac = mac;
    final version = RouterApiService.sessionGeneration;
    notifyListeners();
    try {
      final result = await RouterApiService.deleteDevice(mac);
      if (version != RouterApiService.sessionGeneration) {
        throw Exception('Home changed. Check command status.');
      }
      if (RouterApiService.cloudMode) {
        recordConfirmedRemoval(
          mac,
          completedAt: DateTime.tryParse(
            result['completed_at'] as String? ?? '',
          ),
        );
      }
      confirmedControls.remove(mac);
      _confirmedAt.remove(mac);
      devices = devices.where((device) => device['mac'] != mac).toList();
      _lastStatusByMac.remove(mac);
    } finally {
      pendingControlMac = null;
      if (!_disposed) notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _pollingTimer?.cancel();
    _federatedPollingTimer?.cancel();
    super.dispose();
  }
}
