import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

class SetupQrScreen extends StatefulWidget {
  const SetupQrScreen({super.key});
  @override
  State<SetupQrScreen> createState() => _SetupQrScreenState();
}

class _SetupQrScreenState extends State<SetupQrScreen> {
  final controller = MobileScannerController();
  bool accepted = false;
  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Scan your Pi setup label')),
    body: MobileScanner(
      controller: controller,
      errorBuilder: (context, error) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Camera unavailable. Allow camera access in phone settings, or enter the setup label without scanning.',
              ),
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Enter setup label'),
              ),
            ],
          ),
        ),
      ),
      onDetect: (capture) {
        for (final barcode in capture.barcodes) {
          final value = barcode.rawValue;
          if (!accepted && value != null) {
            accepted = true;
            Navigator.pop(context, value);
            break;
          }
        }
      },
    ),
  );
}
