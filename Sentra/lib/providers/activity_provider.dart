import 'dart:async';

import 'package:flutter/material.dart';

import '../services/router_api_service.dart';

/// Polls the router agent's persisted event history (SQLite) so Activity
/// shows real detections instead of static placeholder tiles.
class ActivityProvider extends ChangeNotifier {
  List<Map<String, dynamic>> events = [];
  String? lastError;
  Timer? _pollingTimer;
  bool _fetching = false;
  bool _disposed = false;

  void clearCachedData() {
    events = [];
    lastError = null;
    notifyListeners();
  }

  void startPolling() {
    _fetch();
    _pollingTimer ??= Timer.periodic(
      const Duration(seconds: 2),
      (_) => _fetch(),
    );
  }

  Future<void> _fetch() async {
    if (_disposed || _fetching || !RouterApiService.hasSession) return;
    _fetching = true;
    final requestedUrl = RouterApiService.baseUrl;
    final requestedSession = RouterApiService.sessionGeneration;
    try {
      final fetched = await RouterApiService.events();
      if (_disposed ||
          requestedUrl != RouterApiService.baseUrl ||
          requestedSession != RouterApiService.sessionGeneration) {
        return;
      }
      events = fetched;
      lastError = null;
    } catch (error) {
      if (_disposed ||
          requestedUrl != RouterApiService.baseUrl ||
          requestedSession != RouterApiService.sessionGeneration) {
        return;
      }
      lastError = error.toString();
    } finally {
      _fetching = false;
    }
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _pollingTimer?.cancel();
    super.dispose();
  }
}
