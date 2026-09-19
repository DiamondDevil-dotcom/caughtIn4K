import 'dart:async';

import 'package:flutter/material.dart';

import 'navigation_screen.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _animationController;
  late final Animation<double> _logoScale;
  late final Animation<double> _logoOpacity;
  late final Animation<double> _textOpacity;
  late final Animation<Offset> _textSlide;

  @override
  void initState() {
    super.initState();

    _animationController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    )..forward();

    _logoScale = CurvedAnimation(
      parent: _animationController,
      curve: const Interval(0, 0.72, curve: Curves.easeOutBack),
    );
    _logoOpacity = CurvedAnimation(
      parent: _animationController,
      curve: const Interval(0, 0.4, curve: Curves.easeOut),
    );
    _textOpacity = CurvedAnimation(
      parent: _animationController,
      curve: const Interval(0.35, 0.9, curve: Curves.easeOut),
    );
    _textSlide = Tween<Offset>(
      begin: const Offset(0, 0.18),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _animationController,
      curve: const Interval(0.35, 0.9, curve: Curves.easeOutCubic),
    ));

    Timer(
      const Duration(milliseconds: 2600),
      () {
        if (!mounted) return;
        Navigator.of(context).pushReplacement(
          PageRouteBuilder<void>(
            transitionDuration: const Duration(milliseconds: 650),
            reverseTransitionDuration: const Duration(milliseconds: 350),
            pageBuilder: (_, animation, secondaryAnimation) =>
                const NavigationScreen(),
            transitionsBuilder: (_, animation, secondaryAnimation, child) {
              final curve = CurvedAnimation(
                parent: animation,
                curve: Curves.easeOutCubic,
              );
              return FadeTransition(
                opacity: curve,
                child: ScaleTransition(
                  scale: Tween<double>(begin: 0.97, end: 1).animate(curve),
                  child: child,
                ),
              );
            },
          ),
        );
      },
    );
  }

  @override
  void dispose() {
    _animationController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF071522), Color(0xFF0B1220), Color(0xFF061019)],
          ),
        ),
        child: Stack(
          children: [
            Positioned(
              top: -120,
              right: -80,
              child: _glow(const Color(0xFF0EDBFF), 300),
            ),
            Positioned(
              bottom: -180,
              left: -100,
              child: _glow(const Color(0xFF1C6CFF), 340),
            ),
            SafeArea(
              child: Center(
                child: AnimatedBuilder(
                  animation: _animationController,
                  builder: (context, child) => Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Opacity(
                        opacity: _logoOpacity.value,
                        child: Transform.scale(
                          scale: 0.78 + (_logoScale.value * 0.22),
                          child: Image.asset(
                            "assets/images/caughtIn4k_logo.png",
                            width: 250,
                            height: 250,
                            fit: BoxFit.contain,
                          ),
                        ),
                      ),
                      const SizedBox(height: 22),
                      SlideTransition(
                        position: _textSlide,
                        child: Opacity(
                          opacity: _textOpacity.value,
                          child: Column(
                            children: [
                              Text(
                                "caughtIn4K",
                                style: Theme.of(context)
                                    .textTheme
                                    .headlineMedium
                                    ?.copyWith(
                                      fontSize: 34,
                                      fontWeight: FontWeight.w800,
                                      letterSpacing: 2.5,
                                    ),
                              ),
                              const SizedBox(height: 10),
                              Text(
                                "Nothing Escapes Detection.",
                                style: Theme.of(context)
                                    .textTheme
                                    .bodyMedium
                                    ?.copyWith(
                                      color: Colors.white70,
                                      letterSpacing: 0.8,
                                    ),
                              ),
                              const SizedBox(height: 28),
                              SizedBox(
                                width: 34,
                                child: LinearProgressIndicator(
                                  minHeight: 3,
                                  borderRadius: BorderRadius.circular(3),
                                  backgroundColor: Colors.white12,
                                  valueColor: AlwaysStoppedAnimation(
                                    Theme.of(context).colorScheme.primary,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _glow(Color color, double size) {
    return IgnorePointer(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(
              color: color.withValues(alpha: 0.12),
              blurRadius: 100,
              spreadRadius: 35,
            ),
          ],
        ),
      ),
    );
  }
}