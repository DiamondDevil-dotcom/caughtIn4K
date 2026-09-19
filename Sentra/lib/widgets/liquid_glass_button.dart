import 'dart:ui';

import 'package:flutter/material.dart';

class LiquidGlassButton extends StatefulWidget {
  final String label;
  final VoidCallback? onPressed;
  final Widget? icon;
  final bool destructive;

  const LiquidGlassButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.destructive = false,
  });

  @override
  State<LiquidGlassButton> createState() => _LiquidGlassButtonState();
}

class _LiquidGlassButtonState extends State<LiquidGlassButton> {
  bool _pressed = false;
  bool _hovered = false;

  bool get _enabled => widget.onPressed != null;

  void _setPressed(bool value) {
    if (_enabled && _pressed != value) {
      setState(() => _pressed = value);
    }
  }

  @override
  Widget build(BuildContext context) {
    final accent = widget.destructive
        ? const Color(0xFFFF6B6B)
        : const Color(0xFF64E3A1);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = isDark ? Colors.white : const Color(0xFF12202A);
    final opacity = _enabled ? 1.0 : 0.35;

    return Semantics(
      button: true,
      enabled: _enabled,
      label: widget.label,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          onTap: widget.onPressed,
          onTapDown: (_) => _setPressed(true),
          onTapUp: (_) => _setPressed(false),
          onTapCancel: () => _setPressed(false),
          child: AnimatedScale(
            scale: _pressed ? 0.975 : (_hovered ? 1.012 : 1.0),
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOutCubic,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 260),
              curve: Curves.easeOutCubic,
              height: 56,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(18),
                boxShadow: [
                  BoxShadow(
                    color: accent.withValues(alpha: _hovered ? 0.22 : 0.10),
                    blurRadius: _hovered ? 24 : 14,
                    spreadRadius: _hovered ? 1 : 0,
                  ),
                ],
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(18),
                child: BackdropFilter(
                  filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                        colors: [
                          ink.withValues(alpha: 0.20 * opacity),
                          accent.withValues(alpha: 0.16 * opacity),
                          ink.withValues(alpha: 0.06 * opacity),
                        ],
                      ),
                      border: Border.all(
                        color: ink.withValues(alpha: 0.28 * opacity),
                      ),
                    ),
                    child: Stack(
                      children: [
                        Positioned(
                          top: 0,
                          left: 18,
                          right: 18,
                          child: Container(
                            height: 1,
                            color: ink.withValues(alpha: 0.48 * opacity),
                          ),
                        ),
                        Center(
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (widget.icon != null) ...[
                                IconTheme(
                                  data: IconThemeData(
                                    color: ink.withValues(alpha: opacity),
                                    size: 19,
                                  ),
                                  child: widget.icon!,
                                ),
                                const SizedBox(width: 9),
                              ],
                              Text(
                                widget.label,
                                style: TextStyle(
                                  color: ink.withValues(alpha: opacity),
                                  fontWeight: FontWeight.w700,
                                  letterSpacing: 0.15,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}