/// Home-Screen (Mobile): Capti-Branding, Begrüßung, großer
/// "Neues Projekt"-CTA, Verlauf. Touch-first, vertikal scrollbar.

library;
import 'package:flutter/material.dart';

import '../../core/i18n.dart';
import '../../core/theme.dart';
import '../app.dart';
import '../session.dart';

class HomeScreen extends StatelessWidget {
  final AppSession session;

  const HomeScreen({super.key, required this.session});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Capti',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 24)),
        actions: [
          IconButton(
            key: const ValueKey('home_settings'),
            tooltip: tr('set.title'),
            onPressed: () => Navigator.pushNamed(context, '/settings'),
            icon: const Icon(Icons.settings_outlined),
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: SafeArea(
        child: ListenableBuilder(
          listenable: session,
          builder: (context, _) {
            final name = session.userName;
            return SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(tr('app.tagline'),
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodyMedium),
                  const SizedBox(height: 24),
                  Text(
                    name.isEmpty
                        ? tr('home.greeting_no_name')
                        : tr('home.greeting', {'name': name}),
                    textAlign: TextAlign.center,
                    style: Theme.of(context)
                        .textTheme
                        .headlineMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 28),

                  // Großer CTA (Touch-Ziel >= 120 dp hoch)
                  captiCard(
                    context: context,
                    child: InkWell(
                      key: const ValueKey('home_cta'),
                      borderRadius: BorderRadius.circular(14),
                      onTap: () {
                        if (session.enterNewProject()) {
                          Navigator.pushNamed(context, '/new-project');
                        }
                      },
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 36),
                        child: Column(
                          children: [
                            Text(tr('home.cta_new'),
                                style: Theme.of(context)
                                    .textTheme
                                    .titleLarge
                                    ?.copyWith(
                                        color: getTheme(currentThemeName(
                                                context))
                                            .accent,
                                        fontWeight: FontWeight.w700)),
                            const SizedBox(height: 6),
                            Text(tr('home.cta_hint'),
                                style: Theme.of(context).textTheme.bodySmall),
                          ],
                        ),
                      ),
                    ),
                  ),

                  const SizedBox(height: 28),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Text(tr('home.history_title'),
                        style: Theme.of(context).textTheme.titleMedium),
                  ),
                  const SizedBox(height: 10),
                  _HistoryList(session: session),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

class _HistoryList extends StatelessWidget {
  final AppSession session;
  const _HistoryList({required this.session});

  @override
  Widget build(BuildContext context) {
    final entries = session.history.recent(limit: 10);
    if (entries.isEmpty) {
      return captiCard(
        context: context,
        child: Column(
          children: [
            Text(tr('history.empty_title'),
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge),
            const SizedBox(height: 4),
            Text(tr('history.empty_hint'),
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      );
    }
    return Column(
      children: [
        for (final e in entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: captiCard(
              context: context,
              padding: const EdgeInsets.symmetric(
                  horizontal: 16, vertical: 12),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(_basename(e['video_path'] as String? ?? ''),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style:
                                Theme.of(context).textTheme.bodyLarge),
                        if ((e['timestamp'] as String?)?.isNotEmpty == true)
                          Text((e['timestamp'] as String).split('T').first,
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall), // technische Meta
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  static String _basename(String path) {
    final norm = path.replaceAll('\\', '/');
    final i = norm.lastIndexOf('/');
    return i >= 0 ? norm.substring(i + 1) : norm;
  }
}
