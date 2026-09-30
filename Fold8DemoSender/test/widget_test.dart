import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:caughtin4k_test/main.dart';

void main() {
  testWidgets('app smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const Fold8UltraSenderApp());

    expect(find.text('caughtIn4K Test'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Send Normal Demo Once'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Send Normal Demo Once'), findsOneWidget);
  });
}
