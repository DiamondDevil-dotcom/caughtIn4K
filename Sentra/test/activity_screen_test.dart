import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:nyxis_security/providers/activity_provider.dart';
import 'package:nyxis_security/providers/router_device_provider.dart';
import 'package:nyxis_security/screens/activity_screen.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';

void main() {
  late ActivityProvider activity;
  late RouterDeviceProvider router;

  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
    CloudApiService.configure(
      'https://staging.example',
      'test-private-staging-token-32-characters',
    );
    activity = ActivityProvider();
    router = RouterDeviceProvider();
  });
  tearDown(() {
    activity.dispose();
    router.dispose();
    CloudApiService.disable();
  });

  Future<void> mount(WidgetTester tester) => tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: activity),
        ChangeNotifierProvider.value(value: router),
      ],
      child: const MaterialApp(home: ActivityScreen()),
    ),
  );

  testWidgets(
    'cloud MAC-only events use matching device names without unknown IP',
    (tester) async {
      router.devices = [
        {'mac': 'aa:bb:cc:dd:ee:ff', 'name': 'Galaxy phone'},
      ];
      activity.events = [
        {
          'mac': 'AA:BB:CC:DD:EE:FF',
          'name': 'Unknown device',
          'status': 'WARNING',
          'attack_probability': 87.5,
          'ip_address': 'unknown ip',
          'timestamp': '2026-10-09T12:00:00Z',
        },
      ];
      await mount(tester);
      expect(find.text('Galaxy phone: WARNING'), findsOneWidget);
      expect(find.text('87.50% attack confidence'), findsOneWidget);
      expect(find.textContaining('unknown ip'), findsNothing);
      expect(find.textContaining('AA:BB:CC:DD:EE:FF'), findsNothing);
    },
  );

  testWidgets(
    'event name is retained without a device match and IP is omitted',
    (tester) async {
      activity.events = [
        {
          'mac': 'aa:bb:cc:dd:ee:ff',
          'name': 'Kitchen camera',
          'status': 'SAFE',
          'attack_probability': 2,
          'ip_address': '192.168.50.24',
        },
      ];
      await mount(tester);
      expect(find.text('Kitchen camera: SAFE'), findsOneWidget);
      expect(find.text('98.00% benign confidence'), findsOneWidget);
      expect(find.textContaining('192.168.50.24'), findsNothing);
    },
  );

  testWidgets('missing names are explicit and resolve when devices arrive', (
    tester,
  ) async {
    activity.events = [
      {
        'mac': 'aa:bb:cc:dd:ee:ff',
        'name': 'aa:bb:cc:dd:ee:ff',
        'status': 'ATTACK',
        'attack_probability': 90,
      },
    ];
    await mount(tester);
    expect(find.text('Unnamed device: ATTACK'), findsOneWidget);
    expect(find.text('90.00% attack confidence'), findsOneWidget);
    router.devices = [
      {'mac': 'aa:bb:cc:dd:ee:ff', 'name': 'Living room TV'},
    ];
    router.notifyListeners();
    await tester.pump();
    expect(find.text('Living room TV: ATTACK'), findsOneWidget);
    expect(find.textContaining('aa:bb:cc:dd:ee:ff'), findsNothing);
  });
}
