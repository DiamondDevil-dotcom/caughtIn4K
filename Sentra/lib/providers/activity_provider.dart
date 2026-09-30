import 'dart:async';
import 'package:flutter/material.dart';

import '../services/router_api_service.dart';

/// Polls the router agent's persisted event history (SQLite) so Activity
/// shows real detections instead of static placeholder tiles.
class ActivityProvider extends ChangeNotifier {
  List<Map<String, dynamic>> events = [];
  String? lastError;
  Timer? _pollingTimer;

  void startPolling() {
    _fetch();
    _pollingTimer ??= Timer.periodic(
      const Duration(seconds: 4),
      (_) => _fetch(),
    );
  }

  Future<void> _fetch() async {
    try {
      events = await RouterApiService.events();
      lastError = null;
    } catch (error) {
      lastError = error.toString();
    }
    notifyListeners();
  }

  @override
  void dispose() {
    _pollingTimer?.cancel();
    super.dispose();
  }
}
