import 'dart:ui';

import 'package:flutter/material.dart';

class LiquidGlassSurface extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final BorderRadius borderRadius;
  final Color accent;

  const LiquidGlassSurface({
    super.key,
    required this.child,
    this.padding,
    this.borderRadius = const BorderRadius.all(Radius.circular(16)),
    this.accent = const Color(0xFF64E3A1),
  });

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = isDark ? Colors.white : const Color(0xFF12202A);
    return ClipRRect(
      borderRadius: borderRadius,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 24, sigmaY: 24),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            borderRadius: borderRadius,
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                ink.withValues(alpha: isDark ? 0.17 : 0.08),
                accent.withValues(alpha: isDark ? 0.11 : 0.08),
                ink.withValues(alpha: isDark ? 0.055 : 0.03),
              ],
            ),
            border: Border.all(
              color: ink.withValues(alpha: isDark ? 0.22 : 0.16),
            ),
          ),
          child: child,
        ),
      ),
    );
  }
}