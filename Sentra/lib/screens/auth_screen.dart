import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import '../services/router_api_service.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _accessCodeController = TextEditingController();
  bool _creating = false;
  bool _submitting = false;

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _accessCodeController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _submitting = true);
    final auth = context.read<AuthProvider>();
    final error = _creating
        ? await auth.createAccount(
            name: _nameController.text,
            email: _emailController.text,
            password: _passwordController.text,
            accessCode: _accessCodeController.text,
          )
        : await auth.signIn(
            _emailController.text,
            _passwordController.text,
            accessCode: _accessCodeController.text,
          );
    if (!mounted) return;
    setState(() => _submitting = false);
    if (error != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: ListView(
              padding: const EdgeInsets.all(28),
              children: [
                const SizedBox(height: 48),
                Icon(Icons.shield_moon_rounded, size: 58, color: theme.colorScheme.primary),
                const SizedBox(height: 20),
                Text('caughtIn4K', textAlign: TextAlign.center, style: theme.textTheme.headlineMedium),
                const SizedBox(height: 8),
                Text(
                  _creating ? 'Create your secure home account' : 'Sign in to your security dashboard',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium,
                ),
                const SizedBox(height: 34),
                Form(
                  key: _formKey,
                  child: Column(
                    children: [
                      if (_creating) ...[
                        TextFormField(
                          controller: _nameController,
                          decoration: const InputDecoration(labelText: 'Full name', prefixIcon: Icon(Icons.person_outline)),
                          validator: (value) {
                            final name = value?.trim() ?? '';
                            if (name.isEmpty) return 'Enter your name';
                            return name.length > 200 ? 'Use a name up to 200 characters' : null;
                          },
                        ),
                        const SizedBox(height: 16),
                      ],
                      if (!RouterApiService.cloudMode) TextFormField(
                        controller: _accessCodeController,
                        decoration: InputDecoration(
                          labelText: _creating
                              ? 'Gateway setup or household invite code'
                              : 'Household invitation code (optional)',
                          prefixIcon: const Icon(Icons.vpn_key_outlined),
                        ),
                        validator: (value) => _creating &&
                                (value == null || value.trim().isEmpty)
                            ? 'Enter the setup or invitation code'
                            : null,
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: _emailController,
                        keyboardType: TextInputType.emailAddress,
                        autocorrect: false,
                        enableSuggestions: false,
                        decoration: const InputDecoration(labelText: 'Email address', prefixIcon: Icon(Icons.mail_outline)),
                        validator: (value) {
                          final email = value?.trim() ?? '';
                          return email.length > 254 ||
                                  !RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(email)
                              ? 'Enter a valid email address'
                              : null;
                        },
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: _passwordController,
                        obscureText: true,
                        decoration: const InputDecoration(labelText: 'Password', prefixIcon: Icon(Icons.lock_outline)),
                        validator: (value) {
                          if (value == null || value.length < 8) return 'Use at least 8 characters';
                          return value.length > 1024 ? 'Use a password up to 1024 characters' : null;
                        },
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 26),
                FilledButton(
                  onPressed: _submitting ? null : _submit,
                  child: _submitting
                      ? const SizedBox(height: 22, width: 22, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(_creating ? 'Create account' : 'Sign in'),
                ),
                if (!_creating)
                  TextButton(
                    onPressed: _submitting ? null : _showPasswordReset,
                    child: const Text('Forgot password?'),
                  ),
                TextButton(
                  onPressed: _submitting ? null : () => setState(() => _creating = !_creating),
                  child: Text(_creating ? 'Already have an account? Sign in' : 'New here? Create an account'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _showPasswordReset() async {
    final email = TextEditingController(text: _emailController.text.trim());
    final code = TextEditingController();
    final password = TextEditingController();
    String? message;
    bool busy = false;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Reset password'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: email, decoration: const InputDecoration(labelText: 'Account email')),
              const SizedBox(height: 12),
              if (message != null) Text(message!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              TextField(controller: code, decoration: const InputDecoration(labelText: 'Email reset code')),
              TextField(
                controller: password,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'New password'),
              ),
            ]),
          ),
          actions: [
            TextButton(
              onPressed: () async {
                setDialogState(() => busy = true);
                try {
                  final result = await RouterApiService.requestPasswordReset(email.text.trim());
                  setDialogState(() {
                    message = result['success'] == true
                        ? result['message']?.toString() ?? 'Check your email for the code.'
                        : result['error']?.toString() ?? 'Could not send a reset code.';
                  });
                } catch (error) {
                  setDialogState(() => message = error.toString().replaceFirst(RegExp(r'^Exception:\s*'), ''));
                } finally {
                  if (dialogContext.mounted) setDialogState(() => busy = false);
                }
              },
              style: TextButton.styleFrom(),
              child: busy ? const Text('Sending...') : const Text('Send code'),
            ),
            FilledButton(
              onPressed: () async {
                if (password.text.length < 8) {
                  setDialogState(() => message = 'Use a password with at least 8 characters.');
                  return;
                }
                setDialogState(() => busy = true);
                Map<String, dynamic> result;
                try {
                  result = await RouterApiService.resetPassword(
                    email: email.text.trim(),
                    token: code.text.trim(),
                    newPassword: password.text,
                  );
                } catch (error) {
                  if (dialogContext.mounted) {
                    setDialogState(() {
                      message = error.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
                      busy = false;
                    });
                  }
                  return;
                }
                if (!dialogContext.mounted) return;
                setDialogState(() => busy = false);
                if (result['success'] == true) {
                  Navigator.pop(dialogContext);
                  if (mounted) {
                    ScaffoldMessenger.of(this.context).showSnackBar(
                      const SnackBar(content: Text('Password reset. You can sign in now.')),
                    );
                  }
                } else {
                  setDialogState(() => message = result['error']?.toString() ?? 'Password reset failed.');
                }
              },
              child: busy ? const CircularProgressIndicator() : const Text('Reset password'),
            ),
          ],
        ),
      ),
    );
    email.dispose();
    code.dispose();
    password.dispose();
  }
}