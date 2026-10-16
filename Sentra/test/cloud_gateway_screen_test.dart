import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:nyxis_security/providers/auth_provider.dart';
import 'package:nyxis_security/screens/cloud_gateway_screen.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';

void main() {
  const label = {
    'version': 1,
    'gateway_id': '11111111-2222-3333-4444-555555555555',
    'pairing_code': 'test-code',
  };
  setUp(() {
    CloudApiService.configure(
      'https://staging.example',
      'test-private-staging-token-32-characters',
    );
    CloudApiService.session = 'test-session';
  });
  tearDown(CloudApiService.disable);

  Future<void> mount(WidgetTester tester) async {
    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => AuthProvider(),
        child: const MaterialApp(home: CloudGatewayScreen()),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('lost QR uses only the order and clears an obsolete label', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(900, 1800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final requests = <http.Request>[];
    await http.runWithClient(
      () async {
        await mount(tester);
        await tester.enterText(
          find.widgetWithText(TextField, 'Pi setup label (or scan QR)'),
          jsonEncode(label),
        );
        await tester.enterText(
          find.widgetWithText(TextField, 'Pi order reference'),
          'order-123',
        );
        await tester.ensureVisible(find.text('Request replacement setup QR'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Request replacement setup QR'));
        await tester.pumpAndSettle();
        expect(find.text('Replacement sent.'), findsOneWidget);
        final posts = requests
            .where((request) => request.method == 'POST')
            .toList();
        expect(posts, hasLength(1));
        expect(posts.single.url.path, '/cloud/gateways/replace-setup-qr');
        expect(jsonDecode(posts.single.body), {'order_reference': 'order-123'});
        final field = tester.widget<TextField>(
          find.widgetWithText(TextField, 'Pi setup label (or scan QR)'),
        );
        expect(field.controller!.text, isEmpty);
        expect(CloudApiService.gatewayId, isNull);
        await tester.pumpWidget(const SizedBox());
      },
      () => MockClient((request) async {
        requests.add(request);
        return http.Response(
          request.method == 'GET'
              ? '{"households":[]}'
              : '{"success":true,"message":"Replacement sent."}',
          200,
        );
      }),
    );
  });

  testWidgets('email QR sends only the supplied label and never pairs a Pi', (
    tester,
  ) async {
    final requests = <http.Request>[];
    await http.runWithClient(
      () async {
        await mount(tester);
        await tester.enterText(
          find.widgetWithText(TextField, 'Pi setup label (or scan QR)'),
          jsonEncode(label),
        );
        await tester.ensureVisible(find.text('Email my setup QR'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Email my setup QR'));
        await tester.pumpAndSettle();
        expect(
          find.text('Setup QR sent to your verified account email.'),
          findsOneWidget,
        );
        final posts = requests
            .where((request) => request.method == 'POST')
            .toList();
        expect(posts, hasLength(1));
        expect(posts.single.url.path, '/cloud/gateways/email-setup-qr');
        expect(jsonDecode(posts.single.body), {
          'gateway_id': label['gateway_id'],
          'pairing_code': label['pairing_code'],
        });
        expect(CloudApiService.gatewayId, isNull);
        await tester.pumpWidget(const SizedBox());
      },
      () => MockClient((request) async {
        requests.add(request);
        return http.Response(
          jsonEncode(
            request.method == 'GET'
                ? {'households': []}
                : {
                    'success': true,
                    'message': 'Setup QR sent to your verified account email.',
                  },
          ),
          200,
        );
      }),
    );
  });

  testWidgets('email QR rejects invalid labels without sending secrets', (
    tester,
  ) async {
    final requests = <http.Request>[];
    await http.runWithClient(
      () async {
        await mount(tester);
        await tester.enterText(
          find.widgetWithText(TextField, 'Pi setup label (or scan QR)'),
          'invalid-label',
        );
        await tester.ensureVisible(find.text('Email my setup QR'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Email my setup QR'));
        await tester.pumpAndSettle();
        expect(
          find.textContaining('setup text supplied with your new Pi'),
          findsOneWidget,
        );
        expect(requests.where((request) => request.method == 'POST'), isEmpty);
        await tester.pumpWidget(const SizedBox());
      },
      () => MockClient((request) async {
        requests.add(request);
        return http.Response('{"households":[]}', 200);
      }),
    );
  });

  testWidgets(
    'pairing a consumer Pi opens Wi-Fi setup without selecting the dashboard',
    (tester) async {
      bool paired = false;
      await tester.binding.setSurfaceSize(const Size(900, 1800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await http.runWithClient(
        () async {
          await mount(tester);
          await tester.enterText(
            find.widgetWithText(TextField, 'Pi setup label (or scan QR)'),
            jsonEncode(label),
          );
          await tester.ensureVisible(find.text('Pair my Pi'));
          await tester.tap(find.text('Pair my Pi'));
          await tester.pumpAndSettle();
          expect(
            find.text('Set up your caughtIn4K'),
            findsOneWidget,
            reason: find
                .byType(Text)
                .evaluate()
                .map((element) => (element.widget as Text).data)
                .join('\n'),
          );
          expect(CloudApiService.gatewayId, isNull);
          // The consumed ownership label is not needed to resume setup.
          await tester.pageBack();
          await tester.pumpAndSettle();
          await tester.ensureVisible(find.text('Consumer home'));
          await tester.tap(find.text('Consumer home'));
          await tester.pumpAndSettle();
          expect(find.text('Set up your caughtIn4K'), findsOneWidget);
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          if (request.url.path == '/cloud/gateways/pair') {
            paired = true;
            return http.Response(
              jsonEncode({'gateway_id': label['gateway_id']}),
              201,
            );
          }
          if (request.url.path == '/cloud/households') {
            return http.Response(
              jsonEncode({
                'households': paired
                    ? [
                        {
                          'household_id': 'home',
                          'name': 'Consumer home',
                          'role': 'owner',
                        },
                      ]
                    : [],
              }),
              200,
            );
          }
          if (request.url.path.endsWith('/gateways')) {
            return http.Response(
              jsonEncode({
                'gateways': [
                  {
                    'gateway_id': label['gateway_id'],
                    'name': 'New Pi',
                    'consumer_setup': true,
                  },
                ],
              }),
              200,
            );
          }
          return http.Response(
            jsonEncode({
              'ready': false,
              'recent_contact': false,
              'configured': false,
              'expired': false,
              'checks': {},
            }),
            200,
          );
        }),
      );
    },
  );
}
