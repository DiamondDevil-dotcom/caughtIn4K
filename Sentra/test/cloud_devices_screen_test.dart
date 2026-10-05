import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:nyxis_security/providers/auth_provider.dart';
import 'package:nyxis_security/providers/router_device_provider.dart';
import 'package:nyxis_security/screens/devices_screen.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';

void main() {
  late RouterDeviceProvider router;

  setUp(() {
    CloudApiService.configure(
      'https://staging.example',
      'test-private-staging-token-32-characters',
    );
    CloudApiService.session = 'cloud-v1.test.signature';
    router = RouterDeviceProvider();
    router.devices = [
      {
        'mac': 'aa:bb:cc:dd:ee:ff',
        'name': 'Test phone',
        'status': 'SAFE',
        'blocked': false,
      },
    ];
    CloudApiService.lastSnapshot = {
      'observed_at': DateTime.now().toUtc().toIso8601String(),
      'data_stale': false,
      'recent_contact': true,
    };
  });

  tearDown(() {
    router.dispose();
    CloudApiService.disable();
  });

  Future<void> mount(WidgetTester tester, String role) async {
    CloudApiService.select({
      'household_id': 'home',
      'gateway_id': 'gateway',
      'role': role,
    });
    CloudApiService.lastSnapshot = {
      'observed_at': DateTime.now().toUtc().toIso8601String(),
      'data_stale': false,
      'recent_contact': true,
    };
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: router),
          ChangeNotifierProvider(create: (_) => AuthProvider()),
        ],
        child: const MaterialApp(home: DevicesScreen()),
      ),
    );
  }

  testWidgets('members can see devices but cannot block or remove', (
    tester,
  ) async {
    await mount(tester, 'member');
    expect(find.text('Test phone'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.widgetWithText(FilledButton, 'Block'))
          .onPressed,
      isNull,
    );
    expect(find.text('Remove'), findsNothing);
    expect(find.byTooltip('Add device'), findsNothing);
    expect(find.textContaining('Read-only'), findsOneWidget);
  });

  testWidgets(
    'owner gets confirmation and pending/stale controls are disabled',
    (tester) async {
      await mount(tester, 'owner');
      final button = find.widgetWithText(FilledButton, 'Block');
      expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.text('Block device?'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      router.pendingControlMac = 'aa:bb:cc:dd:ee:ff';
      router.notifyListeners();
      await tester.pump();
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Waiting for Pi...'),
            )
            .onPressed,
        isNull,
      );
      router.pendingControlMac = null;
      CloudApiService.lastSnapshot!['data_stale'] = true;
      router.notifyListeners();
      await tester.pump();
      expect(tester.widget<FilledButton>(button).onPressed, isNull);
      expect(find.textContaining('stale/offline'), findsOneWidget);
    },
  );
}
