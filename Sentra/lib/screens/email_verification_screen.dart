import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../services/cloud_api_service.dart';

class EmailVerificationScreen extends StatefulWidget {
  const EmailVerificationScreen({super.key});
  @override
  State<EmailVerificationScreen> createState() =>
      _EmailVerificationScreenState();
}

class _EmailVerificationScreenState extends State<EmailVerificationScreen> {
  final code = TextEditingController();
  bool busy = false;
  String? message;
  @override
  void dispose() {
    code.dispose();
    super.dispose();
  }

  Future<void> run(bool send) async {
    setState(() {
      busy = true;
      message = null;
    });
    try {
      final result = await CloudApiService.request(
        'POST',
        send ? '/cloud/auth/request-verification' : '/cloud/auth/verify-email',
        body: send ? null : {'token': code.text.trim()},
      );
      if (!mounted) return;
      if (!send) await context.read<AuthProvider>().refreshAccount();
      if (mounted) {
        setState(
          () => message = result['message'] as String? ?? 'Email verified.',
        );
      }
    } catch (error) {
      if (mounted) setState(() => message = '$error');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Verify your email')),
    body: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          Text(
            'Verify ${context.watch<AuthProvider>().email} before pairing or accessing a home.',
          ),
          TextField(
            controller: code,
            decoration: const InputDecoration(
              labelText: 'Email verification code',
            ),
          ),
          if (message != null) Text(message!),
          TextButton(
            onPressed: busy ? null : () => run(true),
            child: const Text('Send verification code'),
          ),
          FilledButton(
            onPressed: busy ? null : () => run(false),
            child: Text(busy ? 'Please wait...' : 'Verify email'),
          ),
          TextButton(
            onPressed: busy
                ? null
                : () => context.read<AuthProvider>().signOut(),
            child: const Text('Sign out'),
          ),
        ],
      ),
    ),
  );
}
