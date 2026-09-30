/// Settings-Screen (Mobile): Name, Theme, Sprache, Standardmodell,
/// Verlauf löschen. Alles Auto-Save (kein Speichern-Button) – wie Desktop.

library;
import 'package:flutter/material.dart';

import '../../core/i18n.dart';
import '../../core/project.dart';
import '../../core/theme.dart';
import '../app.dart';
import '../session.dart';

class SettingsScreen extends StatefulWidget {
  final AppSession session;
  const SettingsScreen({super.key, required this.session});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _nameController;

  @override
  void initState() {
    super.initState();
    _nameController = TextEditingController(text: widget.session.userName);
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    return Scaffold(
      appBar: AppBar(
          title: Text(tr('set.title')),
          leading: BackButton(onPressed: () => Navigator.pop(context))),
      body: SafeArea(
        child: ListenableBuilder(
          listenable: session,
          builder: (context, _) {
            final tokens = getTheme(session.theme);
            return SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Name (Auto-Save bei Änderung)
                  captiCard(
                    context: context,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(tr('set.name_title'),
                            style:
                                Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        TextField(
                          key: const ValueKey('set_name'),
                          controller: _nameController,
                          decoration: InputDecoration(
                              suffixIcon: IconButton(
                            key: const ValueKey('set_name_commit'),
                            icon: const Icon(Icons.check),
                            onPressed: () => session.setUserName(
                                _nameController.text),
                          )),
                          onSubmitted:
                              session.setUserName,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Theme (sofort aktiv, Auto-Save)
                  captiCard(
                    context: context,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(tr('set.theme_title'),
                            style:
                                Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        SegmentedButton<String>(
                          key: const ValueKey('set_theme'),
                          segments: [
                            for (final t in availableThemes)
                              ButtonSegment(value: t, label: Text(t)),
                          ],
                          selected: {session.theme},
                          onSelectionChanged: (selection) =>
                              session.setTheme(selection.first),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  // UI-Sprache (Live-Wechsel, Auto-Save)
                  captiCard(
                    context: context,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(tr('set.lang_title'),
                            style:
                                Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          key: const ValueKey('set_language'),
                          initialValue: session.language,
                          items: const [
                            DropdownMenuItem(
                                value: 'de', child: Text('Deutsch')),
                            DropdownMenuItem(
                                value: 'en', child: Text('English')),
                          ],
                          onChanged: (v) =>
                              v == null ? null : session.setLanguage(v),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Standardmodell
                  captiCard(
                    context: context,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(tr('set.model_title'),
                            style:
                                Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          key: const ValueKey('set_model'),
                          initialValue: session.project.model ==
                                  session.settings.model
                              ? session.settings.model
                              : session.settings.model,
                          items: [
                            for (final m in validModels)
                              DropdownMenuItem(value: m, child: Text(m))
                          ],
                          onChanged: (m) =>
                              m == null ? null : session.setDefaultModel(m),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Verlauf löschen
                  captiCard(
                    context: context,
                    child: Column(
                      children: [
                        OutlinedButton.icon(
                          key: const ValueKey('set_clear_history'),
                          icon: const Icon(Icons.delete_outline),
                          label: Text(tr('set.clear_history')),
                          onPressed: () => setState(() {
                            widget.session.history.clear();
                          }),
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 24),
                  // Akzent-Vorschau als Live-Feedback des Themes
                  Row(children: [
                    Container(width: 24, height: 24,
                        color: tokens.accent),
                    const SizedBox(width: 8),
                    Text('${tr('set.theme_title')}: ${session.theme}'),
                  ]),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}
