/// Result-Screen (Mobile): Erfolg, Metadaten, Export ("Speichern unter")
/// und Navigation zu neuem Projekt / Home.

library;
import 'dart:io';

import 'package:flutter/material.dart';

import '../../core/i18n.dart';
import '../app.dart';
import '../session.dart';

class ResultScreen extends StatelessWidget {
  final AppSession session;

  const ResultScreen({super.key, required this.session});

  @override
  Widget build(BuildContext context) {
    final outputPath = session.lastOutputPath ?? '';
    final exists = outputPath.isNotEmpty && File(outputPath).existsSync();
    final filename = _basename(outputPath);

    return Scaffold(
      appBar: AppBar(
        title: Text(tr('res.title')),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 8),
              Icon(Icons.check_circle_outline,
                  size: 72,
                  color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 12),
              Text(tr('res.subtitle'),
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium),
              const SizedBox(height: 24),

              captiCard(
                context: context,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      filename.isNotEmpty
                          ? filename
                          : tr('res.no_result'),
                      key: const ValueKey('res_filename'),
                      style: Theme.of(context)
                          .textTheme
                          .titleMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    if (outputPath.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(outputPath,
                          key: const ValueKey('res_path'),
                          style: Theme.of(context).textTheme.bodySmall),
                    ],
                    if (!exists) ...[
                      const SizedBox(height: 6),
                      Text(tr('error.video_missing'),
                          style: TextStyle(
                              color:
                                  Theme.of(context).colorScheme.error)),
                    ],
                  ],
                ),
              ),

              const SizedBox(height: 24),

              // Galerie-Status (automatisch nach Movies/Capti gespeichert)
              if (session.lastGalleryName != null) ...[
                captiCard(
                  context: context,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Icon(Icons.check_circle,
                            color: Theme.of(context).colorScheme.primary, size: 20),
                        const SizedBox(width: 8),
                        Text(tr('res.gallery_saved'),
                            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                                fontWeight: FontWeight.w700)),
                      ]),
                      const SizedBox(height: 6),
                      Text(tr('res.gallery_saved_desc'),
                          style: Theme.of(context).textTheme.bodySmall),
                      const SizedBox(height: 4),
                      Text('${tr('res.gallery_path')}${session.lastGalleryName}',
                          key: const ValueKey('res_gallery_path'),
                          style: Theme.of(context).textTheme.labelSmall),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                PrimaryActionButton(
                  key: const ValueKey('res_open_gallery'),
                  label: tr('res.btn_open_gallery'),
                  onPressed: () async {
                    final ok = await session.openGallery();
                    if (!context.mounted) return;
                    if (!ok) {
                      ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text(tr('error.gallery_failed'))));
                    }
                  },
                ),
              ] else if (session.gallerySaveFailed) ...[
                captiCard(
                  context: context,
                  child: Column(
                    children: [
                      Icon(Icons.error_outline,
                          color: Theme.of(context).colorScheme.error),
                      const SizedBox(height: 8),
                      Text(
                          (session.processingError != null &&
                                  session.processingError!.contains('CAPTI_GALLERY_ERROR'))
                              ? session.processingError!
                              : tr('error.gallery_failed'),
                          key: const ValueKey('res_gallery_error'),
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.bodyMedium),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                PrimaryActionButton(
                  key: const ValueKey('res_retry_gallery'),
                  label: tr('res.btn_save_as'),
                  onPressed: exists
                      ? () async {
                          final ok = await session.exportResult();
                          if (!context.mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                              content: Text(ok
                                  ? tr('res.gallery_saved')
                                  : tr('error.gallery_failed'))));
                          (context as Element).markNeedsBuild();
                        }
                      : null,
                ),
              ] else ...[
                // Fallback: manueller Export (sollte bei Auto-Galerie nicht nötig sein)
                PrimaryActionButton(
                  key: const ValueKey('res_save_as'),
                  label: tr('res.btn_save_as'),
                  onPressed: exists
                      ? () async {
                          final ok = await session.exportResult();
                          if (!context.mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                              content: Text(ok
                                  ? tr('set.saved')
                                  : tr('res.no_result'))));
                        }
                      : null,
                ),
              ],
              const SizedBox(height: 12),

              SecondaryActionButton(
                key: const ValueKey('res_new_project'),
                label: tr('res.btn_new_project'),
                onPressed: () {
                  session.resetToHome();
                  if (session.enterNewProject()) {
                    Navigator.pushNamedAndRemoveUntil(
                        context, '/new-project', (r) => false);
                  }
                },
              ),
              const SizedBox(height: 12),

              SecondaryActionButton(
                key: const ValueKey('res_home'),
                label: tr('nav.home'),
                onPressed: () {
                  session.resetToHome();
                  Navigator.pushNamedAndRemoveUntil(
                      context, '/', (r) => false);
                },
              ),
            ],
          ),
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
