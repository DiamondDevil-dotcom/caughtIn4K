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
}
