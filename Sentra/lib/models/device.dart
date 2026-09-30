class Device {
  final String id;
  final String name;
  final String location;
  final String ip;
  final String mac;
  final String manufacturer;
  final String firmware;
  final bool safe;
  final String? attack;

  const Device({
    required this.id,
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
    String? id,
    String? name,
    String? location,
    String? ip,
    String? mac,
    String? manufacturer,
    String? firmware,
    bool? safe,
    String? attack,
  }) {
    return Device(
      id: id ?? this.id,
      name: name ?? this.name,
      location: location ?? this.location,
      ip: ip ?? this.ip,
      mac: mac ?? this.mac,
      manufacturer: manufacturer ?? this.manufacturer,
      firmware: firmware ?? this.firmware,
      safe: safe ?? this.safe,
      attack: attack ?? this.attack,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'location': location,
        'ip': ip,
        'mac': mac,
        'manufacturer': manufacturer,
        'firmware': firmware,
      };

  factory Device.fromJson(Map<String, dynamic> json) => Device(
        id: json['id'] as String,
        name: json['name'] as String,
        location: json['location'] as String,
        ip: json['ip'] as String,
        mac: json['mac'] as String,
        manufacturer: json['manufacturer'] as String,
        firmware: json['firmware'] as String,
      );
}