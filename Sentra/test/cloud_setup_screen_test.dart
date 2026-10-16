import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nyxis_security/screens/cloud_setup_screen.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';

void main() {
  const gateway = {
    'household_id': '11111111-2222-4333-8444-555555555555',
    'gateway_id': 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
    'role': 'owner',
    'consumer_setup': true,
  };
  Map<String, dynamic> status({bool ready = false}) => {
    'ready': ready,
    'recent_contact': true,
    'configured': ready,
    'expired': false,
    'request_id': ready ? 'applied-revision' : null,
    'error_code': null,
    'checks': {
      'ethernet': true,
      'wifi': ready,
      'router': ready,
      'model': ready,
      'firewall': ready,
    },
  };
  setUp(() {
    CloudApiService.configure(
      'https://staging.example',
      'test-private-staging-token-32-characters',
    );
    CloudApiService.session = 'test-session';
  });
  tearDown(CloudApiService.disable);

  Future<void> mount(
    WidgetTester tester, {
    Map<String, dynamic>? choice,
  }) async {
    await tester.binding.setSurfaceSize(const Size(900, 1800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(home: CloudSetupScreen(gateway: choice ?? gateway)),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'Wi-Fi save waits for applied readiness and clears the password',
    (tester) async {
      final requests = <http.Request>[];
      bool saved = false;
      await http.runWithClient(
        () async {
          await mount(tester);
          expect(
            tester
                .widget<FilledButton>(
                  find.widgetWithText(FilledButton, 'Open my home'),
                )
                .onPressed,
            isNull,
          );
          await tester.enterText(
            find.widgetWithText(TextFormField, 'IoT Wi-Fi name'),
            'Customer IoT',
          );
          await tester.enterText(
            find.widgetWithText(TextFormField, 'IoT Wi-Fi password'),
            'private-test-password',
          );
          await tester.ensureVisible(find.text('Set up IoT Wi-Fi'));
          await tester.tap(find.text('Set up IoT Wi-Fi'));
          await tester.pumpAndSettle();
          final put = requests.singleWhere(
            (request) => request.method == 'PUT',
          );
          final body = jsonDecode(put.body) as Map<String, dynamic>;
          expect(body['ssid'], 'Customer IoT');
          expect(body['password'], 'private-test-password');
          expect(
            body['request_id'],
            matches(
              RegExp(
                r'^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$',
              ),
            ),
          );
          expect(
            put.url.path,
            contains('/households/${gateway['household_id']}/gateways/'),
          );
          final password = tester.widget<TextFormField>(
            find.widgetWithText(TextFormField, 'IoT Wi-Fi password'),
          );
          expect(password.controller!.text, isEmpty);
          expect(
            tester
                .widget<FilledButton>(
                  find.widgetWithText(FilledButton, 'Open my home'),
                )
                .onPressed,
            isNotNull,
          );
          expect(CloudApiService.gatewayId, isNull);
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          requests.add(request);
          if (request.method == 'PUT') {
            saved = true;
            return http.Response(
              jsonEncode({
                'request_id': jsonDecode(request.body)['request_id'],
              }),
              200,
            );
          }
          return http.Response(jsonEncode(status(ready: saved)), 200);
        }),
      );
    },
  );

  testWidgets('invalid Wi-Fi is rejected before any password request', (
    tester,
  ) async {
    final requests = <http.Request>[];
    await http.runWithClient(
      () async {
        await mount(tester);
        await tester.enterText(
          find.widgetWithText(TextFormField, 'IoT Wi-Fi name'),
          'Bad\nSSID',
        );
        await tester.enterText(
          find.widgetWithText(TextFormField, 'IoT Wi-Fi password'),
          'short',
        );
        await tester.ensureVisible(find.text('Set up IoT Wi-Fi'));
        await tester.tap(find.text('Set up IoT Wi-Fi'));
        await tester.pumpAndSettle();
        expect(
          find.text('Use 8–63 printable ASCII characters.'),
          findsOneWidget,
        );
        expect(requests.where((request) => request.method == 'PUT'), isEmpty);
        await tester.pumpWidget(const SizedBox());
      },
      () => MockClient((request) async {
        requests.add(request);
        return http.Response(jsonEncode(status()), 200);
      }),
    );
  });

  testWidgets(
    'restart resumes checks and later connection failure removes readiness',
    (tester) async {
      bool failed = false;
      await http.runWithClient(
        () async {
          await mount(tester);
          expect(
            tester
                .widget<FilledButton>(
                  find.widgetWithText(FilledButton, 'Open my home'),
                )
                .onPressed,
            isNotNull,
          );
          failed = true;
          await tester.pump(const Duration(seconds: 5));
          await tester.pumpAndSettle();
          expect(
            tester
                .widget<FilledButton>(
                  find.widgetWithText(FilledButton, 'Open my home'),
                )
                .onPressed,
            isNull,
          );
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient(
          (request) async => failed
              ? http.Response(
                  '{"detail":"Setup temporarily unavailable."}',
                  503,
                )
              : http.Response(jsonEncode(status(ready: true)), 200),
        ),
      );
    },
  );

  testWidgets(
    'a stale in-flight status cannot mark newly submitted settings ready',
    (tester) async {
      final delayed = Completer<http.Response>();
      int gets = 0;
      await http.runWithClient(
        () async {
          await mount(tester);
          await tester.pump(const Duration(seconds: 5));
          await tester.enterText(
            find.widgetWithText(TextFormField, 'IoT Wi-Fi name'),
            'New IoT',
          );
          await tester.enterText(
            find.widgetWithText(TextFormField, 'IoT Wi-Fi password'),
            'test-only-password',
          );
          await tester.ensureVisible(find.text('Set up IoT Wi-Fi'));
          await tester.tap(find.text('Set up IoT Wi-Fi'));
          await tester.pump();
          delayed.complete(http.Response(jsonEncode(status(ready: true)), 200));
          await tester.pumpAndSettle();
          expect(
            tester
                .widget<FilledButton>(
                  find.widgetWithText(FilledButton, 'Open my home'),
                )
                .onPressed,
            isNull,
          );
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          if (request.method == 'PUT') {
            return http.Response(
              jsonEncode({
                'request_id': jsonDecode(request.body)['request_id'],
              }),
              200,
            );
          }
          gets++;
          if (gets == 2) return delayed.future;
          return http.Response(jsonEncode(status()), 200);
        }),
      );
    },
  );

  testWidgets(
    'household members may see checks but cannot submit credentials',
    (tester) async {
      await http.runWithClient(
        () async {
          await mount(tester, choice: {...gateway, 'role': 'member'});
          expect(
            find.text(
              'A household owner or admin must choose the Wi-Fi settings.',
            ),
            findsOneWidget,
          );
          expect(find.byType(TextFormField), findsNothing);
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient(
          (request) async => http.Response(jsonEncode(status()), 200),
        ),
      );
    },
  );
}
