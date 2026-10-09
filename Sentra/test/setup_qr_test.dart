import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:nyxis_security/models/setup_label.dart';
import 'package:nyxis_security/screens/setup_qr_screen.dart';

class TestImagePicker extends ImagePicker {
  bool cancelled = false;
  @override
  Future<XFile?> pickImage({
    required ImageSource source,
    double? maxWidth,
    double? maxHeight,
    int? imageQuality,
    CameraDevice preferredCameraDevice = CameraDevice.rear,
    bool requestFullMetadata = true,
  }) async {
    expect(source, ImageSource.gallery);
    expect(requestFullMetadata, isFalse);
    return cancelled ? null : XFile('test-setup.png');
  }
}

void main() {
  const label = {
    'version': 1,
    'gateway_id': '11111111-2222-3333-4444-555555555555',
    'pairing_code': 'test-code',
  };
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  const scanner = MethodChannel(
    'dev.steenbakker.mobile_scanner/scanner/method',
  );
  final picker = TestImagePicker();
  List<String> values = [];
  int analyzed = 0;

  setUp(() {
    picker.cancelled = false;
    values = [jsonEncode(label)];
    analyzed = 0;
    binding.defaultBinaryMessenger.setMockMethodCallHandler(scanner, (
      call,
    ) async {
      if (call.method == 'state') return 2;
      if (call.method == 'request') return false;
      if (call.method == 'analyzeImage') {
        analyzed++;
        expect((call.arguments as Map)['filePath'], 'test-setup.png');
        return {
          'data': values
              .map((value) => {'rawValue': value, 'format': 256})
              .toList(),
        };
      }
      return null;
    });
    for (final name in ['event', 'deviceOrientation']) {
      binding.defaultBinaryMessenger.setMockMethodCallHandler(
        MethodChannel('dev.steenbakker.mobile_scanner/scanner/$name'),
        (call) async => null,
      );
    }
  });

  tearDown(() {
    binding.defaultBinaryMessenger.setMockMethodCallHandler(scanner, null);
    for (final name in ['event', 'deviceOrientation']) {
      binding.defaultBinaryMessenger.setMockMethodCallHandler(
        MethodChannel('dev.steenbakker.mobile_scanner/scanner/$name'),
        null,
      );
    }
  });

  test('setup label rejects invalid or machine credential payloads', () {
    expect(SetupLabel.parse(jsonEncode(label)).toJson(), label);
    for (final invalid in [
      '',
      'null',
      '[]',
      '{}',
      'x' * 2049,
      jsonEncode({...label, 'version': 2}),
      jsonEncode({...label, 'gateway_id': 'invalid'}),
      jsonEncode({...label, 'pairing_code': ' '}),
      jsonEncode({...label, 'gateway_credential': 'machine-secret'}),
    ]) {
      expect(() => SetupLabel.parse(invalid), throwsFormatException);
    }
  });

  Future<void> openScanner(
    WidgetTester tester,
    ValueChanged<String?> result,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async => result(
                await Navigator.push<String>(
                  context,
                  MaterialPageRoute(
                    builder: (_) => SetupQrScreen(imagePicker: picker),
                  ),
                ),
              ),
              child: const Text('Open scanner'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open scanner'));
    await tester.pumpAndSettle();
  }

  testWidgets('gallery import works when camera access is denied', (
    tester,
  ) async {
    String? result;
    await openScanner(tester, (value) => result = value);
    expect(find.textContaining('Camera unavailable.'), findsOneWidget);
    await tester.tap(find.text('Choose QR from gallery'));
    await tester.pumpAndSettle();
    expect(analyzed, 1);
    expect(jsonDecode(result!), label);
    expect(find.text('Open scanner'), findsOneWidget);
  });

  testWidgets('unrelated or multiple setup codes do not close scanner', (
    tester,
  ) async {
    await openScanner(tester, (_) => fail('Invalid QR must not be accepted'));
    values = ['https://example.invalid'];
    await tester.tap(find.text('Choose QR from gallery'));
    await tester.pumpAndSettle();
    expect(find.textContaining('No valid caughtIn4K setup QR'), findsOneWidget);
    values = [
      jsonEncode(label),
      jsonEncode({...label, 'pairing_code': 'another-code'}),
    ];
    await tester.tap(find.text('Choose QR from gallery'));
    await tester.pumpAndSettle();
    expect(find.textContaining('More than one setup QR'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  });

  testWidgets('cancelled gallery selection is not treated as a scan', (
    tester,
  ) async {
    picker.cancelled = true;
    await openScanner(
      tester,
      (_) => fail('Cancellation must not return a label'),
    );
    await tester.tap(find.text('Choose QR from gallery'));
    await tester.pumpAndSettle();
    expect(analyzed, 0);
    expect(find.text('Choose QR from gallery'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  });
}
