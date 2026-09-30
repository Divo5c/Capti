# Capti – Agent Working Rules

## Project
Capti is a desktop transcription/video-caption application. The current released version is 2.0.0.

## Core rules
- Work directly in the existing repository.
- Before changing code, inspect the existing architecture and relevant files.
- Do not rewrite working systems unnecessarily.
- Preserve existing functionality unless the task explicitly requires changing it.
- Prefer small, maintainable changes over hacks.
- Do not remove existing tests just to make the test suite pass.
- Never weaken or delete an assertion merely because it fails after a change.
- After meaningful changes, run the relevant tests.
- Before declaring the task complete, run the complete test suite.
- Fix regressions instead of ignoring them.

## User data / privacy
NEVER read, modify, delete, commit, package, or upload:
- config.json
- history.json
- *.log
- personal APPDATA data
- credentials, tokens, API keys, or secrets

The user's existing configuration must remain untouched.

Builds and release packages MUST NOT contain the user's personal configuration or history.

## Git
- Do not force-push.
- Do not reset or discard unrelated user changes.
- Do not delete existing work merely to simplify implementation.
- Never commit secrets or personal configuration.
- Inspect git status before making major changes.
- Keep the working tree understandable.

## Verification
For UI changes:
- Test normal window sizes.
- Test the minimum supported window size.
- Test navigation between screens.
- Test theme changes.
- Test language changes where relevant.
- Check that scrolling still works.
- Check that screens remain visible and correctly mapped.

For workflow changes:
- Verify the complete workflow from input to result.
- Ensure cancellation/error paths remain functional.
- Ensure no unwanted temporary files are created.

## Long-running autonomy
You may work autonomously for an extended period when the task requires it.

Use the time productively:
1. Inspect.
2. Plan.
3. Implement.
4. Test.
5. Diagnose failures.
6. Fix regressions.
7. Re-test.
8. Perform a final audit.

Do not stop merely because the first implementation works.

Do not ask for confirmation for every small implementation decision.

If a reasonable implementation choice is required, make it based on the existing architecture and the task requirements.

## Completion standard
Do NOT claim completion based only on code being written.

A task is complete only when:
- the requested functionality exists,
- existing functionality still works,
- relevant tests pass,
- the full test suite passes,
- obvious edge cases have been checked,
- no personal configuration has been touched,
- and the final implementation matches the requested behavior.

When reporting completion, clearly state:
- files changed,
- functionality implemented,
- tests run and results,
- known limitations,
- anything intentionally not changed.
