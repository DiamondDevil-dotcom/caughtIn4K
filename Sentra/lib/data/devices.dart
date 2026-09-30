import '../models/device.dart';

final List<Device> devices = [
  const Device(
    id: "amazon-alexa",
    name: "Amazon Alexa",
    location: "Living Room",
    ip: "192.168.0.101",
    mac: "A4:CF:12:45:21:11",
    manufacturer: "Amazon",
    firmware: "v3.2.1",
  ),
  const Device(
    id: "security-camera",
    name: "Security Camera",
    location: "Front Door",
    ip: "192.168.0.102",
    mac: "B8:22:41:90:12:AA",
    manufacturer: "Hikvision",
    firmware: "v5.1.4",
  ),
  const Device(
    id: "dvr",
    name: "DVR",
    location: "Office",
    ip: "192.168.0.103",
    mac: "D0:33:98:12:55:CC",
    manufacturer: "CP Plus",
    firmware: "v2.7.8",
  ),
];