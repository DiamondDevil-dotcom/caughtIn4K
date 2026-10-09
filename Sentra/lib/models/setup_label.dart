import 'dart:convert';

class SetupLabel {
  final String gatewayId;
  final String pairingCode;

  const SetupLabel._(this.gatewayId, this.pairingCode);

  factory SetupLabel.parse(String value) {
    if (value.length > 2048) {
      throw const FormatException('Use a caughtIn4K Pi setup QR label.');
    }
    final dynamic label;
    try {
      label = jsonDecode(value);
    } on FormatException {
      throw const FormatException(
        'Use the setup text supplied with your new Pi or copied from its setup email.',
      );
    }
    if (label is! Map<String, dynamic> ||
        label.length != 3 ||
        label['version'] != 1 ||
        label['gateway_id'] is! String ||
        !RegExp(
          r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
        ).hasMatch(label['gateway_id'] as String) ||
        label['pairing_code'] is! String ||
        (label['pairing_code'] as String).trim().isEmpty ||
        (label['pairing_code'] as String).length > 256) {
      throw const FormatException(
        'Use the caughtIn4K setup QR supplied with your new Pi, not its machine credential.',
      );
    }
    return SetupLabel._(
      label['gateway_id'] as String,
      (label['pairing_code'] as String).trim(),
    );
  }

  Map<String, dynamic> toJson() => {
    'version': 1,
    'gateway_id': gatewayId,
    'pairing_code': pairingCode,
  };
}
