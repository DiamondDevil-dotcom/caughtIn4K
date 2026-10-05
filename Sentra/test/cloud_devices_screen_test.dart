import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:nyxis_security/providers/alert_provider.dart';
import 'package:nyxis_security/providers/auth_provider.dart';
import 'package:nyxis_security/providers/router_device_provider.dart';
import 'package:nyxis_security/screens/devices_screen.dart';
import 'package:nyxis_security/screens/home_screen.dart';
import 'package:nyxis_security/services/cloud_api_service.dart';

void main() {
  late RouterDeviceProvider router;

  setUp(() {
    GoogleFonts.config.allowRuntimeFetching = false;
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

  Future<void> mount(
    WidgetTester tester,
    String role, {
    Widget screen = const DevicesScreen(),
  }) async {
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
          ChangeNotifierProvider(create: (_) => AlertProvider()),
        ],
        child: MaterialApp(home: screen),
      ),
    );
  }

  testWidgets(
    'parallel device warnings remain visible after one device blocks',
    (tester) async {
      const second = '11:22:33:44:55:66';
      router.devices.single['status'] = 'BLOCKED';
      router.devices.single['blocked'] = true;
      router.devices.add({
        'mac': second,
        'name': 'Second phone',
        'status': 'SAFE',
        'blocked': false,
      });
      await mount(tester, 'owner');
      final timestamp = DateTime.now()
          .subtract(const Duration(seconds: 3))
          .toUtc()
          .toIso8601String();
      final alerts = [
        {
          'event_id': 1,
          'mac': 'aa:bb:cc:dd:ee:ff',
          'status': 'WARNING',
          'timestamp': timestamp,
        },
        {
          'event_id': 2,
          'mac': 'aa:bb:cc:dd:ee:ff',
          'status': 'BLOCKED',
          'timestamp': timestamp,
        },
        {
          'event_id': 3,
          'mac': second,
          'status': 'WARNING',
          'timestamp': timestamp,
        },
      ];
      CloudApiService.lastSnapshot!['alerts'] = alerts;
      router.notifyListeners();
      await tester.pump();
      expect(router.recentWarnings.length, 2);
      expect(
        find.text('Recent WARNING detected on this device (last 60 seconds).'),
        findsNWidgets(2),
      );

      expect(find.text('BLOCKED'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Unblock'), findsOneWidget);
      await mount(tester, 'owner', screen: const HomeScreen());
      CloudApiService.lastSnapshot!['alerts'] = alerts;
      router.notifyListeners();
      await tester.pump();
      expect(find.text('Recent WARNING: Test phone'), findsOneWidget);
      expect(find.text('Recent WARNING: Second phone'), findsOneWidget);
      CloudApiService.lastSnapshot!['data_stale'] = true;
      router.notifyListeners();
      await tester.pump();
      expect(router.recentWarnings, isEmpty);
      expect(find.textContaining('Recent WARNING:'), findsNothing);
    },
  );

  testWidgets(
    'cloud FL button and progress are restored for owner, member read-only',
    (tester) async {
      router.federatedStatus = {
        'cloud_model': {
          'available': true,
          'federated': {
            'observed_at': DateTime.now().toUtc().toIso8601String(),
            'status': 'federated',
            'federated_round': 4,
            'training': {
              'state': 'idle',
              'current_round': 0,
              'total_rounds': 10,
            },
          },
        },
      };
      await mount(tester, 'owner', screen: const HomeScreen());
      CloudApiService.lastSnapshot!['training_available'] = true;
      router.notifyListeners();
      await tester.pump();
      await tester.scrollUntilVisible(find.text('Update global model'), 300);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Update global model'),
            )
            .onPressed,
        isNotNull,
      );
      expect(
        find.text('Pi checkpoint: FedAvg global model, round 4.'),
        findsOneWidget,
      );
      final federated =
          (router.federatedStatus!['cloud_model'] as Map)['federated'] as Map;
      federated['training'] = {
        'state': 'running',
        'current_round': 5,
        'total_rounds': 10,
      };
      router.notifyListeners();
      await tester.pump();
      expect(find.text('Training: running · round 5/10'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Training in progress'),
            )
            .onPressed,
        isNull,
      );
      await mount(tester, 'member', screen: const HomeScreen());
      expect(find.text('Update global model'), findsNothing);
      expect(
        find.text(
          'Only household owners and admins can update the global model.',
        ),
        findsOneWidget,
      );
    },
  );

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
      expect(find.byTooltip('Add device'), findsOneWidget);
      expect(find.text('Remove'), findsOneWidget);
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
      expect(
        find.textContaining('offline or updates are delayed'),
        findsOneWidget,
      );
    },
  );
  testWidgets(
    'confirmed unblock has consistent badge and button despite an older blocked snapshot',
    (tester) async {
      router.devices.single['status'] = 'BLOCKED';
      router.devices.single['blocked'] = true;
      router.recordConfirmedControl('aa:bb:cc:dd:ee:ff', false);
      await mount(tester, 'owner');
      expect(find.text('BLOCKED'), findsNothing);
      expect(find.text('SAFE'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Block'), findsOneWidget);
      router.recordConfirmedControl('aa:bb:cc:dd:ee:ff', true);
      await tester.pump();
      expect(find.text('BLOCKED'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Unblock'), findsOneWidget);
    },
  );

  testWidgets(
    'home uses effective device state without a fake Protected claim',
    (tester) async {
      router.recordConfirmedControl('aa:bb:cc:dd:ee:ff', true);
      await mount(tester, 'owner', screen: const HomeScreen());
      expect(find.text('Devices are blocked'), findsOneWidget);
      expect(find.text('1 blocked · 0 needing attention'), findsOneWidget);
      expect(find.text('Protected'), findsNothing);
      expect(find.textContaining('checkpoint'), findsNothing);
      router.recordConfirmedControl('aa:bb:cc:dd:ee:ff', false);
      await tester.pump();
      expect(find.text('No threats reported'), findsOneWidget);
      router.devices.clear();
      router.notifyListeners();
      await tester.pump();
      expect(find.text('Add your first device'), findsOneWidget);
      expect(find.text('No threats reported'), findsNothing);
      router.devices = [
        {'mac': 'aa:bb:cc:dd:ee:ff', 'status': 'UNKNOWN'},
      ];
      router.confirmedControls.clear();
      router.notifyListeners();
      await tester.pump();
      expect(find.text('Checking your devices'), findsOneWidget);
      CloudApiService.lastSnapshot!['data_stale'] = true;
      router.notifyListeners();
      await tester.pump();
      expect(find.text('Home updates delayed'), findsOneWidget);
    },
  );
}
