import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class CloudRequestException implements Exception {
  final int status;
  CloudRequestException(this.status);

  @override
  String toString() =>
      'Cloud request failed (HTTP $status). '
      '${status == 401
          ? "Sign in again."
          : status == 429
          ? "Too many requests. Try again later."
          : "Check home access or command status before retrying."}';
}

class CloudApiService {
  static const storage = FlutterSecureStorage();
  static Map<String, dynamic>? savedAccount;
  static bool customer = false;
  static String origin = '';
  static String stagingToken = '';
  static String session = '';
  static String? householdId;
  static String? gatewayId;
  static String? role;
  static String? gatewayName;
  static int generation = 0;
  static Map<String, dynamic>? lastSnapshot;
  static String? lastCommandId;
  static String? lastCommandMac;
  static String? lastCommandAction;
  static bool commandUnconfirmed = false;
  static Map<String, dynamic> _savedCommands = {};
  static bool get enabled => origin.isNotEmpty;
  static bool get selected => session.isNotEmpty && gatewayId != null;

  static Future<void> initializeCustomer() async {
    disable();
    customer = true;
    const url = String.fromEnvironment(
      'CLOUD_API_URL',
      defaultValue: 'https://caughtin4k-1.onrender.com',
    );
    final uri = Uri.parse(url);
    if (uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw const FormatException('The application cloud origin is invalid.');
    }
    origin = url.replaceAll(RegExp(r'/+$'), '');
    final saved = await storage.read(key: 'customer_session');
    if (saved != null) {
      final data = jsonDecode(saved);
      if (data is! Map<String, dynamic> ||
          data['access_token'] is! String ||
          data['email'] is! String ||
          data['name'] is! String ||
          data['account_id'] is! String) {
        throw const FormatException(
          'Saved account session is invalid. Clear app data and sign in.',
        );
      }
      session = data['access_token'] as String;
      savedAccount = data;
      await _loadCommands();
    }
  }

  static Future<void> forgetSavedSession() async {
    savedAccount = null;
    if (customer) await storage.delete(key: 'customer_session');
  }

  static Future<void> rememberAccount(Map<String, dynamic> account) async {
    if (customer) {
      await storage.write(key: 'customer_session', value: jsonEncode(account));
    }
    savedAccount = account;
  }

  static String get _commandKey =>
      'customer_commands:${savedAccount?['account_id']}:$origin';

  static Future<void> _loadCommands() async {
    _savedCommands = {};
    if (!customer) return;
    final saved = await storage.read(key: _commandKey);
    if (saved == null) return;
    final commands = jsonDecode(saved);
    if (commands is! Map<String, dynamic>) {
      throw const FormatException(
        'Saved network command state is invalid. Contact support before retrying a network action.',
      );
    }
    _savedCommands = commands;
  }

  static Future<void> _persistCommand() async {
    if (!customer || savedAccount == null || gatewayId == null) return;
    _savedCommands[gatewayId!] = {
      'id': lastCommandId,
      'mac': lastCommandMac,
      'action': lastCommandAction,
      'household_id': householdId,
      'unconfirmed': commandUnconfirmed,
    };
    await storage.write(key: _commandKey, value: jsonEncode(_savedCommands));
  }

  static void clearSession() {
    generation++;
    session = '';
    householdId = gatewayId = role = gatewayName = null;
    lastSnapshot = null;
    lastCommandId = lastCommandMac = lastCommandAction = null;
    commandUnconfirmed = false;
    _savedCommands = {};
  }

