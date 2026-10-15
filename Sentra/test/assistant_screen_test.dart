import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nyxis_security/screens/assistant_screen.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';

void main() {
  setUp(() {
    CloudApiService.configure(
      'https://staging.example',
      'test-staging-token-at-least-32-characters',
    );
    CloudApiService.session = 'test-session';
  });
  tearDown(CloudApiService.disable);

  testWidgets(
    'consent gates text-only request and clear removes conversation',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final requests = <http.Request>[];
      await http.runWithClient(
        () async {
          await tester.pumpWidget(const MaterialApp(home: AssistantScreen()));
          await tester.enterText(
            find.byType(TextField),
            'How do I set up my Pi?',
          );
          await tester.tap(find.text('Ask AI'));
          await tester.pumpAndSettle();
          expect(requests, isEmpty);
          await tester.tap(find.byType(CheckboxListTile));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Ask AI'));
          await tester.pumpAndSettle();
          expect(requests, hasLength(1));
          expect(requests.single.url.path, '/cloud/assistant/chat');
          expect(jsonDecode(requests.single.body), {
            'message': 'How do I set up my Pi?',
          });
          expect(find.text('AI: Use the setup wizard.'), findsOneWidget);
          await tester.tap(find.text('Clear chat'));
          await tester.pumpAndSettle();
          expect(find.text('AI: Use the setup wizard.'), findsNothing);
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient((request) async {
          requests.add(request);
          return http.Response('{"reply":"Use the setup wizard."}', 200);
        }),
      );
    },
  );

  testWidgets(
    'unavailable service displays error and retains question for retry',
    (tester) async {
      await http.runWithClient(
        () async {
          await tester.pumpWidget(const MaterialApp(home: AssistantScreen()));
          await tester.tap(find.byType(CheckboxListTile));
          await tester.enterText(find.byType(TextField), 'Help');
          await tester.ensureVisible(find.text('Ask AI'));
          await tester.tap(find.text('Ask AI'));
          await tester.pumpAndSettle();
          expect(
            find.textContaining('unavailable or not configured'),
            findsOneWidget,
          );
          expect(
            tester.widget<TextField>(find.byType(TextField)).controller!.text,
            'Help',
          );
          await tester.pumpWidget(const SizedBox());
        },
        () => MockClient(
          (_) async =>
              http.Response('{"detail":"private provider diagnostic"}', 503),
        ),
      );
    },
  );
}
