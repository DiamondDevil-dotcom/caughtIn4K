import 'package:flutter/material.dart';

import '../services/cloud_api_service.dart';

class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key});

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  final question = TextEditingController();
  final turns = <({String question, String reply})>[];
  bool agreed = false;
  bool busy = false;
  String? error;

  @override
  void dispose() {
    question.dispose();
    super.dispose();
  }

  Future<void> send() async {
    final text = question.text.trim();
    if (busy || !agreed || text.isEmpty) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await CloudApiService.request(
        'POST',
        '/cloud/assistant/chat',
        body: {'message': text},
      );
      final reply = result['reply'];
      if (reply is! String || reply.trim().isEmpty) {
        throw const FormatException('AI help returned an invalid reply.');
      }
      if (!mounted) return;
      setState(() {
        turns.add((question: text, reply: reply));
        if (turns.length > 10) turns.removeAt(0);
        question.clear();
      });
    } catch (exception) {
      if (mounted) setState(() => error = '$exception');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('AI help')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text(
          'Setup and general security guidance only. No live device access or '
          'actions. Each question is independent; previous messages are not sent. '
          'AI can make mistakes. Chat is not saved by this app.',
        ),
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          value: agreed,
          onChanged: busy
              ? null
              : (value) => setState(() => agreed = value == true),
          title: const Text(
            'I agree to send my typed question to OpenAI. Do not include '
            'passwords, QR codes, credentials or private network data.',
          ),
        ),
        ...turns.map(
          (turn) => Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('You: ${turn.question}'),
                  const SizedBox(height: 8),
                  SelectableText('AI: ${turn.reply}'),
                ],
              ),
            ),
          ),
        ),
        TextField(
          controller: question,
          enabled: !busy,
          maxLength: 2000,
          minLines: 2,
          maxLines: 5,
          decoration: const InputDecoration(labelText: 'Your question'),
        ),
        if (error != null)
          Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        FilledButton(
          onPressed: !agreed || busy ? null : send,
          child: Text(busy ? 'Asking...' : 'Ask AI'),
        ),
        TextButton(
          onPressed: busy
              ? null
              : () => setState(() {
                  turns.clear();
                  question.clear();
                  error = null;
                }),
          child: const Text('Clear chat'),
        ),
      ],
    ),
  );
}
