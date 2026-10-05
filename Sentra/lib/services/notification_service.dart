import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter/foundation.dart';

class NotificationService {
  static final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  static bool _initialized = false;
  static Future<void>? _initializing;

  static Future<void> initialize() async {
    if (kIsWeb ||
        defaultTargetPlatform != TargetPlatform.android ||
        _initialized) {
      return;
    }
    if (_initializing != null) return _initializing;
    final initialization = _initializeAndroid();
    _initializing = initialization;
    try {
      await initialization;
    } finally {
      _initializing = null;
    }
  }

  static Future<void> _initializeAndroid() async {
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    const settings = InitializationSettings(android: android);
    await _plugin.initialize(settings);

    final androidPlugin = _plugin
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >();
    if (androidPlugin == null) {
      throw StateError('Android notification plugin is unavailable.');
    }
    final permitted = await androidPlugin.requestNotificationsPermission();
    if (permitted != true) {
      throw StateError('Allow notifications in Android app settings.');
    }
    await androidPlugin.createNotificationChannel(
      const AndroidNotificationChannel(
        'caughtin4k_threats',
        'Threat alerts',
        description: 'Real-time caughtIn4K intrusion alerts',
        importance: Importance.max,
      ),
    );
    _initialized = true;
  }

  static Future<void> showThreat({
    required String device,
    required String attack,
    required num confidence,
    int? notificationId,
  }) async {
    await initialize();
    if (!_initialized) return;
    await _plugin.show(
      notificationId ??
          DateTime.now().millisecondsSinceEpoch.remainder(1 << 31),
      'Threat detected',
      '$device: $attack (${confidence.toStringAsFixed(1)}% confidence)',
      const NotificationDetails(
        android: AndroidNotificationDetails(
          'caughtin4k_threats',
          'Threat alerts',
          channelDescription: 'Real-time caughtIn4K intrusion alerts',
          importance: Importance.max,
          priority: Priority.high,
          playSound: true,
          enableVibration: true,
        ),
      ),
    );
  }

  static Future<void> showStatus({
    required String device,
    required String status,
    required String prediction,
    required num confidence,
    int? notificationId,
  }) async {
    await initialize();
    if (!_initialized) return;

    final isAlert = const {
      'WARNING',
      'ATTACK',
      'ALERT',
      'BLOCKED',
    }.contains(status);
    final title = switch (status) {
      "ALERT" => "Threat detected",
      "BLOCKED" => "Device blocked",
      "WARNING" => "Suspicious activity rising",
      "SAFE" => "Network protected",
      _ => "Traffic status updated",
    };
    await _plugin.show(
      notificationId ??
          DateTime.now().millisecondsSinceEpoch.remainder(1 << 31),
      title,
      '$device: $prediction (${confidence.toStringAsFixed(1)}% confidence)',
      NotificationDetails(
        android: AndroidNotificationDetails(
          'caughtin4k_threats',
          'Threat alerts',
          channelDescription: 'Real-time caughtIn4K intrusion alerts',
          importance: isAlert ? Importance.max : Importance.defaultImportance,
          priority: isAlert ? Priority.high : Priority.defaultPriority,
          playSound: true,
          enableVibration: isAlert,
        ),
      ),
    );
  }
}
