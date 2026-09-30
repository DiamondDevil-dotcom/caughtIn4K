// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:nyxis_security/main.dart';
import 'package:nyxis_security/providers/alert_provider.dart';
import 'package:nyxis_security/providers/auth_provider.dart';
import 'package:nyxis_security/providers/device_provider.dart';
import 'package:nyxis_security/providers/router_device_provider.dart';
import 'package:nyxis_security/providers/theme_provider.dart';

void main() {
  testWidgets('caughtIn4K app starts', (WidgetTester tester) async {
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider(create: (_) => AlertProvider()),
          ChangeNotifierProvider(create: (_) => ThemeProvider()),
          ChangeNotifierProvider(create: (_) => AuthProvider()),
          ChangeNotifierProvider(create: (_) => DeviceProvider()),
          ChangeNotifierProvider(create: (_) => RouterDeviceProvider()),
        ],
        child: const NyxisApp(),
      ),
    );
    await tester.pump(const Duration(seconds: 3));
    expect(find.byType(NyxisApp), findsOneWidget);
  });
}
