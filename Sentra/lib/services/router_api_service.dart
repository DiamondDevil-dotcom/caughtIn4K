import 'dart:convert';
import 'package:http/http.dart' as http;

/// Talks directly to the router-mode IDS agent running on the Raspberry Pi
/// (see router_ids_agent.py), which now hosts the model and blocking logic.
class RouterApiService {
  static const String baseUrl = String.fromEnvironment(
    "ROUTER_API_URL",
    defaultValue: "http://10.170.97.102:8001",
  );

  static Future<List<Map<String, dynamic>>> devices() async {
    final response = await http.get(Uri.parse("$baseUrl/devices"));

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return List<Map<String, dynamic>>.from(body["devices"] ?? []);
    }

    throw Exception(
      "Router device list failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> federatedStatus() async {
    final response = await http.get(Uri.parse("$baseUrl/federated-status"));
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception(
      "Federated model status failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> startFederatedTraining() async {
    final response = await http.post(Uri.parse("$baseUrl/federated/start"));
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode == 200 && body["success"] == true) return body;
    throw Exception(body["detail"] ?? body["message"] ?? "Could not start federated training.");
  }

  static Future<Map<String, dynamic>> registerDevice({
    required String name,
    required String mac,
    required String ipAddress,
  }) async {
    final response = await http.post(
      Uri.parse("$baseUrl/devices/register"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "name": name,
        "mac": mac,
        "ip_address": ipAddress.trim(),
      }),
    );
    if (response.statusCode != 200) {
      throw Exception("Device registration failed: ${response.body}");
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  static Future<void> deleteDevice(String mac) async {
    final response = await http.delete(Uri.parse("$baseUrl/devices/$mac"));
    if (response.statusCode != 200) {
      throw Exception("Device deletion failed: ${response.body}");
    }
  }

  static Future<Map<String, dynamic>> block(String mac) async {
    final response = await http.post(Uri.parse("$baseUrl/devices/$mac/block"));

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Block request failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> unblock(String mac) async {
    final response = await http.post(Uri.parse("$baseUrl/devices/$mac/unblock"));

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Unblock request failed (${response.statusCode}): ${response.body}",
    );
  }

  /// Demonstration-only: posts a labeled feature row so the router agent
  /// classifies it exactly like real sniffed traffic from that device.
  static Future<Map<String, dynamic>> sendTelemetry({
    required String device,
    required String mac,
    String? ipAddress,
    required List<double> features,
  }) async {
    final response = await http.post(
      Uri.parse("$baseUrl/telemetry"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "device": device,
        "mac": mac,
        if (ipAddress != null && ipAddress.trim().isNotEmpty)
          "ip_address": ipAddress.trim(),
        "features": features,
      }),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Telemetry request failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<List<Map<String, dynamic>>> events({int limit = 50}) async {
    final response = await http.get(Uri.parse("$baseUrl/events?limit=$limit"));

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return List<Map<String, dynamic>>.from(body["events"] ?? []);
    }

    throw Exception(
      "Event history failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> signUp({
    required String name,
    required String email,
    required String password,
  }) async {
    final response = await http.post(
      Uri.parse("$baseUrl/auth/signup"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"name": name, "email": email, "password": password}),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Sign up failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> logIn({
    required String email,
    required String password,
  }) async {
    final response = await http.post(
      Uri.parse("$baseUrl/auth/login"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"email": email, "password": password}),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Sign in failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> changePassword({
    required String email,
    required String currentPassword,
    required String newPassword,
  }) async {
    final response = await http.post(
      Uri.parse("$baseUrl/auth/change-password"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "email": email,
        "current_password": currentPassword,
        "new_password": newPassword,
      }),
    );
    return jsonDecode(response.body);
  }

  static Future<Map<String, dynamic>> requestPasswordReset(String email) async {
    final response = await http.post(
      Uri.parse("$baseUrl/auth/request-password-reset"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"email": email}),
    );
    return jsonDecode(response.body);
  }

  static Future<Map<String, dynamic>> resetPassword({
    required String email,
    required String token,
    required String newPassword,
  }) async {
    final response = await http.post(
      Uri.parse("$baseUrl/auth/reset-password"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "email": email,
        "token": token,
        "new_password": newPassword,
      }),
    );
    return jsonDecode(response.body);
  }
}
