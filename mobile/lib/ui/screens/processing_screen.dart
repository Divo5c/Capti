/// Processing-Screen (Mobile): Status-Keys der Pipeline werden via i18n
/// übersetzt; Fortschritt nur mit echten Werten aus der Pipeline.
/// Ist die native Engine nicht verfügbar, wird das lokalisiert und
/// ehrlich angezeigt (keine Fake-Fortschrittsanimation).

library;
import 'package:flutter/material.dart';

import '../../core/i18n.dart';
import '../../core/project.dart';
import '../app.dart';
import '../session.dart';

class ProcessingScreen extends StatelessWidget {
  final AppSession session;

  const ProcessingScreen({super.key, required this.session});

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: !session.isProcessing,
      child: Scaffold(
        appBar: AppBar(
          title: Text(tr('proc.title')),
          automaticallyImplyLeading: false,
        ),
        body: SafeArea(
          child: ListenableBuilder(
            listenable: session,
            builder: (context, _) {
              final handle = session.runHandle;
              final error = session.processingError;

              // Ergebnis liegt vor -> weiter zum Result-Screen.
              if (session.workflow.state == WorkflowState.result) {
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (context.mounted) {
                    Navigator.pushReplacementNamed(context, '/result');
                  }
                });
              }

              return Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(tr('proc.subtitle'),
                          textAlign: TextAlign.center,
                          style:
                              Theme.of(context).textTheme.bodyMedium),
                      const SizedBox(height: 32),

                      // Prozentanzeige (echte Pipeline-Werte)
                      Text(
                        '${(handle?.progress ?? 0).round()} %',
                        textAlign: TextAlign.center,
                        style: Theme.of(context)
                            .textTheme
                            .displaySmall
                            ?.copyWith(
                                color: Theme.of(context)
                                    .colorScheme
                                    .primary,
                                fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 16),
                      LinearProgressIndicator(
                        key: const ValueKey('proc_progress'),
                        value: (handle?.progress ?? 0) / 100.0,
                        minHeight: 10,
                        borderRadius: BorderRadius.circular(5),
                      ),
                      const SizedBox(height: 16),

                      // Status (pipeline.*-Keys -> i18n)
                      Text(
                        tr(handle?.statusKey ?? 'proc.preparing'),
                        key: const ValueKey('proc_status'),
                        textAlign: TextAlign.center,
                        style:
                            Theme.of(context).textTheme.bodyMedium,
                      ),

                      // Log (dezente technische Anzeige)
                      if ((handle?.logLines.isNotEmpty ?? false)) ...[
                        const SizedBox(height: 24),
                        captiCard(
                          context: context,
                          padding: const EdgeInsets.all(12),
                          child: ConstrainedBox(
                            constraints:
                                const BoxConstraints(maxHeight: 160),
                            child: ListView(
                              shrinkWrap: true,
                              children: [
                                for (final line in handle!.logLines)
                                  Text(line,
                                      style: Theme.of(context)
                                          .textTheme
                                          .labelSmall),
                              ],
                            ),
                          ),
                        ),
                      ],

                      // Fehler / Engine nicht verfügbar – ehrlich anzeigen
                      if (error != null) ...[
                        const SizedBox(height: 24),
                        captiCard(
                          context: context,
                          child: Column(
                            children: [
                              Icon(Icons.error_outline,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .error),
                              const SizedBox(height: 8),
                              Text(
                                error.contains('EngineUnavailable')
                                    ? tr('proc.engine_missing')
                                    : error,
                                key: const ValueKey('proc_error'),
                                textAlign: TextAlign.center,
                                style: Theme.of(context)
                                    .textTheme
                                    .bodyMedium,
                              ),
                            ],
                          ),
                        ),
                      ],

                      const SizedBox(height: 28),

                      if (session.isProcessing)
                        SecondaryActionButton(
                          key: const ValueKey('proc_cancel'),
                          label: tr('proc.cancel'),
                          onPressed: () => session.cancelProcessing(),
                        )
                      else
                        SecondaryActionButton(
                          key: const ValueKey('proc_back'),
                          label: tr('common.back'),
                          onPressed: () =>
                              Navigator.pushNamed(context, '/caption-style'),
                        ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}
