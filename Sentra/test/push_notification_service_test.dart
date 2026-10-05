import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:nyxis_security/services/push_notification_service.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
    CloudApiService.disable();
  });

  test(
    'disable revokes with installation credential even after session expiry',
    () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      CloudApiService.customer = true;
      CloudApiService.origin = 'https://customer.example';
      SharedPreferences.setMockInitialValues({
        'push_registration_possible': true,
        'notificationsEnabled': true,
      });
      final installation = {
        'installation_id': '00112233-4455-6677-8899-aabbccddeeff',
        'secret': 'a' * 64,
      };
      FlutterSecureStorage.setMockInitialValues({
        'push_installation': jsonEncode(installation),
      });
      var removals = 0;
      await http.runWithClient(
        () async {
          await PushNotificationService.sync(enabled: false);
          await PushNotificationService.sync();
        },
        () => MockClient((request) async {
          removals++;
          expect(request.url.path, '/cloud/push/unregister');
          expect(request.headers.containsKey('Authorization'), isFalse);
          expect(jsonDecode(request.body), installation);
          return http.Response('{"success":true}', 200);
        }),
      );
      final prefs = await SharedPreferences.getInstance();
      expect(removals, 1);
      expect(prefs.getBool('notificationsEnabled'), isFalse);
      expect(prefs.getBool('push_revoke_pending'), isFalse);
      expect(prefs.getBool('push_registration_possible'), isFalse);
    },
  );

  test('uncertain disable is reported and persisted for retry, not treated as success', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    CloudApiService.customer = true;
    CloudApiService.origin = 'https://customer.example';
    SharedPreferences.setMockInitialValues({
      'push_registration_possible': true,
      'notificationsEnabled': true,
    });
    FlutterSecureStorage.setMockInitialValues({
      'push_installation': jsonEncode({
        'installation_id': '00112233-4455-6677-8899-aabbccddeeff',
        'secret': 'a' * 64,
      }),
    });
    await http.runWithClient(() async {
      await expectLater(
        PushNotificationService.sync(enabled: false),
        throwsA(isA<CloudRequestException>()),
      );
    }, () => MockClient((_) async => http.Response('{}', 503)));
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool('push_revoke_pending'), isTrue);
    expect(prefs.getBool('push_registration_possible'), isTrue);
    expect(prefs.getBool('notificationsEnabled'), isTrue);
    await http.runWithClient(
      () => PushNotificationService.sync(enabled: false),
      () => MockClient((_) async => http.Response('{"success":true}', 200)),
    );
    expect(prefs.getBool('push_revoke_pending'), isFalse);
  });

  test(
    'delivery history deduplicates by gateway and event, not event ID alone',
    () async {
      await PushNotificationService.recordDelivered({
        'gateway_id': 'home-a',
        'event_key': '42:123',
      });
      await PushNotificationService.recordDelivered({
        'gateway_id': 'home-a',
        'event_key': '42:123',
      });
      expect(
        await PushNotificationService.wasDelivered('home-a', '42:123'),
        isTrue,
      );
      expect(
        await PushNotificationService.wasDelivered('home-b', '42:123'),
        isFalse,
      );
      expect(
        await PushNotificationService.wasDelivered('home-a', '42:124'),
        isFalse,
      );
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getStringList('delivered_cloud_events'), hasLength(1));
    },
  );

  test('delivery history is bounded and ignores unrelated payloads', () async {
    await PushNotificationService.recordDelivered({'message': 'unrelated'});
    for (var i = 0; i < 205; i++) {
      await PushNotificationService.recordDelivered({
        'gateway_id': 'home-a',
        'event_key': '$i:123',
      });
    }
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getStringList('delivered_cloud_events'), hasLength(200));
    expect(
      await PushNotificationService.wasDelivered('home-a', '0:123'),
      isFalse,
    );
    expect(
      await PushNotificationService.wasDelivered('home-a', '204:123'),
      isTrue,
    );
  });
}
