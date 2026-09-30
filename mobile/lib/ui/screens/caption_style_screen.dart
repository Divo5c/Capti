/// Caption-Style-Screen (Mobile): Presets, Farben, Pop Scale/Decay und
/// animierte Vorschau auf 9:16-Canvas.
///
/// Die Vorschau verwendet EXAKT die Renderer-Port-Mathematik
/// (computeLayout + currentPopState) – keine zweite Animation-Engine.
/// Ablauf pro Wort: normal -> aktiv wächst auf Pop Scale ->
/// linearer Rückweg über pop_decay_ms (ASS-\t-Semantik).

library;
import 'dart:async';

import 'package:flutter/material.dart';

import '../../captions/renderer.dart';
import '../../core/caption_style.dart';
import '../../core/i18n.dart';
import '../app.dart';
import '../session.dart';
import 'caption_preview_painter.dart';const List<String> colorChoices = [
  '#FFFFFF', '#FFFF00', '#FF3B30', '#4EC9B0',
  '#FFD60A', '#101010', '#000000', '#5A5A5A',
];

class CaptionStyleScreen extends StatefulWidget {
  final AppSession session;
  const CaptionStyleScreen({super.key, required this.session});

  @override
  State<CaptionStyleScreen> createState() => _CaptionStyleScreenState();
}

class _CaptionStyleScreenState extends State<CaptionStyleScreen> {
  late CaptionStyle style;
  Timer? _ticker;
  DateTime _epoch = DateTime.now();
  int? activeWordIndex;
  double activeScale = 100.0;

  static const double previewWidth = 324; // 9:16 skaliert
  static const double previewHeight = 576;
  static const double virtualW = 1080;
  static final double virtualH = 1920;

  late final CaptionLayout layout =
      computeLayout(virtualW.toInt(), virtualH.toInt());

  /// Vorschau-Zeitplan: Wort ~450 ms + 60 ms Pause (wie Desktop-Preview).
  List<({String word, PopSlot slot})> timeline = [];

  String get sentence => tr('cs.preview_sentence');

  @override
  void initState() {
    super.initState();
    style = widget.session.styleDraft;
    debugPrint('PREVIEW_INIT style=${style.fontName} pop=${style.popEnabled}');
    WidgetsBinding.instance.addPostFrameCallback((_) => _rebuildTimeline());
    _startAnimation();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  void _apply(CaptionStyle next) {
    setState(() => style = next);
    widget.session.saveCaptionStyle(next);
    _rebuildTimeline();
  }

  void _rebuildTimeline() {
    // Zeilen wie im Renderer: max_words_per_line aus computeLayout,
    // max. 2 Zeilen.
    final words = sentence.split(' ');
    final perLine = layout.maxWordsPerLine < 1 ? 1 : layout.maxWordsPerLine;
    final lines = <List<String>>[];
    for (var i = 0; i < words.length && lines.length < 2; i += perLine) {
      lines.add(words.skip(i).take(perLine).toList());
    }

    const wordMs = 450.0;
    const gapMs = 60.0;
    var t = 300.0;
    final decay = style.popDecayMs.toDouble();
    final slots = <({String word, PopSlot slot})>[];
    for (final line in lines) {
      for (final w in line) {
        slots.add((
          word: w,
          slot: PopSlot(t, t + wordMs, t + wordMs + decay),
        ));
        t += wordMs + gapMs;
      }
    }
    final count = slots.length;
    final wordsDbg = slots.map((e) => e.word).join(' ');
    debugPrint('PREVIEW_TIMELINE_COUNT count=$count words=[$wordsDbg] sentence="$sentence"');
    if (mounted) setState(() => timeline = slots);
  }

  void _startAnimation() {
    _ticker?.cancel();
    _epoch = DateTime.now();
    _tick();
    _ticker = Timer.periodic(const Duration(milliseconds: 33), (_) => _tick());
  }

  void _tick() {
    if (!mounted) return;
    final tMs =
        DateTime.now().difference(_epoch).inMilliseconds.toDouble();
    final totalEnd =
        timeline.isEmpty ? 0 : timeline.last.slot.decayEndMs + 200;
    if (tMs > totalEnd + 1200) {
      _startAnimation(); // Loop mit kurzer Pause
      return;
    }
    final state = currentPopState(
      popEnabled: style.popEnabled,
      popScalePct: style.popScale,
      timeline: [for (final s in timeline) s.slot],
      tMs: tMs,
    );
    final prevActive = activeWordIndex;
    setState(() {
      activeWordIndex = state.active;
      activeScale = state.scale;
    });
    // Geraete-Log: nur bei Wechsel oder alle 2 Sekunden, um Logcat nicht zu fluten
    if (prevActive != state.active || tMs % 1000 < 34) {
      debugPrint(
          'PREVIEW_CURRENT_WORD active=$activeWordIndex scale=${activeScale.toStringAsFixed(1)} tMs=${tMs.toStringAsFixed(0)} timeline=${timeline.length}');
    }
  }

  /// Test-Sichtfenster: die tatsächlich gerenderten Preview-Wörter
  /// (CustomPainter-Text ist für find.text unsichtbar).
  @visibleForTesting
  List<String> get previewWordsForTests =>
      [for (final s in timeline) s.word];

  /// Test-Sichtfenster: aktuell aktiver Wortindex (Animation lebt?).
  @visibleForTesting
  int? get activeIndexForTests => activeWordIndex;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
          title: Text(tr('nav.caption_style')),
          leading: BackButton(onPressed: () => Navigator.pop(context))),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(tr('cs.subtitle'),
                  style: Theme.of(context).textTheme.bodyMedium),
              const SizedBox(height: 16),

