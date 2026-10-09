import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:image_picker/image_picker.dart';

import '../models/setup_label.dart';

class SetupQrScreen extends StatefulWidget {
  const SetupQrScreen({super.key, this.imagePicker});
  final ImagePicker? imagePicker;
  @override
  State<SetupQrScreen> createState() => _SetupQrScreenState();
}

class _SetupQrScreenState extends State<SetupQrScreen> {
  final controller = MobileScannerController(formats: [BarcodeFormat.qrCode]);
  bool accepted = false;
  bool importing = false;
  String? error;

  void acceptCapture(BarcodeCapture capture) {
    if (accepted || !mounted) return;
    final labels = <String>{};
    for (final barcode in capture.barcodes) {
      final value = barcode.rawValue;
      if (value == null) continue;
      try {
        labels.add(jsonEncode(SetupLabel.parse(value).toJson()));
      } on FormatException {
        // Ignore unrelated barcodes; never interpret them as setup credentials.
      }
    }
    if (labels.length != 1) {
      setState(
        () => error = labels.isEmpty
            ? 'No valid caughtIn4K setup QR found. Choose the label for your new Pi.'
            : 'More than one setup QR found. Use an image containing only one Pi label.',
      );
      return;
    }
    accepted = true;
    Navigator.pop(context, labels.single);
  }

  Future<void> importGallery() async {
    if (importing || accepted) return;
    setState(() {
      importing = true;
      error = null;
    });
    try {
      final image = await (widget.imagePicker ?? ImagePicker()).pickImage(
        source: ImageSource.gallery,
        requestFullMetadata: false,
      );
      if (image == null || !mounted || accepted) return;
      final capture = await controller.analyzeImage(
        image.path,
        formats: [BarcodeFormat.qrCode],
      );
      if (!mounted || accepted) return;
      if (capture == null) {
        setState(
          () => error =
              'No QR code found. Choose a clear image of the Pi setup label.',
        );
      } else {
        acceptCapture(capture);
      }
    } on UnsupportedError {
      if (mounted) {
        setState(
          () => error = 'Gallery QR reading is not supported on this device. Enter the setup label manually.',
        );
      }
    } on Exception {
      if (mounted) {
        setState(
          () => error = 'The QR image could not be read. Check photo access or enter the setup label manually.',
        );
      }
    } finally {
      if (mounted) setState(() => importing = false);
    }
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Scan your Pi setup label')),
    body: Column(
      children: [
        Expanded(
          child: MobileScanner(
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
              if (!importing) acceptCapture(capture);
            },
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                if (error != null)
                  Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                FilledButton.icon(
                  onPressed: importing ? null : importGallery,
                  icon: const Icon(Icons.photo_library_outlined),
                  label: Text(
                    importing
                        ? 'Reading QR image...'
                        : 'Choose QR from gallery',
                  ),
                ),
                TextButton(
                  onPressed: importing ? null : () => Navigator.pop(context),
                  child: const Text('Enter setup label manually'),
                ),
              ],
            ),
          ),
        ),
      ],
    ),
  );
}
