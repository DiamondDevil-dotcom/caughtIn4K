import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/router_api_service.dart';
import '../services/cloud_api_service.dart';

/// Customer accounts use the shared service; sessions use secure phone storage.
class AuthProvider extends ChangeNotifier {
  static const _sessionKey = 'session_account';
  static const _signedInKey = 'signed_in';

  bool _ready = false;
  bool _passwordFallbackForLaunch = false;
  String? _email;
  String? _name;
  String? _householdRole;
  bool emailVerified = false;
  bool choosingHome = false;

  bool get ready => _ready;
  bool get isSignedIn => _email != null;
  bool get passwordFallbackForLaunch => _passwordFallbackForLaunch;
  String get name => _name ?? 'Security owner';
  String get email => _email ?? '';
  String? get householdRole => RouterApiService.cloudMode ? CloudApiService.role : _householdRole;

  void selectCloudGateway(Map<String, dynamic> gateway) {
    CloudApiService.select(gateway);
    choosingHome = false;
    notifyListeners();
  }

  void chooseAnotherHome() {
    choosingHome = true;
    CloudApiService.generation++;
    CloudApiService.gatewayId = null;
    CloudApiService.householdId = null;
    CloudApiService.role = null;
    CloudApiService.lastSnapshot = null;
    notifyListeners();
  }

  Future<void> refreshAccount() async {
    final result = await CloudApiService.request('GET', '/cloud/auth/me');
    emailVerified = result['email_verified'] == true;
    await CloudApiService.rememberAccount({...result, 'access_token': CloudApiService.session});
    notifyListeners();
  }

  Future<void> load() async {
    if (RouterApiService.cloudMode) {
      final account = CloudApiService.savedAccount;
      if (account != null && CloudApiService.session.isNotEmpty) {
        _email = account['email'] as String;
        _name = account['name'] as String;
        emailVerified = account['email_verified'] == true;
      }
      _ready = true;
      notifyListeners();
      return;
    }
    final preferences = await SharedPreferences.getInstance();
    final session = preferences.getStringList(_sessionKey);
    if (preferences.getBool(_signedInKey) == true &&
        session != null &&
        session.length >= 2 &&
        RouterApiService.hasSession) {
      _email = session[0];
      _name = session[1];
      _householdRole = session.length > 2 && session[2].isNotEmpty ? session[2] : null;
    }
    _ready = true;
    notifyListeners();
  }

  Future<void> _persistSession(String email, String name, String? role) async {
    if (RouterApiService.cloudMode) return;
    final preferences = await SharedPreferences.getInstance();
    await preferences.setStringList(_sessionKey, [email, name, role ?? '']);
    await preferences.setBool(_signedInKey, true);
  }

  Future<String?> signIn(
    String email,
    String password, {
    String accessCode = '',
  }) async {
    try {
      final result = await RouterApiService.logIn(
        email: email.trim(),
        password: password,
        accessCode: accessCode,
      );
      if (result['success'] != true) {
        return result['error'] as String? ?? 'Sign in failed.';
      }
      _email = result['email'] as String;
      _name = result['name'] as String;
      _householdRole = result['household_role'] as String?;
      emailVerified = result['email_verified'] == true;
      _passwordFallbackForLaunch = false;
      choosingHome = false;
      await _persistSession(_email!, _name!, _householdRole);
      notifyListeners();
      return null;
    } catch (error) {
      return 'Sign in failed: $error';
    }
  }

  Future<String?> createAccount({
    required String name,
    required String email,
    required String password,
    required String accessCode,
  }) async {
    try {
      final result = await RouterApiService.signUp(
        name: name.trim(),
        email: email.trim(),
        password: password,
        accessCode: accessCode.trim(),
      );
      if (result['success'] != true) {
        return result['error'] as String? ?? 'Could not create account.';
      }
      _email = result['email'] as String;
      _name = result['name'] as String;
      _householdRole = result['household_role'] as String?;
      emailVerified = result['email_verified'] == true;
      _passwordFallbackForLaunch = false;
      choosingHome = false;
      await _persistSession(_email!, _name!, _householdRole);
      notifyListeners();
      return null;
    } catch (error) {
      return 'Could not create account: $error';
    }
  }

  Future<void> signOut({bool preservePasswordFallback = false}) async {
    await RouterApiService.clearSession();
    final preferences = await SharedPreferences.getInstance();
    await preferences.setBool(_signedInKey, false);
    _passwordFallbackForLaunch = preservePasswordFallback;
    _email = null;
    _name = null;
    _householdRole = null;
    emailVerified = false;
    choosingHome = false;
    notifyListeners();
  }

  Future<String?> claimGateway(String pairingCode) async {
    try {
      final result = await RouterApiService.claimGateway(pairingCode.trim());
      _householdRole = result['household_role'] as String?;
      if (_email != null && _name != null) {
        await _persistSession(_email!, _name!, _householdRole);
      }
      notifyListeners();
      return null;
    } catch (error) {
      return error.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
    }
  }

  Future<String?> changePassword(String currentPassword, String newPassword) async {
    try {
      final result = await RouterApiService.changePassword(
        email: email,
        currentPassword: currentPassword,
        newPassword: newPassword,
      );
      return result['success'] == true ? null : result['error'] as String? ?? 'Password change failed.';
    } catch (error) {
      return 'Could not change your password: $error';
    }
  }
}