  static void configure(String url, String token) {
    final uri = Uri.tryParse(url.trim());
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw const FormatException(
        'Use an HTTPS cloud origin without a path or credentials.',
      );
    }
    if (token.trim().length < 32 || RegExp(r'\s').hasMatch(token.trim())) {
      throw const FormatException(
        'Enter the current private staging access token.',
      );
    }
    clearSession();
    customer = false;
    origin = url.trim().replaceAll(RegExp(r'/+$'), '');
    stagingToken = token.trim();
  }

  static void disable() {
    clearSession();
    customer = false;
    savedAccount = null;
    origin = stagingToken = '';
  }

  static Future<Map<String, dynamic>> request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    int expected = 200,
  }) async {
    final version = generation;
    final request = http.Request(method, Uri.parse('$origin$path'))
      ..followRedirects = false
      ..headers.addAll({
        if (stagingToken.isNotEmpty) 'X-Cloud-Staging-Token': stagingToken,
        if (session.isNotEmpty) 'Authorization': 'Bearer $session',
        if (body != null) 'Content-Type': 'application/json',
      });
    if (body != null) request.body = jsonEncode(body);
    final client = http.Client();
    try {
      final response = await (() async {
        final stream = await client.send(request);
        return http.Response.fromStream(stream);
      })().timeout(const Duration(seconds: 60));
      if (version != generation) {
        throw Exception('Cloud session or gateway changed.');
      }
      if (response.statusCode != expected) {
        if (path == '/cloud/auth/signup' && response.statusCode == 409) {
          throw Exception(
            'An account with this email already exists. Sign in, or use Forgot password. To test isolation, use an email that has not been registered.',
          );
        }
        throw CloudRequestException(response.statusCode);
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Cloud returned an invalid response.');
      }
      return decoded;
    } finally {
      client.close();
    }
  }

  static Future<Map<String, dynamic>> login(
    String email,
    String password,
  ) async {
    final result = await request(
      'POST',
      '/cloud/auth/login',
      body: {'email': email, 'password': password},
    );
    final token = result['access_token'];
    if (token is! String ||
        !token.startsWith('cloud-v1.') ||
        result['email'] is! String ||
        result['name'] is! String ||
        (customer && result['account_id'] is! String)) {
      throw const FormatException('Cloud returned an invalid account session.');
    }
    clearSession();
    session = token;
    await rememberAccount(result);
    await _loadCommands();
    return {...result, 'success': true};
  }

  static Future<Map<String, dynamic>> signup(
    String name,
    String email,
    String password,
  ) async {
    final result = await request(
      'POST',
      '/cloud/auth/signup',
      expected: 201,
      body: {'name': name, 'email': email, 'password': password},
    );
    final token = result['access_token'];
    if (token is! String ||
        !token.startsWith('cloud-v1.') ||
        result['email'] is! String ||
        result['name'] is! String ||
        (customer && result['account_id'] is! String)) {
      throw const FormatException('Invalid account response.');
    }
    clearSession();
    session = token;
    await rememberAccount(result);
    await _loadCommands();
    return result;
  }

  static List<Map<String, dynamic>> rows(Object? value) {
    if (value is! List || value.any((row) => row is! Map<String, dynamic>)) {
      throw const FormatException('Cloud returned an invalid list.');
    }
    return value.cast<Map<String, dynamic>>();
  }

  static Future<List<Map<String, dynamic>>> gateways() async {
    final homes = rows(
      (await request('GET', '/cloud/households'))['households'],
    );
    final choices = <Map<String, dynamic>>[];
    for (final home in homes) {
      final id = home['household_id'];
      if (id is! String ||
          !{'owner', 'admin', 'member'}.contains(home['role'])) {
        throw const FormatException('Invalid household membership.');
      }
      final devices = rows(
        (await request('GET', '/cloud/households/$id/gateways'))['gateways'],
      );
      for (final gateway in devices) {
        if (gateway['revoked_at'] == null) {
          choices.add({
            ...gateway,
            'household_id': id,
            'household_name': home['name'],
            'role': home['role'],
          });
        }
      }
    }
    return choices;
  }

  static void select(Map<String, dynamic> gateway) {
    if (gateway['gateway_id'] is! String ||
        gateway['household_id'] is! String) {
      throw const FormatException('Invalid gateway selection.');
    }
    generation++;
    gatewayId = gateway['gateway_id'] as String;
    householdId = gateway['household_id'] as String;
    role = gateway['role'] as String;
    gatewayName = gateway['name'] as String? ?? 'Gateway';
    lastSnapshot = null;
    lastCommandId = lastCommandMac = lastCommandAction = null;
    commandUnconfirmed = false;
    final pending = _savedCommands[gatewayId];
    if (pending != null) {
      if (pending is! Map<String, dynamic> ||
          pending['household_id'] != householdId ||
          pending['id'] is! String ||
          !{
            'block',
            'unblock',
            'register',
            'remove',
            'train',
          }.contains(pending['action']) ||
          (pending['action'] == 'train'
              ? pending['mac'] != null
              : pending['mac'] is! String) ||
          pending['unconfirmed'] is! bool) {
        throw const FormatException(
          'Saved network command is invalid. Contact support before retrying.',
        );
      }
      lastCommandId = pending['id'] as String;
      lastCommandMac = pending['mac'] as String?;
      lastCommandAction = pending['action'] as String;
      commandUnconfirmed = pending['unconfirmed'] as bool;
    }
  }

  static String get gatewayPath {
    if (!selected) throw Exception('Select a cloud household gateway first.');
    return '/cloud/households/$householdId/gateways/$gatewayId';
  }

  static Future<Map<String, dynamic>> snapshot() async {
    final version = generation;
    final result = await request('GET', '$gatewayPath/snapshot');
    if (version != generation) throw Exception('Cloud selection changed.');
    if (result['gateway_id'] != gatewayId ||
        result['data_stale'] is! bool ||
        result['recent_contact'] is! bool) {
      throw const FormatException('Invalid cloud snapshot.');
    }
    if (result['snapshot_available'] != true) {
      throw Exception('No snapshot uploaded by this gateway yet.');
    }
    rows(result['devices']);
    rows(result['alerts']);
    if (result['model'] is! Map<String, dynamic>) {
      throw const FormatException('Invalid cloud model metadata.');
    }
    lastSnapshot = result;
    return result;
  }

  static String _uuid() {
    final random = Random.secure();
    final bytes = List.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  static Future<Map<String, dynamic>> control(
    String? mac,
    String action, {
    Duration pollInterval = const Duration(seconds: 3),
    Duration wait = const Duration(seconds: 150),
    String? deviceName,
    String? ipAddress,
  }) async {
    if (commandUnconfirmed) {
      throw Exception(
        'Check the previous command status before sending another action.',
      );
    }
    if (!{'owner', 'admin'}.contains(role)) {
      throw Exception(
        'Only household owners and admins can control the network.',
      );
    }
    if (!{'block', 'unblock', 'register', 'remove', 'train'}.contains(action) ||
        (action == 'train'
            ? mac != null
            : mac == null ||
                  !RegExp(r'^[0-9a-f]{2}(:[0-9a-f]{2}){5}$').hasMatch(mac))) {
      throw const FormatException('Invalid network control target.');
    }
    final fresh = await snapshot();
    if (action == 'train') {
      if (fresh['training_available'] != true) {
        throw Exception(
          'Federated training requires the Pi update. No command sent.',
        );
      }
      final model = fresh['model'];
      final federated = model is Map ? model['federated'] : null;
      final training = federated is Map ? federated['training'] : null;
      final checked = federated is Map
          ? DateTime.tryParse(federated['observed_at'] as String? ?? '')
          : null;
      if (checked == null ||
          DateTime.now().difference(checked).inSeconds > 30 ||
          checked.isAfter(DateTime.now()) ||
          training is! Map ||
          !{'idle', 'completed', 'failed'}.contains(training['state'])) {
        throw Exception(
          'Laptop training status is unavailable, stale, or already running. No command sent.',
        );
      }
    }
    if ({'register', 'remove'}.contains(action) &&
        fresh['device_management_available'] != true) {
      throw Exception(
        'Device management requires the Pi update. No command sent.',
      );
    }
    final observed = DateTime.tryParse(fresh['observed_at'] as String? ?? '');
    if (fresh['data_stale'] == true ||
        fresh['recent_contact'] != true ||
        observed == null ||
        DateTime.now().difference(observed).inSeconds > 90) {
      throw Exception('Gateway is offline or data is stale. No command sent.');
    }
    final path = '$gatewayPath/commands';
    final id = _uuid();
    final version = generation;
    lastCommandId = id;
    lastCommandMac = mac;
    lastCommandAction = action;
    commandUnconfirmed = true;
    try {
      await _persistCommand();
      if (version != generation) {
        throw Exception('Account or home changed before submission.');
      }
      Map<String, dynamic> submitted;
      try {
        submitted = await request(
          'POST',
          path,
          expected: 202,
          body: {
            'command_id': id,
            'action': action,
            'mac': mac,
            if (action == 'register') 'device_name': deviceName,
            if (action == 'register') 'ip_address': ipAddress ?? '',
          },
        );
      } on CloudRequestException catch (error) {
        if ({400, 401, 403, 404, 409, 422}.contains(error.status) &&
            version == generation) {
          commandUnconfirmed = false;
          await _persistCommand();
        }
        rethrow;
      }
      if (submitted['id'] != id ||
          submitted['gateway_id'] != gatewayId ||
          submitted['mac'] != mac ||
          submitted['action'] != action) {
        throw const FormatException('Invalid queued command acknowledgement.');
      }
      final timer = Stopwatch()..start();
      while (timer.elapsed < wait) {
        if (version != generation) throw Exception('Cloud session changed.');
        final result = await request('GET', '$path/$id');
        if (result['id'] != id || result['gateway_id'] != gatewayId) {
          throw const FormatException('Invalid command identity.');
        }
        final status = result['status'];
        if (status == 'succeeded' && result['result_code'] == 'applied') {
          commandUnconfirmed = false;
          await _persistCommand();
          return {
            'success': true,
            'command_id': id,
            'completed_at': result['completed_at'],
            if (action == 'train') 'message': 'Laptop coordinator accepted real federated training. Completion is reported separately.',
          };
        }
        if (status != 'queued' && status != 'delivered') {
          if ({'failed', 'expired', 'cancelled'}.contains(status)) {
            commandUnconfirmed = false;
            await _persistCommand();
          }
          throw Exception('Network action not confirmed: $status.');
        }
        await Future<void>.delayed(pollInterval);
      }
      throw TimeoutException('Execution not confirmed before timeout.');
    } catch (error) {
      throw Exception(
        '$error Command ID: $id. Do not retry blindly; check command status and fresh device state.',
      );
    }
  }

  static Future<Map<String, dynamic>> commandStatus() async {
    final id = lastCommandId;
    if (id == null) throw Exception('No command to check in this session.');
    final result = await request('GET', '$gatewayPath/commands/$id');
    if (result['id'] != id ||
        result['gateway_id'] != gatewayId ||
        !{
          'queued',
          'delivered',
          'succeeded',
          'failed',
          'expired',
          'cancelled',
          'unknown',
        }.contains(result['status']) ||
        (result['status'] == 'succeeded' &&
            result['result_code'] != 'applied')) {
      throw const FormatException('Invalid command status.');
    }
    if ({
      'succeeded',
      'failed',
      'expired',
      'cancelled',
    }.contains(result['status'])) {
      commandUnconfirmed = false;
      await _persistCommand();
    }
    return result;
  }
}
