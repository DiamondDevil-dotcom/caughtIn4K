import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  static const String baseUrl = String.fromEnvironment(
    "API_BASE_URL",
    defaultValue: "http://10.121.31.102:8000",
  );

  static Future<Map<String, dynamic>> predict(
      List<double> features) async {
    final response = await http.post(
      Uri.parse("$baseUrl/predict"),
      headers: {
        "Content-Type": "application/json",
      },
      body: jsonEncode({
        "features": features,
      }),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Prediction failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> latestTraffic() async {
    final response = await http.get(Uri.parse("$baseUrl/traffic/latest"));

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Traffic request failed (${response.statusCode}): ${response.body}",
    );
  }

  static Future<Map<String, dynamic>> scanNetwork(
      List<String> deviceNames) async {
    final response = await http.post(
      Uri.parse("$baseUrl/scan"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"devices": deviceNames}),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }

    throw Exception(
      "Network scan failed (${response.statusCode}): ${response.body}",
    );
  }
}