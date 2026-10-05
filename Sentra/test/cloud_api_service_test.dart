import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';
import 'package:nyxis_security/services/router_api_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  const mac = 'aa:bb:cc:dd:ee:ff';
  Map<String, dynamic> snapshot({bool stale = false}) => {
    'gateway_id': 'gateway-a',
    'snapshot_available': true,
    'observed_at': DateTime.now().toUtc().toIso8601String(),
    'received_at': DateTime.now().toUtc().toIso8601String(),
    'data_stale': stale,
    'recent_contact': !stale,
    'devices': [
      {
        'mac': mac,
        'name': 'Test phone',
        'status': 'SAFE',
        'blocked': false,
        'attack_probability': 0,
      },
    ],
    'alerts': [],
    'model': {'available': true, 'checkpoint_name': 'test.pth'},
  };

  void select({String role = 'owner'}) {
    CloudApiService.session = 'cloud-v1.test.signature';
    CloudApiService.select({
      'household_id': 'home-a',
      'gateway_id': 'gateway-a',
      'name': 'My gateway',
      'role': role,
    });
  }

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await RouterApiService.init(legacy: true);
    CloudApiService.configure(
      'https://staging.example',
      'test-private-staging-token-32-characters',
    );
  });

  tearDown(CloudApiService.disable);

  test(
    'staging tokens and cloud sessions are never saved to preferences',
    () async {
      final client = MockClient((request) async {
        expect(request.url.path, '/cloud/auth/login');
        expect(
          request.headers['X-Cloud-Staging-Token'],
          'test-private-staging-token-32-characters',
        );
        expect(request.headers.containsKey('X-Gateway-Token'), isFalse);
        expect(request.headers.containsKey('X-Gateway-Credential'), isFalse);
        expect(request.followRedirects, isFalse);
        return http.Response(
          jsonEncode({
            'email': 'owner@example.com',
            'name': 'Owner',
            'access_token': 'cloud-v1.test.signature',
          }),
          200,
        );
      });
      await http.runWithClient(() async {
        expect(
          (await RouterApiService.logIn(
            email: 'owner@example.com',
            password: 'password',
          ))['success'],
          isTrue,
        );
        expect(RouterApiService.hasSession, isFalse);
        select();
        expect(RouterApiService.hasSession, isTrue);
        expect((await SharedPreferences.getInstance()).getKeys(), isEmpty);
        await RouterApiService.init(legacy: true);
        expect(CloudApiService.enabled, isFalse);
        expect(RouterApiService.hasSession, isFalse);
      }, () => client);
    },
  );

  test(
    'households and nonrevoked gateways are explicitly selectable',
    () async {
      CloudApiService.session = 'cloud-v1.test.signature';
      await http.runWithClient(
        () async {
          final choices = await CloudApiService.gateways();
          expect(choices.length, 1);
          expect(choices.single['role'], 'member');
          CloudApiService.select(choices.single);
          expect(CloudApiService.gatewayId, 'gateway-a');
        },
        () => MockClient((request) async {
          if (request.url.path == '/cloud/households') {
            return http.Response(
              '{"households":[{"household_id":"home-a","role":"member"}]}',
              200,
            );
          }
          expect(request.url.path, '/cloud/households/home-a/gateways');
          return http.Response(
            '{"gateways":[{"gateway_id":"gateway-a","revoked_at":null},{"gateway_id":"revoked","revoked_at":"yesterday"}]}',
            200,
          );
        }),
      );
    },
  );

  test('existing devices and model methods use household-scoped snapshots', () async {
    select();
    await http.runWithClient(
      () async {
        expect((await RouterApiService.devices()).single['mac'], mac);
        expect(
          (await RouterApiService.federatedStatus())['cloud_model']['available'],
          isTrue,
        );
      },
      () => MockClient((request) async {
        expect(
          request.url.path,
          '/cloud/households/home-a/gateways/gateway-a/snapshot',
        );
        expect(
          request.headers['Authorization'],
          'Bearer cloud-v1.test.signature',
        );
        return http.Response(jsonEncode(snapshot()), 200);
      }),
    );
  });

  test('control waits for Pi acknowledgement; queued is not success', () async {
    select();
    String? commandId;
    var reads = 0;
    await http.runWithClient(
      () async {
        final result = await CloudApiService.control(
          mac,
          'block',
          pollInterval: Duration.zero,
        );
        expect(result['success'], isTrue);
        expect(reads, 3);
        expect(CloudApiService.commandUnconfirmed, isFalse);
      },
      () => MockClient((request) async {
        if (request.url.path.endsWith('/snapshot')) {
          return http.Response(jsonEncode(snapshot()), 200);
        }
        expect(
          request.url.path.startsWith(
            '/cloud/households/home-a/gateways/gateway-a/commands',
          ),
          isTrue,
        );
        if (request.method == 'POST') {
          final body = jsonDecode(request.body);
          expect(body['mac'], mac);
          expect(body['action'], 'block');
          commandId = body['command_id'] as String;
          expect(RegExp(r'^[a-f0-9-]{36}$').hasMatch(commandId!), isTrue);
          return http.Response(
            jsonEncode({
              ...body as Map<String, dynamic>,
              'id': commandId,
              'gateway_id': 'gateway-a',
              'status': 'queued',
            }),
            202,
          );
        }
        reads++;
        return http.Response(
          jsonEncode({
            'id': commandId,
            'gateway_id': 'gateway-a',
            'status': reads == 3
                ? 'succeeded'
                : reads == 2
                ? 'delivered'
                : 'queued',
            'result_code': reads == 3 ? 'applied' : null,
          }),
          200,
        );
      }),
    );
  });

  test(
    'member controls, stale data and unsupported features never send a command',
    () async {
      select(role: 'member');
      final requests = <http.Request>[];
      await http.runWithClient(
        () async {
          await expectLater(
            CloudApiService.control(mac, 'block'),
            throwsException,
          );
          expect(requests, isEmpty);
          select();
          await expectLater(
            CloudApiService.control(mac, 'unblock'),
            throwsException,
          );
          expect(requests.every((r) => r.method == 'GET'), isTrue);
          requests.clear();
          await expectLater(
            RouterApiService.startFederatedTraining(),
            throwsException,
          );
          await expectLater(
            RouterApiService.registerDevice(
              name: 'name',
              mac: mac,
              ipAddress: '',
            ),
            throwsException,
          );
          expect(requests, isEmpty);
        },
        () => MockClient((request) async {
          requests.add(request);
          return http.Response(jsonEncode(snapshot(stale: true)), 200);
        }),
      );
    },
  );

  test(
    'unknown outcome blocks blind retry and offers read-only status recovery',
    () async {
      select();
      var posts = 0;
      var completed = false;
      await http.runWithClient(
        () async {
          await expectLater(
            CloudApiService.control(mac, 'unblock'),
            throwsException,
          );
          expect(CloudApiService.commandUnconfirmed, isTrue);
          await expectLater(
            CloudApiService.control(mac, 'unblock'),
            throwsException,
          );
          expect(posts, 1);
          completed = true;
          expect(
            (await CloudApiService.commandStatus())['status'],
            'succeeded',
          );
          expect(CloudApiService.commandUnconfirmed, isFalse);
        },
        () => MockClient((request) async {
          if (request.url.path.endsWith('/snapshot')) {
            return http.Response(jsonEncode(snapshot()), 200);
          }
          if (request.method == 'POST') {
            posts++;
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            return http.Response(
              jsonEncode({
                ...body,
                'id': body['command_id'],
                'gateway_id': 'gateway-a',
                'status': 'queued',
              }),
              202,
            );
          }
          return http.Response(
            jsonEncode({
              'id': CloudApiService.lastCommandId,
              'gateway_id': 'gateway-a',
              'status': completed ? 'succeeded' : 'unknown',
              'result_code': completed ? 'applied' : null,
            }),
            200,
          );
        }),
      );
    },
  );

  test('old snapshot is discarded when session changes in flight', () async {
    select();
    final response = Completer<http.Response>();
    await http.runWithClient(() async {
      final pending = CloudApiService.snapshot();
      final check = expectLater(pending, throwsException);
      await Future<void>.delayed(Duration.zero);
      CloudApiService.clearSession();
      response.complete(http.Response(jsonEncode(snapshot()), 200));
      await check;
      expect(CloudApiService.lastSnapshot, isNull);
    }, () => MockClient((_) => response.future));
  });

  test('cloud validation rejects insecure destinations', () {
    for (final url in [
      'http://staging.example',
      'https://user:pass@staging.example',
      'https://staging.example/path',
    ]) {
      expect(
        () => CloudApiService.configure(
          url,
          'test-private-staging-token-32-characters',
        ),
        throwsFormatException,
      );
    }
  });
}
