class Device {
  final String name;
  final String location;
  final String ip;
  final String mac;
  final String manufacturer;
  final String firmware;
  final bool safe;
  final String? attack;

  const Device({
    required this.name,
    required this.location,
    required this.ip,
    required this.mac,
    required this.manufacturer,
    required this.firmware,
    this.safe = true,
    this.attack,
  });

  Device copyWith({
    bool? safe,
    String? attack,
  }) {
    return Device(
      name: name,
      location: location,
      ip: ip,
      mac: mac,
      manufacturer: manufacturer,
      firmware: firmware,
      safe: safe ?? this.safe,
      attack: attack ?? this.attack,
    );
  }
}