import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';
import 'package:nyxis_security/services/router_api_service.dart';
import 'package:nyxis_security/providers/router_device_provider.dart';
import 'package:nyxis_security/providers/activity_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
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
    'setup QR email errors explain invalid labels and delivery failures',
    () async {
      for (final entry in {
        400: 'invalid, expired, or already paired',
        403: 'Verify your account email',
        503: 'could not be sent',
        429: 'Too many requests',
      }.entries) {
        await http.runWithClient(
          () async => expectLater(
            CloudApiService.request(
              'POST',
              '/cloud/gateways/email-setup-qr',
              body: {'gateway_id': 'gateway', 'pairing_code': 'test'},
            ),
            throwsA(
              predicate(
                (error) =>
                    error is CloudRequestException &&
                    error.status == entry.key &&
                    error.toString().contains(entry.value) &&
                    !error.toString().contains('private database diagnostic'),
              ),
            ),
          ),
          () => MockClient(
            (_) async => http.Response(
              '{"detail":"private database diagnostic"}',
              entry.key,
            ),
          ),
        );
      }
    },
  );

  test('signup validation reports the actual safe account error', () async {
    for (final message in [
      'Enter a valid email address.',
      'Use a password between 8 and 1024 characters.',
      'Use a name between 1 and 200 characters.',
    ]) {
      await http.runWithClient(
        () async {
          await expectLater(
            CloudApiService.signup('Test', 'test@example.invalid', 'password'),
            throwsA(
              predicate(
                (error) =>
                    error is CloudRequestException &&
                    error.status == 400 &&
                    error.toString().contains(message) &&
                    !error.toString().contains('command status'),
              ),
            ),
          );
        },
        () => MockClient(
          (_) async => http.Response(jsonEncode({'detail': message}), 400),
        ),
      );
    }
  });

  test('signup does not expose unexpected server response details', () async {
    for (final body in [
      '{"detail":"private database diagnostic"}',
      '<html>private database diagnostic</html>',
    ]) {
      await http.runWithClient(() async {
        await expectLater(
          CloudApiService.signup('Test', 'test@example.invalid', 'password'),
          throwsA(
            predicate(
              (error) =>
                  error.toString().contains('Check your name, email') &&
                  !error.toString().contains('private database diagnostic') &&
                  !error.toString().contains('command status'),
            ),
          ),
        );
      }, () => MockClient((_) async => http.Response(body, 400)));
    }
  });

  test(
    'signup conflict explains existing email instead of network commands',
    () async {
      await http.runWithClient(
        () async {
          await expectLater(
            CloudApiService.signup(
              'Test',
              'second@example.invalid',
              'test-password',
            ),
            throwsA(
              predicate(
                (error) =>
                    error.toString().contains('email already exists') &&
                    !error.toString().contains('command status'),
              ),
            ),
          );
        },
        () => MockClient(
          (request) async => http.Response(
            '{"detail":"An account with this email already exists."}',
            409,
          ),
        ),
      );
    },
  );

  test(
    'Activity refreshes events every two seconds without a 15-second gate',
    () async {
      select();
      final activity = ActivityProvider();
      var reads = 0;
      try {
        await http.runWithClient(
          () async {
            activity.startPolling();
            await Future<void>.delayed(const Duration(milliseconds: 2300));
            expect(reads, 2);
            expect(activity.events.single['status'], 'WARNING');
          },
          () => MockClient((request) async {
            reads++;
            return http.Response(
              jsonEncode({
                ...snapshot(),
                'alerts': [
                  {
                    'event_id': reads,
                    'mac': mac,
                    'status': 'WARNING',
                    'attack_probability': 90,
                    'timestamp': DateTime.now().toUtc().toIso8601String(),
                  },
                ],
              }),
              200,
            );
          }),
        );
      } finally {
        activity.dispose();
      }
    },
  );

  test('cloud warning and block events notify once per event across parallel devices', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    AndroidFlutterLocalNotificationsPlugin.registerWith();
    select();
    const channel = MethodChannel('dexterous.com/flutter/local_notifications');
    final delivered = <Map<dynamic, dynamic>>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          if (call.method == 'show') delivered.add(call.arguments as Map);
          return true;
        });
    final router = RouterDeviceProvider();
    final data = snapshot();
    final timestamp = DateTime.now().toUtc().toIso8601String();
    (data['devices'] as List).add({
      'mac': '11:22:33:44:55:66',
      'name': 'Second phone',
      'status': 'SAFE',
      'blocked': false,
    });
    data['alerts'] = [
      {
        'event_id': 1,
        'mac': mac,
        'status': 'WARNING',
        'attack_probability': 90,
        'timestamp': timestamp,
      },
      {
        'event_id': 2,
        'mac': mac,
        'status': 'BLOCKED',
        'attack_probability': 95,
        'timestamp': timestamp,
      },
      {
        'event_id': 3,
        'mac': '11:22:33:44:55:66',
        'status': 'WARNING',
        'attack_probability': 89,
        'timestamp': timestamp,
      },
    ];
    try {
      await http.runWithClient(
        () async {
          await router.refresh();
          await router.refresh();
          expect(router.lastError, isNull);
          expect(router.notificationError, isNull);
          expect(delivered.length, 3);
          expect(delivered.map((item) => item['id']).toSet().length, 3);
          expect(router.notifications.length, 3);
          expect(router.notificationError, isNull);
          router.clearCachedData();
          SharedPreferences.setMockInitialValues({
            'notificationsEnabled': false,
          });
          await router.refresh();
          expect(delivered.length, 3);
          expect(router.notifications, isEmpty);
        },
        () =>
            MockClient((request) async => http.Response(jsonEncode(data), 200)),
      );
    } finally {
      debugDefaultTargetPlatformOverride = null;
      router.dispose();
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null);
    }
  });

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
    'training targets the gateway and waits for real startup acknowledgement',
    () async {
      select();
      String? id;
      var reads = 0;
      await http.runWithClient(
        () async {
          final result = await CloudApiService.control(
            null,
            'train',
            pollInterval: Duration.zero,
          );
          expect(result['success'], isTrue);
          expect(
            result['message'],
            contains('Completion is reported separately'),
          );
          expect(CloudApiService.commandUnconfirmed, isFalse);
          expect(reads, 2);
        },
        () => MockClient((request) async {
          if (request.url.path.endsWith('/snapshot')) {
            return http.Response(
              jsonEncode({
                ...snapshot(),
                'training_available': true,
                'model': {
                  'available': true,
                  'federated': {
                    'observed_at': DateTime.now().toUtc().toIso8601String(),
                    'status': 'pretrained',
                    'training': {
                      'state': 'idle',
                      'current_round': 0,
                      'total_rounds': 10,
                    },
                  },
                },
              }),
              200,
            );
          }
          if (request.method == 'POST') {
            final body = jsonDecode(request.body) as Map;
            expect(body['action'], 'train');
            expect(body['mac'], isNull);
            expect(body.containsKey('server_address'), isFalse);
            id = body['command_id'] as String;
            return http.Response(
              jsonEncode({
                'id': id,
                'gateway_id': 'gateway-a',
                'mac': null,
                'action': 'train',
                'status': 'queued',
              }),
              202,
            );
          }
          reads++;
          return http.Response(
            jsonEncode({
              'id': id,
              'gateway_id': 'gateway-a',
              'status': reads == 1 ? 'delivered' : 'succeeded',
              'result_code': reads == 1 ? null : 'applied',
            }),
            200,
          );
        }),
      );
    },
  );

  test(
    'training cannot bypass role rollout freshness or running checks',
    () async {
      for (final state in [
        'running',
        'unavailable',
        'stale',
        'rollout',
        'member',
      ]) {
        select(role: state == 'member' ? 'member' : 'owner');
        var posts = 0;
        await http.runWithClient(
          () async {
            await expectLater(
              CloudApiService.control(null, 'train'),
              throwsException,
            );
            expect(posts, 0);
          },
          () => MockClient((request) async {
            if (request.method == 'POST') posts++;
            return http.Response(
              jsonEncode({
                ...snapshot(),
                'training_available': state != 'rollout',
                'model': {
                  'available': true,
                  'federated': {
                    'observed_at': DateTime.now()
                        .subtract(Duration(seconds: state == 'stale' ? 31 : 0))
                        .toUtc()
                        .toIso8601String(),
                    'status': 'pretrained',
                    'training': {
                      'state': {'running', 'unavailable'}.contains(state)
                          ? state
                          : 'idle',
                      'current_round': 0,
                      'total_rounds': 10,
                    },
                  },
                },
              }),
              200,
            );
          }),
        );
      }
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

  test(
    'two-second polling refreshes multiple devices in one request',
    () async {
      select();
      var requests = 0;
      final router = RouterDeviceProvider();
      try {
        await http.runWithClient(
          () async {
            router.startPolling();
            await Future<void>.delayed(const Duration(milliseconds: 2300));
            expect(requests, 2);
            expect(router.devices.length, 2);
          },
          () => MockClient((request) async {
            expect(request.url.path.endsWith('/snapshot'), isTrue);
            requests++;
            final data = snapshot();
            (data['devices'] as List).add({
              'mac': '11:22:33:44:55:66',
              'name': 'Second phone',
              'status': 'WARNING',
              'blocked': false,
              'attack_probability': 90,
            });
            return http.Response(jsonEncode(data), 200);
          }),
        );
      } finally {
        router.dispose();
      }
    },
  );

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
    'register and remove are bounded commands, not direct router requests',
    () async {
      for (final action in ['register', 'remove']) {
        select();
        Map<String, dynamic>? command;
        var reads = 0;
        await http.runWithClient(
          () async {
            final result = await CloudApiService.control(
              action == 'register' ? '11:22:33:44:55:66' : mac,
              action,
              deviceName: action == 'register' ? 'Sensor' : null,
              ipAddress: action == 'register' ? '' : null,
              pollInterval: Duration.zero,
            );
            expect(result['success'], isTrue);
            expect(reads, 2);
            expect(CloudApiService.commandUnconfirmed, isFalse);
          },
          () => MockClient((request) async {
            if (request.url.path.endsWith('/snapshot')) {
              return http.Response(
                jsonEncode({
                  ...snapshot(),
                  'device_management_available': true,
                }),
                200,
              );
            }
            expect(
              request.url.path,
              contains('/cloud/households/home-a/gateways/gateway-a/commands'),
            );
            if (request.method == 'POST') {
              command = jsonDecode(request.body) as Map<String, dynamic>;
              expect(command!['action'], action);
              if (action == 'register') {
                expect(command!['device_name'], 'Sensor');
                expect(command!['ip_address'], '');
              } else {
                expect(command!.containsKey('device_name'), isFalse);
              }
              return http.Response(
                jsonEncode({
                  ...command!,
                  'id': command!['command_id'],
                  'gateway_id': 'gateway-a',
                }),
                202,
              );
            }
            reads++;
            return http.Response(
              jsonEncode({
                ...command!,
                'id': command!['command_id'],
                'gateway_id': 'gateway-a',
                'status': reads == 1 ? 'delivered' : 'succeeded',
                'result_code': reads == 2 ? 'applied' : null,
                'completed_at': DateTime.now().toUtc().toIso8601String(),
              }),
              200,
            );
          }),
        );
      }
    },
  );

  test(
    'recovering a succeeded remove never restores the old device snapshot',
    () async {
      select();
      CloudApiService.lastCommandId = 'command-test';
      CloudApiService.lastCommandMac = mac;
      CloudApiService.lastCommandAction = 'remove';
      CloudApiService.commandUnconfirmed = true;
      final old = snapshot();
      final completed = DateTime.parse(old['observed_at'] as String)
          .add(const Duration(seconds: 1));
      final router = RouterDeviceProvider();
      try {
        await http.runWithClient(
          () async {
            final result = await router.checkCommandStatus();
            expect(result['status'], 'succeeded');
            expect(router.devices.length, 1);
            expect(router.displayedDevices, isEmpty);
            expect(router.confirmedControls, isEmpty);
            expect(CloudApiService.commandUnconfirmed, isFalse);
          },
          () => MockClient((request) async {
            expect(request.method, 'GET');
            return http.Response(
              jsonEncode(
                request.url.path.endsWith('/snapshot')
                    ? old
                    : {
                        'id': 'command-test',
                        'gateway_id': 'gateway-a',
                        'status': 'succeeded',
                        'result_code': 'applied',
                        'completed_at': completed.toIso8601String(),
                      },
              ),
              200,
            );
          }),
        );
      } finally {
        router.dispose();
      }
    },
  );

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
          expect(requests.every((r) => r.method == 'GET'), isTrue);
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
