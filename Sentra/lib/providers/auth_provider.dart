import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/router_api_service.dart';

/// Accounts are stored in the router agent's SQLite database (see
/// storage.py), not just on this phone. SharedPreferences only caches the
/// signed-in session locally so the app can auto-resume without a password.
class AuthProvider extends ChangeNotifier {
  static const _sessionKey = 'session_account';
  static const _signedInKey = 'signed_in';

  bool _ready = false;
  bool _passwordFallbackForLaunch = false;
  String? _email;
  String? _name;
  String? _householdRole;

  bool get ready => _ready;
  bool get isSignedIn => _email != null;
  bool get passwordFallbackForLaunch => _passwordFallbackForLaunch;
  String get name => _name ?? 'Security owner';
  String get email => _email ?? '';
  String? get householdRole => _householdRole;

  Future<void> load() async {
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
      _passwordFallbackForLaunch = false;
      await _persistSession(_email!, _name!, _householdRole);
      notifyListeners();
      return null;
    } catch (error) {
      return 'Could not reach the router agent: $error';
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
      _passwordFallbackForLaunch = false;
      await _persistSession(_email!, _name!, _householdRole);
      notifyListeners();
      return null;
    } catch (error) {
      return 'Could not reach the router agent: $error';
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
      return 'Could not reach the router agent: $error';
    }
  }
}
