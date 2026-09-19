import 'package:flutter/material.dart';

import 'home_screen.dart';
import 'devices_screen.dart';
import 'activity_screen.dart';
import 'settings_screen.dart';
import '../widgets/liquid_glass_navigation.dart';

class NavigationScreen extends StatefulWidget {
  const NavigationScreen({super.key});

  @override
  State<NavigationScreen> createState() => _NavigationScreenState();
}

class _NavigationScreenState extends State<NavigationScreen> {

  int currentIndex = 0;

  final List<Widget> pages = const [
    HomeScreen(),
    DevicesScreen(),
    ActivityScreen(),
    SettingsScreen(),
  ];

  Alignment _backgroundAlignment = Alignment.topLeft;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      backgroundColor: isDark
          ? const Color(0xFF0B1220)
          : const Color(0xFFF3F7F8),
      body: AnimatedContainer(
        duration: const Duration(milliseconds: 900),
        curve: Curves.easeInOutCubic,
        alignment: _backgroundAlignment,
        decoration: BoxDecoration(
          gradient: RadialGradient(
            center: Alignment.topLeft,
            radius: 1.25,
            colors: isDark
                ? const [
                    Color(0xFF12364A),
                    Color(0xFF0B1220),
                    Color(0xFF060A10),
                  ]
                : const [
                    Color(0xFFE0F7F2),
                    Color(0xFFF3F7F8),
                    Color(0xFFE8F0F2),
                  ],
          ),
        ),
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 460),
          reverseDuration: const Duration(milliseconds: 360),
          switchInCurve: Curves.easeOutQuart,
          switchOutCurve: Curves.easeInQuart,
          transitionBuilder: (child, animation) {
            final offset = Tween<Offset>(
              begin: const Offset(0.018, 0.012),
              end: Offset.zero,
            ).animate(animation);
            return FadeTransition(
              opacity: animation,
              child: SlideTransition(position: offset, child: child),
            );
          },
          child: KeyedSubtree(
            key: ValueKey(currentIndex),
            child: pages[currentIndex],
          ),
        ),
      ),

      bottomNavigationBar: LiquidGlassNavigation(
        selectedIndex: currentIndex,
        onSelected: (index) {
          setState(() {
            currentIndex = index;
            _backgroundAlignment = index.isEven
                ? Alignment.topLeft
                : Alignment.bottomRight;
          });
        },
      ),
    );
  }
}