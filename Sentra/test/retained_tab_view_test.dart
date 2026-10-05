import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nyxis_security/widgets/retained_tab_view.dart';

class _TestTab extends StatefulWidget {
  const _TestTab(this.name, this.onMount);

  final String name;
  final VoidCallback onMount;

  @override
  State<_TestTab> createState() => _TestTabState();
}

class _TestTabState extends State<_TestTab> {
  int count = 0;

  @override
  void initState() {
    super.initState();
    widget.onMount();
  }

  @override
  Widget build(BuildContext context) {
    return TextButton(
      onPressed: () => setState(() => count++),
      child: Text('${widget.name}: $count'),
    );
  }
}

void main() {
  testWidgets('Direct switches skip intermediate tabs and preserve tab state', (
    tester,
  ) async {
    final mounts = List.filled(4, 0);
    final tabs = List.generate(
      4,
      (index) => _TestTab('Tab $index', () => mounts[index]++),
    );
    Future<void> select(int index, {bool reduceMotion = false}) async {
      await tester.pumpWidget(
        MaterialApp(
          home: MediaQuery(
            data: MediaQueryData(disableAnimations: reduceMotion),
            child: RetainedTabView(index: index, children: tabs),
          ),
        ),
      );
    }

    await select(0);
    await tester.tap(find.text('Tab 0: 0'));
    await select(3);
    expect(mounts, [1, 0, 0, 1]);
    expect(find.text('Tab 3: 0'), findsOneWidget);
    expect(find.text('Tab 0: 1'), findsNothing);

    // Switch again before the first transition finishes.
    await tester.pump(const Duration(milliseconds: 30));
    await select(1);
    await select(0);
    await tester.pumpAndSettle();
    expect(find.text('Tab 0: 1'), findsOneWidget);
    expect(mounts, [1, 1, 0, 1]);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Reduced motion switches immediately without animation tickers', (
    tester,
  ) async {
    Future<void> select(int index) async {
      await tester.pumpWidget(
        MaterialApp(
          home: MediaQuery(
            data: const MediaQueryData(disableAnimations: true),
            child: RetainedTabView(
              index: index,
              children: const [Text('Home'), Text('Devices')],
            ),
          ),
        ),
      );
    }

    await select(0);
    await select(1);
    expect(find.text('Devices'), findsOneWidget);
    final fade = tester.widget<FadeTransition>(
      find
          .ancestor(
            of: find.text('Devices'),
            matching: find.byType(FadeTransition),
          )
          .first,
    );
    expect(fade.opacity.value, 1);
    expect(fade.opacity.status, AnimationStatus.completed);
    expect(tester.binding.transientCallbackCount, 0);
  });

  testWidgets('Removing the demo tab allows a safe return to Home', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: RetainedTabView(
          index: 2,
          children: const [Text('Home'), Text('Devices'), Text('Demo')],
        ),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: RetainedTabView(
          index: 0,
          children: const [Text('Home'), Text('Devices')],
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Demo', skipOffstage: false), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