              // ---------------- Vorschau ----------------
              Center(
                child: captiCard(
                  context: context,
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    children: [
                      Row(
                        mainAxisAlignment:
                            MainAxisAlignment.spaceBetween,
                        children: [
                          Text(tr('cs.preview'),
                              style: Theme.of(context)
                                  .textTheme
                                  .labelSmall),
                          IconButton(
                            key: const ValueKey('cs_replay'),
                            tooltip: 'Replay',
                            onPressed: _startAnimation,
                            icon: const Icon(Icons.replay_outlined),
                          ),
                        ],
                      ),
                      // Adaptive Größe: auf schmalen Geräten (z. B. 360 dp)
                      // wird die 9:16-Preview proportional verkleinert,
                      // statt horizontal zu überlaufen.
                      LayoutBuilder(builder: (context, constraints) {
                        final w = previewWidth.clamp(
                            0.0, constraints.maxWidth.isFinite
                                ? constraints.maxWidth
                                : previewWidth);
                        final h = w * (previewHeight / previewWidth);
                        // Deterministischer Fallback fuer leere Timeline (diagnostisch auf Geraet sichtbar):
                        final fallbackText = timeline.isEmpty
                            ? 'Das ist eine Test-Caption'
                            : tr('cs.preview_sentence');
                        // Direkter Android-Log fuer Diagnose:
                        debugPrint(
                            'PREVIEW_SIZE w=${w.toStringAsFixed(1)} h=${h.toStringAsFixed(1)} constraints=${constraints.maxWidth} timeline=${timeline.length} active=$activeWordIndex font=${style.fontName}');
                        return Column(
                          children: [
                            ClipRRect(
                              borderRadius: BorderRadius.circular(8),
                              child: Container(
                                width: w,
                                height: h,
                                color: Colors.black,
                                padding: const EdgeInsets.all(8),
                                child: RepaintBoundary(
                                  child: CustomPaint(
                                    key: const ValueKey('cs_preview'),
                                    painter: CaptionPreviewPainter(
                                      words: [
                                        for (final s in timeline) s.word
                                      ],
                                      activeIndex: activeWordIndex,
                                      activeScale: activeScale,
                                      style: style,
                                      layout: layout,
                                      staticFallbackText: fallbackText,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              '${w.round()}×${h.round()} · '
                                  '${timeline.length} Wörter · '
                                  'Anim ${activeWordIndex != null ? "läuft" : "bereit"} · '
                                  'Font ${style.fontName.trim().isEmpty ? "Roboto" : style.fontName}',
                              key: const ValueKey('cs_preview_diag'),
                              style:
                                  Theme.of(context).textTheme.labelSmall,
                            ),
                          ],
                        );
                      }),
                    ],
                  ),
                ),
              ),

              const SizedBox(height: 16),

              // ---------------- Presets ----------------
              captiCard(
                context: context,
                child: Wrap(
                  spacing: 8,
                  children: [
                    for (final name in captionPresets.keys)
                      OutlinedButton(
                        key: ValueKey('cs_preset_$name'),
                        onPressed: () => _apply(
                            style.mergedWithPreset(name)),
                        child: Text(name),
                      ),
                  ],
                ),
              ),

              const SizedBox(height: 16),

              // ---------------- Farben ----------------
              captiCard(
                context: context,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _ColorRow(
                      label: tr('cs.color.normal'),
                      value: style.normalColor,
                      onChanged: (c) => _apply(_copyWith(normalColor: c)),
                    ),
                    const Divider(),
                    _ColorRow(
                      label: tr('cs.color.highlight'),
                      value: style.highlightColor,
                      onChanged: (c) =>
                          _apply(_copyWith(highlightColor: c)),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 16),

              // ---------------- Pop-Effekt ----------------
              captiCard(
                context: context,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(tr('cs.pop_enabled')),
                        ),
                        Switch(
                          key: const ValueKey('cs_pop_switch'),
                          value: style.popEnabled,
                          thumbColor: WidgetStateProperty.all(
                              Theme.of(context).colorScheme.primary),
                          onChanged: (v) =>
                              _apply(_copyWith(popEnabled: v)),
                        ),
                      ],
                    ),
                    Text(tr('cs.pop_scale')),
                    Slider(
                      key: const ValueKey('cs_pop_scale'),
                      min: 100,
                      max: 150,
                      divisions: 10,
                      label: '${style.popScale}',
                      value: style.popScale.toDouble().clamp(100, 150),
                      onChanged: style.popEnabled
                          ? (v) => _apply(_copyWith(popScale: v.round()))
                          : null,
                    ),
                    Text(tr('cs.pop_decay')),
                    Slider(
                      key: const ValueKey('cs_pop_decay'),
                      min: 50,
                      max: 400,
                      divisions: 14,
                      label: '${style.popDecayMs}',
                      value:
                          style.popDecayMs.toDouble().clamp(50, 400),
                      onChanged: (v) =>
                          _apply(_copyWith(popDecayMs: v.round())),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 24),
              PrimaryActionButton(
                key: const ValueKey('cs_start'),
                label: tr('cs.start_processing'),
                onPressed: () async {
                  widget.session.saveCaptionStyle(style);
                  final ok = await widget.session.startProcessing();
                  if (!context.mounted) return;
                  Navigator.pushNamed(context, '/processing');
                  if (!ok && widget.session.processingError == null) {
                    // Start nicht erlaubt (sollte hier nicht passieren,
                    // da Workflow-Gate vorab greift)
                    ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text(tr('error.no_video'))));
                  }
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  CaptionStyle _copyWith({
    String? normalColor,
    String? highlightColor,
    bool? popEnabled,
    int? popScale,
    int? popDecayMs,
  }) =>
      CaptionStyle(
        normalColor: normalColor ?? style.normalColor,
        highlightColor: highlightColor ?? style.highlightColor,
        outlineColor: style.outlineColor,
        shadowColor: style.shadowColor,
        shadowAlpha: style.shadowAlpha,
        fontName: style.fontName,
        fontSize: style.fontSize,
        popEnabled: popEnabled ?? style.popEnabled,
        popScale: popScale ?? style.popScale,
        popDecayMs: popDecayMs ?? style.popDecayMs,
        shadowColorExplicit: style.shadowColorExplicit,
      );
}

class _ColorRow extends StatelessWidget {
  final String label;
  final String value;
  final ValueChanged<String> onChanged;

  const _ColorRow({
    required this.label,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: Text(label)),
        DropdownButton<String>(
          key: ValueKey('color_$label'),
          value: colorChoices.contains(value.toUpperCase())
              ? value.toUpperCase()
              : colorChoices.first,
          items: [
            for (final c in colorChoices)
              DropdownMenuItem(
                value: c,
                child: Row(children: [
                  Container(width: 18, height: 18, color: Color(int.parse(c.substring(1), radix: 16) | 0xFF000000)),
                  const SizedBox(width: 6),
                  Text(c),
                ]),
              )
          ],
          onChanged: (c) {
            if (c != null) onChanged(c);
          },
        ),
      ],
    );
  }
}

/// Zeichnet einen Vorschau-Rahmen: Wörter zentriert unten (Safe Area aus
/// computeLayout.marginV), aktives Wort in Highlightfarbe und mit
/// aktueller Pop-Skala (identische Mathematik wie der Renderer).
