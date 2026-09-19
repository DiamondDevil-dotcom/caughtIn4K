class AlertModel {
  final String device;
  final String attack;
  final double confidence;
  final String status;

  AlertModel({
    required this.device,
    required this.attack,
    required this.confidence,
    required this.status,
  });

  factory AlertModel.fromJson(Map<String, dynamic> json) {
    return AlertModel(
      device: json["device"],
      attack: json["attack"],
      confidence: (json["confidence"] as num).toDouble(),
      status: json["status"],
    );
  }
}