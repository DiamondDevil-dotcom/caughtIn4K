import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:caughtin4k_test/main.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('app smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const Fold8UltraSenderApp());

    expect(find.text('caughtIn4K Demo Data Sender'), findsOneWidget);
    expect(find.text('Sign in to gateway'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Send Normal Demo Once'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Send Normal Demo Once'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('owner signs in before labeled telemetry uses bearer token', (
    tester,
  ) async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      if (request.url.path == '/auth/login') {
        return http.Response(
          jsonEncode({'success': true, 'access_token': 'test-session'}),
          200,
        );
      }
      return http.Response('{"status":"NORMAL"}', 200);
    });
    await tester.pumpWidget(Fold8UltraSenderApp(client: client));
    await tester.enterText(
      find.widgetWithText(TextField, 'Owner email'),
      'owner@example.com',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'Password'),
      'test-password',
    );
    await tester.ensureVisible(find.text('Sign in to gateway'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sign in to gateway'));
    await tester.pumpAndSettle();
    expect(requests.length, 2);
    expect(
      requests.first.url.toString(),
      'http://192.168.50.198:8002/auth/login',
    );
    expect(requests.last.url.path, '/telemetry');
    expect(requests.first.headers['ngrok-skip-browser-warning'], 'true');
    expect(requests.last.headers['Authorization'], 'Bearer test-session');
    expect(jsonDecode(requests.last.body)['traffic_type'], 'normal');
    await tester.pumpWidget(const SizedBox());
    client.close();
  });

  testWidgets('sign-in timeout is actionable and does not send telemetry', (
    tester,
  ) async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      throw TimeoutException('Test timeout');
    });
    await tester.pumpWidget(Fold8UltraSenderApp(client: client));
    await tester.enterText(
      find.widgetWithText(TextField, 'Owner email'),
      'owner@example.com',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'Password'),
      'test-password',
    );
    await tester.ensureVisible(find.text('Sign in to gateway'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sign in to gateway'));
    await tester.pumpAndSettle();
    expect(requests, hasLength(1));
    await tester.scrollUntilVisible(
      find.textContaining('Gateway sign-in timed out.'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.textContaining('Gateway sign-in timed out.'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    client.close();
  });
}
