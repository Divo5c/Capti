/// New-Project-Screen (Mobile): Video-Auswahl über den System-Dateipicker
/// (Android SAF / iOS DocumentPicker), Sprache + Modell, Validierung.
/// KEIN Verarbeitungsstart hier – Weiter führt zum Caption-Style-Schritt.

library;
import 'package:flutter/material.dart';

import '../../core/i18n.dart';
import '../../core/project.dart';
import '../app.dart';
import '../session.dart';

class TranscriptionLanguageOption {
  final String label;
  final String? code;
  const TranscriptionLanguageOption(this.label, this.code);
}

class NewProjectScreen extends StatefulWidget {
  final AppSession session;
  const NewProjectScreen({super.key, required this.session});

  @override
  State<NewProjectScreen> createState() => _NewProjectScreenState();
}

class _NewProjectScreenState extends State<NewProjectScreen> {
  String? warning;

  List<TranscriptionLanguageOption> get languageOptions => [
        TranscriptionLanguageOption(tr('np.lang.auto'), null),
        const TranscriptionLanguageOption('Deutsch', 'de'),
        const TranscriptionLanguageOption('English', 'en'),
      ];

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    return Scaffold(
      appBar: AppBar(
          title: Text(tr('nav.new_project')),
          leading: BackButton(onPressed: () => Navigator.pop(context))),
      body: SafeArea(
        child: ListenableBuilder(
          listenable: session,
          builder: (context, _) {
            final project = session.project;
            final errors = project.validationErrors();
            final hasVideo =
                !errors.contains('error.no_video') &&
                    project.videoPath.isNotEmpty;
            return SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(tr('np.subtitle'),
                      style: Theme.of(context).textTheme.bodyMedium),
                  const SizedBox(height: 20),

                  // Video-Auswahl (großes Touch-Ziel)
                  captiCard(
                    context: context,
                    child: Column(
                      children: [
                        SizedBox(
                          width: double.infinity,
                          height: 64,
                          child: OutlinedButton.icon(
                            key: const ValueKey('np_pick_video'),
                            icon: const Icon(Icons.videocam_outlined),
                            label: Text(tr('np.btn_select'),
                                style:
                                    const TextStyle(fontSize: 16)),
                            onPressed: session.pickVideoPending
                                ? null
                                : () async {
                                    setState(() => warning = null);
                                    await session.pickVideo();
                                  },
                          ),
                        ),
                        if (hasVideo) ...[
                          const SizedBox(height: 10),
                          Align(
                            alignment: Alignment.centerLeft,
                            child: Text(
                              '${tr('np.selected')} '
                              '${_basename(project.videoPath)}',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                      color: Theme.of(context)
                                          .colorScheme
                                          .primary),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),

                  const SizedBox(height: 16),

                  // Sprache (stabile Codes, lokalisierte Labels)
                  captiCard(
                    context: context,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(tr('np.lang_title'),
                            style: Theme.of(context).textTheme.titleMedium),
                        Text(tr('np.lang_desc'),
                            style: Theme.of(context).textTheme.bodySmall),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          key: const ValueKey('np_language'),
                          initialValue:
                              project.language ?? languageOptions.first.code,
                          items: [
                            for (final opt in languageOptions)
                              DropdownMenuItem(
                                value: opt.code,
                                child: Text(opt.label),
                              )
                          ],
                          onChanged: (code) {
                            session.workflow.project = session.project.copyWith(
                                language: code,
                                clearLanguage: code == null);
                            session.notifyChanged();
                          },
                        ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 16),

                  // Modell
                  captiCard(
                    context: context,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(tr('np.model_title'),
                            style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          key: const ValueKey('np_model'),
                          initialValue: project.model,
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

                  if (warning != null || errors.contains('error.invalid_format')) ...[
                    const SizedBox(height: 12),
                    Text(
                      warning ?? tr('error.invalid_format'),
                      key: const ValueKey('np_warning'),
                      style: TextStyle(
                          color:
                              Theme.of(context).colorScheme.error),
                    ),
                  ],

                  const SizedBox(height: 24),
                  PrimaryActionButton(
                    key: const ValueKey('np_continue'),
                    label: tr('np.continue'),
                    onPressed: () {
                      setState(() => warning = null);
                      final errs = session.projectValidationErrors();
                      if (errs.contains('error.no_video') ||
                          errs.contains('error.video_missing')) {
                        setState(() => warning = tr('np.warn_no_video'));
                        return;
                      }
                      if (errs.contains('error.invalid_format')) {
                        setState(() => warning = tr('np.warn_invalid'));
                        return;
                      }
                      if (errs.contains('error.invalid_model')) {
                        setState(
                            () => warning = tr('error.invalid_model'));
                        return;
                      }
                      if (session.continueToCaptionStyle()) {
                        Navigator.pushNamed(context, '/caption-style');
                      }
                    },
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }

  static String _basename(String path) {
    final norm = path.replaceAll('\\', '/');
    final i = norm.lastIndexOf('/');
    return i >= 0 ? norm.substring(i + 1) : norm;
  }
}
