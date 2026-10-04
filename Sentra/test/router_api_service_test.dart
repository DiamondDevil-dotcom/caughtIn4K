import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:nyxis_security/services/router_api_service.dart';
import 'package:nyxis_security/providers/router_device_provider.dart';
import 'package:nyxis_security/providers/activity_provider.dart';

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await RouterApiService.init();
  });

  test('Render is the shared default', () {
    expect(RouterApiService.baseUrl, 'https://caughtin4k.onrender.com');
    expect(RouterApiService.hasSession, isFalse);
  });

  test('sign-in persists token and forwards it on device reads', () async {
    final client = MockClient((request) async {
      if (request.url.path == '/auth/login') {
        expect(jsonDecode(request.body)['email'], 'owner@example.com');
        return http.Response(
          jsonEncode({
            'success': true,
            'name': 'Owner',
            'email': 'owner@example.com',
            'access_token': 'test-session',
          }),
          200,
        );
      }
      expect(request.url.path, '/devices');
      expect(request.headers['Authorization'], 'Bearer test-session');
      return http.Response('{"devices": []}', 200);
    });
    await http.runWithClient(() async {
      await RouterApiService.logIn(
        email: 'owner@example.com',
        password: 'test',
      );
      expect(RouterApiService.hasSession, isTrue);
      expect(await RouterApiService.devices(), isEmpty);
      await RouterApiService.init();
      expect(RouterApiService.hasSession, isTrue);
      await RouterApiService.clearSession();
      expect(RouterApiService.hasSession, isFalse);
    }, () => client);
  });

  test('failed sign-in does not create a session', () async {
    await http.runWithClient(
      () async {
        final result = await RouterApiService.logIn(
          email: 'owner@example.com',
          password: 'wrong',
        );
        expect(result['success'], isFalse);
        expect(RouterApiService.hasSession, isFalse);
      },
      () => MockClient(
        (_) async =>
            http.Response('{"success": false, "error": "Wrong password"}', 200),
      ),
    );
  });

  test('training uses the shared gateway start alias', () async {
    await http.runWithClient(
      () async {
        expect(
          (await RouterApiService.startFederatedTraining())['success'],
          isTrue,
        );
      },
      () => MockClient((request) async {
        expect(request.url.host, 'caughtin4k.onrender.com');
        expect(request.url.path, '/federated/start');
        return http.Response('{"success": true}', 200);
      }),
    );
  });

  test(
    'upstream device failure is surfaced instead of empty success',
    () async {
      await http.runWithClient(
        () async {
          await expectLater(RouterApiService.devices(), throwsException);
        },
        () => MockClient(
          (_) async => http.Response('{"detail": "Pi offline"}', 502),
        ),
      );
    },
  );

  test('failed blocking response is not accepted', () async {
    await http.runWithClient(
      () async {
        await expectLater(
          RouterApiService.block('aa:bb:cc:dd:ee:ff'),
          throwsException,
        );
      },
      () => MockClient(
        (_) async => http.Response(
          '{"success": false, "detail": "Firewall unavailable"}',
          200,
        ),
      ),
    );
  });

  test(
    'invalid gateway URL is rejected and existing URL is preserved',
    () async {
      await expectLater(
        RouterApiService.setBaseUrl('not a url'),
        throwsFormatException,
      );
      await expectLater(
        RouterApiService.setBaseUrl('https://'),
        throwsFormatException,
      );
      expect(RouterApiService.baseUrl, 'https://caughtin4k.onrender.com');
    },
  );

  test('changing gateway clears the old signed-in session', () async {
    SharedPreferences.setMockInitialValues({
      'gateway_session_token': 'test-session',
    });
    await RouterApiService.init();
    final generation = RouterApiService.sessionGeneration;
    await RouterApiService.setBaseUrl('https://replacement.example/');
    expect(RouterApiService.baseUrl, 'https://replacement.example');
    expect(RouterApiService.hasSession, isFalse);
    expect(RouterApiService.sessionGeneration, greaterThan(generation));
  });

  test(
    'pending device and activity responses are discarded after sign-out',
    () async {
      SharedPreferences.setMockInitialValues({
        'gateway_session_token': 'test-session',
      });
      await RouterApiService.init();
      final devices = Completer<http.Response>();
      final events = Completer<http.Response>();
      final requests = <String>[];
      await http.runWithClient(
        () async {
          final router = RouterDeviceProvider();
          final activity = ActivityProvider();
          addTearDown(router.dispose);
          addTearDown(activity.dispose);
          router.startPolling();
          activity.startPolling();
          await Future<void>.delayed(Duration.zero);
          router.startPolling();
          activity.startPolling();
          expect(requests.where((path) => path == '/devices').length, 1);
          expect(requests.where((path) => path == '/events').length, 1);
          await RouterApiService.clearSession();
          devices.complete(
            http.Response('{"devices":[{"name":"Old gateway"}]}', 200),
          );
          events.complete(
            http.Response('{"events":[{"device":"Old gateway"}]}', 200),
          );
          await Future<void>.delayed(Duration.zero);
          expect(router.devices, isEmpty);
          expect(activity.events, isEmpty);
        },
        () => MockClient((request) async {
          requests.add(request.url.path);
          if (request.url.path == '/devices') return devices.future;
          if (request.url.path == '/events') return events.future;
          return http.Response('{}', 200);
        }),
      );
    },
  );
}
