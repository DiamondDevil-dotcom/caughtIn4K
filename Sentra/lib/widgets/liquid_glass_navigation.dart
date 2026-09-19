import 'dart:ui';

import 'package:flutter/material.dart';

class LiquidGlassNavigation extends StatelessWidget {
  final int selectedIndex;
  final ValueChanged<int> onSelected;

  const LiquidGlassNavigation({
    super.key,
    required this.selectedIndex,
    required this.onSelected,
  });

  static const items = [
    (Icons.home_outlined, Icons.home, "Home"),
    (Icons.devices_outlined, Icons.devices, "Devices"),
    (Icons.history, Icons.history, "Activity"),
    (Icons.settings_outlined, Icons.settings, "Settings"),
  ];

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = isDark ? Colors.white : const Color(0xFF12202A);
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(24),
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
            child: Container(
              height: 70,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(24),
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [
                    ink.withValues(alpha: isDark ? 0.16 : 0.07),
                    const Color(0xFF168B63).withValues(
                      alpha: isDark ? 0.07 : 0.10,
                    ),
                    ink.withValues(alpha: isDark ? 0.05 : 0.025),
                  ],
                ),
                border: Border.all(
                  color: ink.withValues(alpha: isDark ? 0.18 : 0.12),
                ),
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFF168B63).withValues(
                      alpha: isDark ? 0.10 : 0.08,
                    ),
                    blurRadius: 24,
                    spreadRadius: 1,
                  ),
                ],
              ),
              child: Row(
                children: List.generate(items.length, (index) {
                  final selected = index == selectedIndex;
                  final item = items[index];
                  return Expanded(
                    child: _NavigationItem(
                      selected: selected,
                      ink: ink,
                      icon: selected ? item.$2 : item.$1,
                      label: item.$3,
                      onTap: () => onSelected(index),
                    ),
                  );
                }),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NavigationItem extends StatefulWidget {
  final bool selected;
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color ink;

  const _NavigationItem({
    required this.selected,
    required this.icon,
    required this.label,
    required this.onTap,
    required this.ink,
  });

  @override
  State<_NavigationItem> createState() => _NavigationItemState();
}

class _NavigationItemState extends State<_NavigationItem> {
  bool pressed = false;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final selectedColor = isDark
        ? const Color(0xFF64E3A1)
        : const Color(0xFF168B63);
    return GestureDetector(
      onTap: widget.onTap,
      onTapDown: (_) => setState(() => pressed = true),
      onTapUp: (_) => setState(() => pressed = false),
      onTapCancel: () => setState(() => pressed = false),
      child: AnimatedScale(
        scale: pressed ? 0.92 : 1,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOutCubic,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 360),
          curve: Curves.easeOutQuart,
          margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 9),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(17),
            color: widget.selected
              ? selectedColor.withValues(alpha: isDark ? 0.92 : 0.90)
                : Colors.transparent,
            boxShadow: widget.selected
                ? [
                    BoxShadow(
                      color: selectedColor.withValues(alpha: 0.20),
                      blurRadius: 14,
                    ),
                  ]
                : null,
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 260),
                switchInCurve: Curves.easeOutBack,
                switchOutCurve: Curves.easeIn,
                transitionBuilder: (child, animation) => ScaleTransition(
                  scale: animation,
                  child: FadeTransition(opacity: animation, child: child),
                ),
                child: Icon(
                  widget.icon,
                  key: ValueKey(widget.icon),
                  size: 21,
                  color: widget.selected
                      ? Colors.white
                      : widget.ink.withValues(alpha: 0.78),
                ),
              ),
              const SizedBox(height: 2),
              AnimatedDefaultTextStyle(
                duration: const Duration(milliseconds: 260),
                curve: Curves.easeOutCubic,
                style: TextStyle(
                  fontSize: widget.selected ? 10.5 : 10,
                  fontWeight: FontWeight.w700,
                  color: widget.selected
                      ? Colors.white
                      : widget.ink.withValues(alpha: 0.78),
                ),
                child: Text(widget.label),
              ),
            ],
          ),
        ),
      ),
    );
  }
}