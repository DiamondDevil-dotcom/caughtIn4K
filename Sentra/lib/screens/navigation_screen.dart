import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'home_screen.dart';
import 'devices_screen.dart';
import 'activity_screen.dart';
import 'settings_screen.dart';
import 'demo_control_screen.dart';
import '../providers/demo_mode_provider.dart';
import '../widgets/liquid_glass_navigation.dart';

class NavigationScreen extends StatefulWidget {
  const NavigationScreen({super.key});

  @override
  State<NavigationScreen> createState() => _NavigationScreenState();
}

class _NavigationScreenState extends State<NavigationScreen> {
  int currentIndex = 0;
  late final PageController _pageController;

  List<Widget> _pages(bool demoMode) => [
        const HomeScreen(),
        const DevicesScreen(),
        const ActivityScreen(),
        const SettingsScreen(),
        if (demoMode) const DemoControlScreen(),
      ];

  List<(IconData, IconData, String)> _navItems(bool demoMode) => [
        ...LiquidGlassNavigation.defaultItems,
        if (demoMode) (Icons.science_outlined, Icons.science, "Demo"),
      ];

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final demoMode = context.watch<DemoModeProvider>().enabled;
    final pages = _pages(demoMode);
    final safeIndex = currentIndex < pages.length ? currentIndex : 0;
    return Scaffold(
      backgroundColor: isDark
          ? const Color(0xFF0B1220)
          : const Color(0xFFF3F7F8),
      body: DecoratedBox(
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
        child: PageView(
          controller: _pageController,
          physics: const NeverScrollableScrollPhysics(),
          onPageChanged: (index) => setState(() => currentIndex = index),
          children: pages,
        ),
      ),

      bottomNavigationBar: LiquidGlassNavigation(
        items: _navItems(demoMode),
        selectedIndex: safeIndex,
        onSelected: (index) {
          if (index == currentIndex) return;
          _pageController.animateToPage(
            index,
            duration: const Duration(milliseconds: 240),
            curve: Curves.easeOutCubic,
          );
          setState(() => currentIndex = index);
        },
      ),
    );
  }
}