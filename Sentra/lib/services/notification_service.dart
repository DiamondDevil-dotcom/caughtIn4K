import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  static final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  static bool _initialized = false;

  static Future<void> initialize() async {
    if (_initialized) return;

    try {
      const android = AndroidInitializationSettings('@mipmap/ic_launcher');
      const settings = InitializationSettings(android: android);
      await _plugin.initialize(settings);

      final androidPlugin = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      await androidPlugin?.requestNotificationsPermission();
      await androidPlugin?.createNotificationChannel(
        const AndroidNotificationChannel(
          'caughtin4k_threats',
          'Threat alerts',
          description: 'Real-time caughtIn4K intrusion alerts',
          importance: Importance.max,
        ),
      );
      _initialized = true;
    } catch (_) {
      // Desktop and widget-test platforms do not expose Android notifications.
    }
  }

  static Future<void> showThreat({
    required String device,
    required String attack,
    required num confidence,
  }) async {
    await initialize();
    if (!_initialized) return;
    await _plugin.show(
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
  }) async {
    await initialize();
    if (!_initialized) return;

    final isAlert = status == "ALERT" || status == "BLOCKED";
    final title = switch (status) {
      "ALERT" => "Threat detected",
      "BLOCKED" => "Device blocked",
      "WARNING" => "Suspicious activity rising",
      "SAFE" => "Network protected",
      _ => "Traffic status updated",
    };
    await _plugin.show(
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