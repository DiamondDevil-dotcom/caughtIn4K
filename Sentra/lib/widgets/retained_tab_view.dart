import 'package:flutter/material.dart';

class RetainedTabView extends StatefulWidget {
  const RetainedTabView({
    super.key,
    required this.index,
    required this.children,
  }) : assert(index >= 0);

  final int index;
  final List<Widget> children;

  @override
  State<RetainedTabView> createState() => _RetainedTabViewState();
}

class _RetainedTabViewState extends State<RetainedTabView>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;
  final Set<int> _visited = {};
  bool _reduceMotion = false;

  @override
  void initState() {
    super.initState();
    _visited.add(widget.index);
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 180),
      value: 1,
    );
    _opacity = Tween<double>(
      begin: 0.92,
      end: 1,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic));
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduceMotion = MediaQuery.disableAnimationsOf(context);
    if (_reduceMotion) _controller.value = 1;
  }

  @override
  void didUpdateWidget(RetainedTabView oldWidget) {
    super.didUpdateWidget(oldWidget);
    _visited.removeWhere((index) => index >= widget.children.length);
    _visited.add(widget.index);
    if (oldWidget.index != widget.index) {
      if (_reduceMotion) {
        _controller.value = 1;
      } else {
        _controller.forward(from: 0);
      }
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    assert(widget.index < widget.children.length);
    return Stack(
      fit: StackFit.expand,
      children: List.generate(widget.children.length, (index) {
        final selected = index == widget.index;
        return Offstage(
          offstage: !selected,
          child: TickerMode(
            enabled: selected,
            child: ExcludeFocus(
              excluding: !selected,
              child: FadeTransition(
                opacity: selected ? _opacity : const AlwaysStoppedAnimation(1),
                child: RepaintBoundary(
                  child: _visited.contains(index)
                      ? widget.children[index]
                      : const SizedBox.shrink(),
                ),
              ),
            ),
          ),
        );
      }),
    );
  }
}
