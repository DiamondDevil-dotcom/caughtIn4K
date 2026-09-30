import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Talks directly to the router-mode IDS agent running on the Raspberry Pi
/// or via the Cloud/Ngrok gateway.
class RouterApiService {
  static const String _defaultUrl = "https://stimuli-clubhouse-frozen.ngrok-free.dev";
  static String _customBaseUrl = "";

  static String get baseUrl {
    if (_customBaseUrl.isNotEmpty) return _customBaseUrl;
    const envUrl = String.fromEnvironment("ROUTER_API_URL", defaultValue: "");
    if (envUrl.isNotEmpty) return envUrl;
    return _defaultUrl;
  }

  static Future<void> init() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _customBaseUrl = prefs.getString("custom_router_api_url") ?? "";
    } catch (_) {}
  }

  static Future<void> setBaseUrl(String url) async {
    _customBaseUrl = url.trim().replaceAll(RegExp(r'/+$'), '');
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString("custom_router_api_url", _customBaseUrl);
    } catch (_) {}
  }

  static Map<String, String> _headers([Map<String, String>? extra]) {
    final Map<String, String> h = {
      "ngrok-skip-browser-warning": "true",
      "User-Agent": "caughtIn4K-mobile/1.0",
    };
    if (extra != null) {
      h.addAll(extra);
    }
    return h;
  }

  static Future<List<Map<String, dynamic>>> devices() async {
    final response = await http.get(
      Uri.parse("$baseUrl/devices"),
      headers: _headers(),
    );

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return List<Map<String, dynamic>>.from(body["devices"] ?? []);
    }

    throw Exception(
      "Router device list failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> federatedStatus() async {
    final response = await http.get(
      Uri.parse("$baseUrl/federated-status"),
      headers: _headers(),
    );
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception(
      "Federated model status failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> startFederatedTraining() async {
    final response = await http.post(
      Uri.parse("$baseUrl/federated/start"),
      headers: _headers({"Content-Type": "application/json"}),
    );
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
      headers: _headers({"Content-Type": "application/json"}),
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
    final response = await http.delete(
      Uri.parse("$baseUrl/devices/$mac"),
      headers: _headers(),
    );
    if (response.statusCode != 200) {
      throw Exception("Device deletion failed: ${response.body}");
    }
  }

  static Future<Map<String, dynamic>> block(String mac) async {
    final response = await http.post(
      Uri.parse("$baseUrl/devices/$mac/block"),
      headers: _headers(),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Block request failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> unblock(String mac) async {
    final response = await http.post(
      Uri.parse("$baseUrl/devices/$mac/unblock"),
      headers: _headers(),
    );

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
      headers: _headers({"Content-Type": "application/json"}),
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
    final response = await http.get(
      Uri.parse("$baseUrl/events?limit=$limit"),
      headers: _headers(),
    );

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
      headers: _headers({"Content-Type": "application/json"}),
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
      headers: _headers({"Content-Type": "application/json"}),
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
      headers: _headers({"Content-Type": "application/json"}),
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
      headers: _headers({"Content-Type": "application/json"}),
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
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({
        "email": email,
        "token": token,
        "new_password": newPassword,
      }),
    );
    return jsonDecode(response.body);
  }
}
