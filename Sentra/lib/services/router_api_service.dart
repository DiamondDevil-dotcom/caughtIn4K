import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'cloud_api_service.dart';

/// Uses Render as the shared gateway to the Pi and laptop coordinator.
class RouterApiService {
  static const String _defaultUrl = "https://caughtin4k.onrender.com";
  static String _customBaseUrl = "";
  static String _sessionToken = "";
  static int _sessionGeneration = 0;
  static int get sessionGeneration => _sessionGeneration + CloudApiService.generation;
  static bool get cloudMode => CloudApiService.enabled;
  static bool get hasSession => cloudMode ? CloudApiService.selected : _sessionToken.isNotEmpty;

  static Future<void> clearSession() async {
    _sessionGeneration++;
    CloudApiService.clearSession();
    await CloudApiService.forgetSavedSession();
    _sessionToken = "";
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove("gateway_session_token");
  }

  static Future<void> _saveSession(Map<String, dynamic> body) async {
    if (body["success"] != true) return;
    final token = body["access_token"];
    if (token is! String || token.isEmpty) {
      throw Exception("The server does not support authenticated gateway sessions. Update the backend.");
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString("gateway_session_token", token);
    _sessionToken = token;
    _sessionGeneration++;
  }

  static String get baseUrl {
    if (cloudMode) return CloudApiService.origin;
    if (_customBaseUrl.isNotEmpty) return _customBaseUrl;
    const envUrl = String.fromEnvironment("ROUTER_API_URL", defaultValue: "");
    if (envUrl.isNotEmpty) return envUrl;
    return _defaultUrl;
  }

  static Future<void> init({bool legacy = false}) async {
    CloudApiService.disable();
    final prefs = await SharedPreferences.getInstance();
    _customBaseUrl = prefs.getString("custom_router_api_url") ?? "";
    _sessionToken = prefs.getString("gateway_session_token") ?? "";
    if (!legacy) await CloudApiService.initializeCustomer();
  }

  static Future<void> setBaseUrl(String url) async {
    final normalized = url.trim().replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(normalized);
    if (uri == null || !uri.hasAuthority || uri.host.isEmpty ||
        (uri.scheme != 'https' && uri.scheme != 'http')) {
      throw const FormatException("Enter a valid HTTP or HTTPS gateway URL.");
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString("custom_router_api_url", normalized);
    if (normalized != baseUrl) await clearSession();
    _customBaseUrl = normalized;
  }

  static Map<String, String> _headers([Map<String, String>? extra]) {
    final Map<String, String> h = {
      "ngrok-skip-browser-warning": "true",
      "User-Agent": "caughtIn4K-mobile/1.0",
      if (_sessionToken.isNotEmpty) "Authorization": "Bearer $_sessionToken",
    };
    if (extra != null) {
      h.addAll(extra);
    }
    return h;
  }

  static Future<List<Map<String, dynamic>>> devices() async {
    if (cloudMode) {
      return CloudApiService.rows((await CloudApiService.snapshot())['devices']);
    }
    final response = await http.get(
      Uri.parse("$baseUrl/devices"),
      headers: _headers(),
    ).timeout(const Duration(seconds: 60));

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return List<Map<String, dynamic>>.from(body["devices"] ?? []);
    }

    throw Exception(
      "Router device list failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> federatedStatus() async {
    if (cloudMode) {
      return {'cloud_model': (await CloudApiService.snapshot())['model']};
    }
    final response = await http.get(
      Uri.parse("$baseUrl/federated-status"),
      headers: _headers(),
    ).timeout(const Duration(seconds: 60));
    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw Exception(
      "Federated model status failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> startFederatedTraining() async {
    _requireLive('Federated training controls');
    final response = await http.post(
      Uri.parse("$baseUrl/federated/start"),
      headers: _headers({"Content-Type": "application/json"}),
    ).timeout(const Duration(seconds: 60));
    final body = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode == 200 && body["success"] == true) return body;
    throw Exception(body["detail"] ?? body["message"] ?? "Could not start federated training.");
  }

  static Future<Map<String, dynamic>> registerDevice({
    required String name,
    required String mac,
    required String ipAddress,
  }) async {
    _requireLive('Device registration');
    final response = await http.post(
      Uri.parse("$baseUrl/devices/register"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({
        "name": name,
        "mac": mac,
        "ip_address": ipAddress.trim(),
      }),
    ).timeout(const Duration(seconds: 60));
    if (response.statusCode != 200) {
      throw Exception("Device registration failed: ${response.body}");
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  static Future<void> deleteDevice(String mac) async {
    _requireLive('Device removal');
    final response = await http.delete(
      Uri.parse("$baseUrl/devices/$mac"),
      headers: _headers(),
    ).timeout(const Duration(seconds: 60));
    if (response.statusCode != 200) {
      throw Exception("Device deletion failed: ${response.body}");
    }
  }

  static Future<Map<String, dynamic>> block(String mac) async {
    if (cloudMode) return CloudApiService.control(mac, 'block');
    final response = await http.post(
      Uri.parse("$baseUrl/devices/$mac/block"),
      headers: _headers(),
    ).timeout(const Duration(seconds: 60));

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (body["success"] != true) {
        throw Exception(body["detail"] ?? "Device blocking failed.");
      }
      return body;
    }

    throw Exception(
      "Block request failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> unblock(String mac) async {
    if (cloudMode) return CloudApiService.control(mac, 'unblock');
    final response = await http.post(
      Uri.parse("$baseUrl/devices/$mac/unblock"),
      headers: _headers(),
    ).timeout(const Duration(seconds: 60));

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (body["success"] != true) {
        throw Exception(body["detail"] ?? "Device unblocking failed.");
      }
      return body;
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
    _requireLive('Demo telemetry');
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
    ).timeout(const Duration(seconds: 60));

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Telemetry request failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<List<Map<String, dynamic>>> events({int limit = 50}) async {
    if (cloudMode) {
      return CloudApiService.rows((await CloudApiService.snapshot())['alerts'])
          .take(limit).map((event) => {
            ...event,
            'device': event['mac'],
            'prediction': event['status'],
          }).toList();
    }
    final response = await http.get(
      Uri.parse("$baseUrl/events?limit=$limit"),
      headers: _headers(),
    ).timeout(const Duration(seconds: 60));

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
    required String accessCode,
  }) async {
    if (cloudMode) return CloudApiService.signup(name, email, password);
    final response = await http.post(
      Uri.parse("$baseUrl/auth/signup"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({
        "name": name,
        "email": email,
        "password": password,
        "access_code": accessCode,
      }),
    ).timeout(const Duration(seconds: 60));

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      await _saveSession(body);
      return body;
    }

    throw Exception(
      "Sign up failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> logIn({
    required String email,
    required String password,
    String accessCode = "",
  }) async {
    if (cloudMode) return CloudApiService.login(email, password);
    final response = await http.post(
      Uri.parse("$baseUrl/auth/login"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({
        "email": email,
        "password": password,
        if (accessCode.trim().isNotEmpty) "access_code": accessCode.trim(),
      }),
    ).timeout(const Duration(seconds: 60));

    if (response.statusCode == 200) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      await _saveSession(body);
      return body;
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
    if (cloudMode) {
      return CloudApiService.request('POST', '/cloud/auth/change-password',
          body: {'current_password': currentPassword, 'new_password': newPassword});
    }
    final response = await http.post(
      Uri.parse("$baseUrl/auth/change-password"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({
        "email": email,
        "current_password": currentPassword,
        "new_password": newPassword,
      }),
    ).timeout(const Duration(seconds: 60));
    return _accountResponse(response);
  }

  static Future<Map<String, dynamic>> requestPasswordReset(String email) async {
    if (cloudMode) return CloudApiService.request('POST', '/cloud/auth/request-password-reset', body: {'email': email});
    final response = await http.post(
      Uri.parse("$baseUrl/auth/request-password-reset"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({"email": email}),
    ).timeout(const Duration(seconds: 60));
    return _accountResponse(response);
  }

  static Future<Map<String, dynamic>> resetPassword({
    required String email,
    required String token,
    required String newPassword,
  }) async {
    if (cloudMode) {
      return CloudApiService.request('POST', '/cloud/auth/reset-password',
          body: {'email': email, 'token': token, 'new_password': newPassword});
    }
    final response = await http.post(
      Uri.parse("$baseUrl/auth/reset-password"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({
        "email": email,
        "token": token,
        "new_password": newPassword,
      }),
    ).timeout(const Duration(seconds: 60));
    return _accountResponse(response);
  }

  static Future<Map<String, dynamic>> claimGateway(String pairingCode) async {
    _requireLive('Gateway pairing');
    final response = await http.post(
      Uri.parse("$baseUrl/gateway/claim"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({"pairing_code": pairingCode}),
    ).timeout(const Duration(seconds: 60));
    return _accountResponse(response);
  }

  static Future<Map<String, dynamic>> createHouseholdInvite({
    required String email,
    required String role,
  }) async {
    if (cloudMode) {
      return CloudApiService.request('POST', '/cloud/households/${CloudApiService.householdId}/invites',
          expected: 201, body: {'email': email, 'role': role});
    }
    final response = await http.post(
      Uri.parse("$baseUrl/household/invites"),
      headers: _headers({"Content-Type": "application/json"}),
      body: jsonEncode({"email": email, "role": role}),
    ).timeout(const Duration(seconds: 60));
    return _accountResponse(response);
  }

  static Future<String?> householdRole() async {
    if (cloudMode) return CloudApiService.role;
    final response = await http.get(
      Uri.parse("$baseUrl/household/role"),
      headers: _headers(),
    ).timeout(const Duration(seconds: 60));
    final body = _accountResponse(response);
    return body["role"] as String?;
  }

  static Map<String, dynamic> _accountResponse(http.Response response) {
    if (response.statusCode != 200) {
      throw Exception("Account request failed (${response.statusCode}): ${response.body}");
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  static void _requireLive(String feature) {
    if (cloudMode) throw Exception('$feature is not available in cloud staging yet. Use live mode.');
  }
}
