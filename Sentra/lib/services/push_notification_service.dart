import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'cloud_api_service.dart';
import 'notification_service.dart';

@pragma('vm:entry-point')
Future<void> firebaseBackgroundMessage(RemoteMessage message) async {
  await Firebase.initializeApp();
  await PushNotificationService.recordDelivered(message.data);
}

class _PushLifecycleObserver extends WidgetsBindingObserver {
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(PushNotificationService.syncSafely());
    }
  }
}

class PushNotificationService {
  static final error = ValueNotifier<String?>(null);
  static bool _initialized = false;
  static String? _registeredSession;
  static String? _registeredToken;
  static String? _signedOutSession;
  static Future<void> _tail = Future<void>.value();
  static Timer? _retry;
  static bool get supported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  static Future<T> _serial<T>(Future<T> Function() action) async {
    final previous = _tail;
    final release = Completer<void>();
    _tail = release.future;
    await previous;
    try {
      return await action();
    } finally {
      release.complete();
    }
  }

  static Future<void> recordDelivered(Map<String, dynamic> data) async {
    final gateway = data['gateway_id'];
    final event = data['event_key'];
    if (gateway is! String || event is! String) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();
    final keys = prefs.getStringList('delivered_cloud_events') ?? [];
    final key = '$gateway:$event';
    if (!keys.contains(key)) keys.add(key);
    await prefs.setStringList(
      'delivered_cloud_events',
      keys.length > 200 ? keys.sublist(keys.length - 200) : keys,
    );
  }

  static Future<bool> wasDelivered(String gateway, String event) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();
    return (prefs.getStringList('delivered_cloud_events') ?? []).contains(
      '$gateway:$event',
    );
  }

  static Future<Map<String, dynamic>> _installation() async {
    const key = 'push_installation';
    final saved = await CloudApiService.storage.read(key: key);
    if (saved != null) {
      final value = jsonDecode(saved);
      if (value is! Map<String, dynamic> ||
          value['installation_id'] is! String ||
          value['secret'] is! String) {
        throw const FormatException('Invalid notification installation state.');
      }
      return value;
    }
    final random = Random.secure();
    String hex(int count) => List.generate(
      count,
      (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'),
    ).join();
    final id = hex(16);
    final value = <String, dynamic>{
      'installation_id':
          '${id.substring(0, 8)}-${id.substring(8, 12)}-'
          '${id.substring(12, 16)}-${id.substring(16, 20)}-${id.substring(20)}',
      'secret': hex(32),
    };
    await CloudApiService.storage.write(key: key, value: jsonEncode(value));
    return value;
  }

  static Future<void> _initialize() async {
    if (_initialized) return;
    await Firebase.initializeApp();
    FirebaseMessaging.onBackgroundMessage(firebaseBackgroundMessage);
    await NotificationService.initialize();
    await FirebaseMessaging.instance.setAutoInitEnabled(true);
    final initial = await FirebaseMessaging.instance.getInitialMessage();
    if (initial != null) await recordDelivered(initial.data);
    FirebaseMessaging.instance.onTokenRefresh.listen(
      (_) => syncSafely(),
      onError: (Object _) {
        error.value =
            'Background notification token refresh failed. Retry in Settings.';
      },
    );
    FirebaseMessaging.onMessageOpenedApp.listen((message) async {
      try {
        await recordDelivered(message.data);
      } on Exception {
        error.value =
            'Notification history could not be saved; an alert may repeat.';
      }
    });
    // Foreground events use the existing snapshot dispatcher, not a second alert.
    WidgetsBinding.instance.addObserver(_PushLifecycleObserver());
    _initialized = true;
  }

  static Future<void> syncSafely() async {
    try {
      await sync();
    } on Exception {
      _registrationFailed();
    } on StateError {
      _registrationFailed();
    }
  }

  static void _registrationFailed() {
    error.value = 'Background notifications are unavailable. Check connectivity and retry in Settings.';
    _retry ??= Timer(const Duration(seconds: 30), () {
      _retry = null;
      unawaited(syncSafely());
    });
  }

  static Future<void> sync({bool? enabled}) => _serial(() async {
    if (!supported || !CloudApiService.customer) return;
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool('push_revoke_pending') == true) await _revoke();
    final allowed = enabled ?? prefs.getBool('notificationsEnabled') ?? true;
    if (!allowed ||
        CloudApiService.session.isEmpty ||
        CloudApiService.session == _signedOutSession ||
        CloudApiService.savedAccount?['email_verified'] != true) {
      await _revoke();
      if (enabled != null) await prefs.setBool('notificationsEnabled', enabled);
      return;
    }
    final version = CloudApiService.generation;
    final session = CloudApiService.session;
    await _initialize();
    final permissions = await FirebaseMessaging.instance
        .getNotificationSettings();
    if (permissions.authorizationStatus != AuthorizationStatus.authorized) {
      throw StateError('Allow notifications in Android settings.');
    }
    final token = await FirebaseMessaging.instance.getToken();
    if (token == null) {
      throw StateError('Firebase did not issue a notification token.');
    }
    if (version != CloudApiService.generation ||
        session != CloudApiService.session) {
      return;
    }
    if (_registeredSession == session && _registeredToken == token) {
      error.value = null;
      if (enabled != null) await prefs.setBool('notificationsEnabled', enabled);
      return;
    }
    final installation = await _installation();
    // Persist before requesting, so uncertain network outcomes can be revoked.
    await prefs.setBool('push_registration_possible', true);
    await CloudApiService.request(
      'POST',
      '/cloud/push/register',
      body: {...installation, 'token': token},
    );
    if (version != CloudApiService.generation ||
        session != CloudApiService.session) {
      await _revoke();
      return;
    }
    _registeredSession = session;
    _registeredToken = token;
    if (enabled != null) await prefs.setBool('notificationsEnabled', enabled);
    error.value = null;
    _retry?.cancel();
    _retry = null;
  });

  static Future<void> _revoke() async {
    final prefs = await SharedPreferences.getInstance();
    _registeredSession = _registeredToken = null;
    if (prefs.getBool('push_registration_possible') != true) {
      error.value = null;
      return;
    }
    await prefs.setBool('push_revoke_pending', true);
    await CloudApiService.request(
      'POST',
      '/cloud/push/unregister',
      body: await _installation(),
    );
    await prefs.setBool('push_registration_possible', false);
    await prefs.setBool('push_revoke_pending', false);
    error.value = null;
  }

  static Future<void> revokeForLogout() async {
    _signedOutSession = CloudApiService.session;
    if (!supported || !CloudApiService.customer) return;
    try {
      await _serial(_revoke);
    } on Exception {
      error.value = 'Signed out, but background alert removal could not be confirmed. Reconnect and retry.';
      _retry ??= Timer(const Duration(seconds: 30), () {
        _retry = null;
        unawaited(syncSafely());
      });
    }
  }
}
