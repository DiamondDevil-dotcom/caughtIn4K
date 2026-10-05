import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:nyxis_security/providers/auth_provider.dart';
import 'package:nyxis_security/providers/router_device_provider.dart';
import 'package:nyxis_security/screens/account_gate.dart';
import 'package:nyxis_security/screens/auth_screen.dart';
import 'package:nyxis_security/screens/cloud_gateway_screen.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';
import 'package:nyxis_security/services/router_api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const mac = 'aa:bb:cc:dd:ee:ff';
  const account = {
    'success': true,
    'account_id': 'owner-a',
    'name': 'Owner',
    'email': 'owner@example.invalid',
    'email_verified': false,
    'access_token': 'cloud-v1.test.signature',
  };
  const gateway = {
    'household_id': 'home-a',
    'gateway_id': 'gateway-a',
    'role': 'owner',
    'name': 'My Pi',
  };
  Map<String, dynamic> snapshot() => {
    'gateway_id': 'gateway-a',
    'snapshot_available': true,
    'observed_at': DateTime.now().toUtc().toIso8601String(),
    'data_stale': false,
    'recent_contact': true,
    'devices': [
      {'mac': mac, 'name': 'Test phone', 'blocked': false, 'status': 'SAFE'},
    ],
    'alerts': [],
    'model': {'available': false},
  };
  http.Response reply(Object data, [int code = 200]) =>
      http.Response(jsonEncode(data), code);

  setUp(() async {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({});
    await RouterApiService.init();
  });
  tearDown(CloudApiService.disable);

  test('confirmed buttons ignore older snapshots, but accept newer authoritative state', () async {
    final router = RouterDeviceProvider();
    CloudApiService.session = account['access_token'] as String;
    CloudApiService.select(gateway);
    final completed = DateTime.now();
    var observed = completed.subtract(const Duration(seconds: 1));
    router.recordConfirmedControl(mac, true, completedAt: completed);
    await http.runWithClient(
      () async {
        await router.refresh();
        expect(router.confirmedControls[mac], isTrue);
        observed = completed.add(const Duration(seconds: 1));
        await router.refresh();
        expect(router.confirmedControls, isEmpty);
        expect(router.devices.single['blocked'], isFalse);
      },
      () => MockClient(
        (request) async => reply({
          ...snapshot(),
          'observed_at': observed.toUtc().toIso8601String(),
        }),
      ),
    );
    router.dispose();
  });

  test('customer startup needs no operator configuration and restores encrypted account state', () async {
    expect(CloudApiService.customer, isTrue);
    expect(CloudApiService.stagingToken, isEmpty);
    await http.runWithClient(
      () => CloudApiService.login(account['email'] as String, 'test-password'),
      () => MockClient((request) async {
        expect(request.headers.containsKey('X-Cloud-Staging-Token'), isFalse);
        expect(request.headers.containsKey('X-Gateway-Credential'), isFalse);
        return reply(account);
      }),
    );
    expect((await SharedPreferences.getInstance()).getKeys(), isEmpty);
    await RouterApiService.init();
    expect(CloudApiService.savedAccount?['account_id'], 'owner-a');
    expect(CloudApiService.session, account['access_token']);
    await RouterApiService.clearSession();
    await RouterApiService.init();
    expect(CloudApiService.savedAccount, isNull);
  });

  test('signup and recovery use the customer account endpoints', () async {
    final paths = <String>[];
    await http.runWithClient(
      () async {
        final signup = await RouterApiService.signUp(
          name: 'Owner',
          email: account['email'] as String,
          password: 'test-password',
          accessCode: '',
        );
        expect(signup['success'], isTrue);
        await RouterApiService.requestPasswordReset(account['email'] as String);
        await RouterApiService.resetPassword(
          email: account['email'] as String,
          token: 'test-code',
          newPassword: 'new-password',
        );
      },
      () => MockClient((request) async {
        paths.add(request.url.path);
        expect(request.headers.containsKey('X-Cloud-Staging-Token'), isFalse);
        return request.url.path.endsWith('/signup')
            ? reply(account, 201)
            : reply({'success': true});
      }),
    );
    expect(paths, [
      '/cloud/auth/signup',
      '/cloud/auth/request-password-reset',
      '/cloud/auth/reset-password',
    ]);
  });

  test('unresolved actions survive restart and sign-out without replay or cross-account leakage', () async {
    String? id;
    var posts = 0;
    await http.runWithClient(
      () async {
        await CloudApiService.login(
          account['email'] as String,
          'test-password',
        );
        CloudApiService.select(gateway);
        await expectLater(
          CloudApiService.control(mac, 'block', pollInterval: Duration.zero),
          throwsException,
        );
        expect(CloudApiService.commandUnconfirmed, isTrue);
        await RouterApiService.init();
        CloudApiService.select(gateway);
        expect(CloudApiService.lastCommandId, id);
        await expectLater(
          CloudApiService.control(mac, 'block'),
          throwsException,
        );
        await RouterApiService.clearSession();
        await CloudApiService.login('second@example.invalid', 'test-password');
        CloudApiService.select(gateway);
        expect(CloudApiService.lastCommandId, isNull);
        await RouterApiService.clearSession();
        await CloudApiService.login(
          account['email'] as String,
          'test-password',
        );
        CloudApiService.select(gateway);
        expect(CloudApiService.lastCommandId, id);
        expect((await CloudApiService.commandStatus())['status'], 'unknown');
        expect(posts, 1);
      },
      () => MockClient((request) async {
        if (request.url.path.endsWith('/login')) {
          final email = (jsonDecode(request.body) as Map)['email'];
          return reply({
            ...account,
            if (email != account['email']) 'account_id': 'owner-b',
          });
        }
        if (request.url.path.endsWith('/snapshot')) return reply(snapshot());
        if (request.method == 'POST') {
          posts++;
          id = (jsonDecode(request.body) as Map)['command_id'] as String;
          return reply({
            'id': id,
            'gateway_id': 'gateway-a',
            'mac': mac,
            'action': 'block',
          }, 202);
        }
        return reply({
          'id': id,
          'gateway_id': 'gateway-a',
          'status': 'unknown',
        });
      }),
    );
  });

  testWidgets(
    'customer sign-in and signup never show server, mode, or access-token fields',
    (tester) async {
      final auth = AuthProvider();
      await auth.load();
      await tester.pumpWidget(
        ChangeNotifierProvider.value(
          value: auth,
          child: const MaterialApp(home: AuthScreen()),
        ),
      );
      expect(find.text('Gateway / Server URL'), findsNothing);
      expect(find.textContaining('staging'), findsNothing);
      expect(find.textContaining('invitation code'), findsNothing);
      await tester.tap(find.text('New here? Create an account'));
      await tester.pump();
      expect(find.text('Full name'), findsOneWidget);
      expect(find.text('Create account'), findsOneWidget);
      expect(find.textContaining('setup or household'), findsNothing);
      auth.dispose();
    },
  );

  testWidgets(
    'unverified accounts see email verification instead of a home dashboard',
    (tester) async {
      await CloudApiService.rememberAccount(account);
      CloudApiService.session = account['access_token'] as String;
      final auth = AuthProvider();
      await auth.load();
      await tester.pumpWidget(
        ChangeNotifierProvider.value(
          value: auth,
          child: const MaterialApp(home: AccountGate()),
        ),
      );
      expect(find.text('Verify your email'), findsOneWidget);
      expect(find.text('Your smart home'), findsNothing);
      auth.dispose();
    },
  );

  test('unconfirmed training survives restart without a fake MAC or automatic replay', () async {
    String? id;
    var starts = 0;
    await http.runWithClient(
      () async {
        await CloudApiService.login(
          account['email'] as String,
          'test-password',
        );
        CloudApiService.select(gateway);
        await expectLater(
          CloudApiService.control(null, 'train', pollInterval: Duration.zero),
          throwsException,
        );
        expect(CloudApiService.commandUnconfirmed, isTrue);
        await RouterApiService.init();
        CloudApiService.select(gateway);
        expect(CloudApiService.lastCommandId, id);
        expect(CloudApiService.lastCommandMac, isNull);
        expect(CloudApiService.lastCommandAction, 'train');
        await expectLater(
          CloudApiService.control(null, 'train'),
          throwsException,
        );
        expect(starts, 1);
      },
      () => MockClient((request) async {
        if (request.url.path.endsWith('/login')) return reply(account);
        if (request.url.path.endsWith('/snapshot')) {
          return reply({
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
          });
        }
        if (request.method == 'POST') {
          starts++;
          id = (jsonDecode(request.body) as Map)['command_id'] as String;
          return reply({
            'id': id,
            'gateway_id': 'gateway-a',
            'mac': null,
            'action': 'train',
          }, 202);
        }
        return reply({
          'id': id,
          'gateway_id': 'gateway-a',
          'status': 'unknown',
        });
      }),
    );
  });

  testWidgets(
    'one home opens automatically but explicit home management stays accessible',
    (tester) async {
      final auth = AuthProvider();
      await auth.load();
      await http.runWithClient(
        () async {
          await tester.pumpWidget(
            ChangeNotifierProvider.value(
              value: auth,
              child: const MaterialApp(home: CloudGatewayScreen()),
            ),
          );
          await tester.pumpAndSettle();
          expect(CloudApiService.gatewayId, 'gateway-a');
          auth.chooseAnotherHome();
          await tester.pumpWidget(const SizedBox());
          await tester.pumpWidget(
            ChangeNotifierProvider.value(
              value: auth,
              child: const MaterialApp(home: CloudGatewayScreen()),
            ),
          );
          await tester.pumpAndSettle();
          expect(CloudApiService.gatewayId, isNull);
          expect(find.text('Pair my Pi'), findsOneWidget);
        },
        () => MockClient((request) async {
          if (request.url.path == '/cloud/households') {
            return reply({
              'households': [
                {'household_id': 'home-a', 'name': 'My home', 'role': 'owner'},
              ],
            });
          }
          return reply({
            'gateways': [
              {'gateway_id': 'gateway-a', 'name': 'My Pi', 'revoked_at': null},
            ],
          });
        }),
      );
      auth.dispose();
    },
  );
}
