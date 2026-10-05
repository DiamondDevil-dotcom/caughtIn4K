import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../providers/activity_provider.dart';
import '../providers/alert_provider.dart';
import '../providers/router_device_provider.dart';
import 'auth_screen.dart';
import 'navigation_screen.dart';
import 'cloud_gateway_screen.dart';
import '../services/cloud_api_service.dart';
import 'email_verification_screen.dart';

class AccountGate extends StatelessWidget {
  const AccountGate({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthProvider>();
    if (!auth.ready) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!auth.isSignedIn) return const AuthScreen();
    if (CloudApiService.enabled && !auth.emailVerified) {
      return const EmailVerificationScreen();
    }
    if (CloudApiService.enabled && !CloudApiService.selected) {
      return const CloudGatewayScreen();
    }
    if (auth.passwordFallbackForLaunch) return const NavigationScreen();
    return BiometricGate(key: ValueKey(auth.email));
  }
}

class BiometricGate extends StatefulWidget {
  const BiometricGate({super.key});

  @override
  State<BiometricGate> createState() => _BiometricGateState();
}

class _BiometricGateState extends State<BiometricGate>
    with WidgetsBindingObserver {
  final LocalAuthentication _localAuth = LocalAuthentication();
  bool _attempting = false;
  bool _unlocked = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _authenticate());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused && _unlocked && !_attempting) {
      setState(() {
        _unlocked = false;
        _message = null;
      });
    } else if (state == AppLifecycleState.resumed &&
        !_unlocked &&
        !_attempting) {
      _authenticate();
    }
  }

  Future<void> _authenticate() async {
    if (_attempting || _unlocked) return;
    setState(() {
      _attempting = true;
      _message = null;
    });

    try {
      final supported = await _localAuth.isDeviceSupported();
      final canCheck = await _localAuth.canCheckBiometrics;
      final biometrics = await _localAuth.getAvailableBiometrics();
      if (!supported || !canCheck || biometrics.isEmpty) {
        if (mounted) {
          setState(() => _message =
              'No fingerprint is enrolled on this device. Sign in with your account password to continue.');
        }
        return;
      }

      final authenticated = await _localAuth.authenticate(
        localizedReason: 'Use your fingerprint to unlock caughtIn4K',
        biometricOnly: true,
        persistAcrossBackgrounding: true,
      );
      if (!mounted) return;
      setState(() {
        _unlocked = authenticated;
        _message = authenticated
            ? null
            : 'Fingerprint not verified. Try again or use your account password.';
      });
    } on PlatformException catch (error) {
      if (mounted) {
        setState(() => _message =
            'Fingerprint unlock is unavailable (${error.code}). Use your account password to continue.');
      }
    } catch (_) {
      if (mounted) {
        setState(() => _message =
            'Could not start fingerprint unlock. Use your account password to continue.');
      }
    } finally {
      if (mounted) setState(() => _attempting = false);
    }
  }

  Future<void> _usePassword() async {
    context.read<RouterDeviceProvider>().clearCachedData();
    context.read<ActivityProvider>().clearCachedData();
    context.read<AlertProvider>().clearCachedData();
    await context
        .read<AuthProvider>()
        .signOut(preservePasswordFallback: true);
  }

  @override
  Widget build(BuildContext context) {
    if (_unlocked) return const NavigationScreen();

    final theme = Theme.of(context);
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF071522), Color(0xFF0B1220), Color(0xFF101F2A)],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Padding(
                padding: const EdgeInsets.all(28),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 88,
                      height: 88,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: theme.colorScheme.primary.withValues(alpha: 0.12),
                        border: Border.all(
                          color: theme.colorScheme.primary.withValues(alpha: 0.38),
                        ),
                      ),
                      child: Icon(
                        Icons.fingerprint_rounded,
                        size: 48,
                        color: theme.colorScheme.primary,
                      ),
                    ),
                    const SizedBox(height: 26),
                    Text(
                      'Unlock caughtIn4K',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.spaceGrotesk(
                        fontSize: 28,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Verify your fingerprint to open your security dashboard.',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyMedium,
                    ),
                    if (_message != null) ...[
                      const SizedBox(height: 22),
                      Text(
                        _message!,
                        textAlign: TextAlign.center,
                        style: TextStyle(color: theme.colorScheme.error),
                      ),
                    ],
                    const SizedBox(height: 28),
                    FilledButton.icon(
                      onPressed: _attempting ? null : _authenticate,
                      icon: _attempting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.fingerprint_rounded),
                      label: Text(_attempting ? 'Waiting for fingerprint' : 'Try fingerprint again'),
                    ),
                    TextButton(
                      onPressed: _attempting ? null : _usePassword,
                      child: const Text('Use account password'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}