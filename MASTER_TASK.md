# Capti – Master Task

## Autonomous Engineering Mission

You are the primary autonomous software engineer for the Capti project.

You have permission to work autonomously for an extended period of time. Do not stop after the first successful implementation. Analyze the existing codebase deeply, implement the requested product evolution, test continuously, diagnose failures, fix regressions, and perform a final audit before declaring the task complete.

The goal is not merely to write code.

The goal is to produce a polished, coherent, production-quality Capti application while preserving all functionality that already works.

---

# 1. IMPORTANT: EXISTING PROJECT

Capti currently has a working Windows desktop application.

Current released version:

**2.0.0**

The repository already contains:

* modern CustomTkinter UI
* responsive screens
* scrolling
* Home
* New Project
* Caption Style
* Processing
* Result
* Settings
* i18n
* theme system
* automatic settings persistence
* window-state persistence
* caption-style presets
* animated caption preview
* Pop Scale / Pop Decay
* transcription pipeline
* subtitle rendering
* FFmpeg integration
* history
* drag & drop
* tests
* build system
* Windows packaging

Do NOT replace working functionality blindly.

First inspect the complete architecture.

---

# 2. FIRST PHASE: DEEP CODEBASE AUDIT

Before implementing substantial changes:

1. Inspect the repository structure.
2. Read the main application entry point.
3. Read configuration handling.
4. Read AppController.
5. Read every modern UI screen.
6. Read the caption renderer.
7. Read the processing pipeline.
8. Read video processing code.
9. Read subtitle/ASS generation.
10. Read theme and i18n systems.
11. Read build/package configuration.
12. Read existing tests.
13. Inspect README and documentation.
14. Inspect Git status.

Understand how the existing desktop application works before making architectural decisions.

Do not assume that a feature is missing simply because it is not obvious from the UI.

---

# 3. DO NOT DESTROY THE DESKTOP VERSION

The existing Windows desktop application is valuable and must remain functional.

Preserve:

* transcription
* Whisper/model handling
* video processing
* subtitle generation
* caption styles
* caption renderer
* karaoke/highlight behavior
* Pop Scale
* Pop Decay
* history
* drag & drop
* themes
* language switching
* automatic settings saving
* window state
* error handling
* result screen
* existing tests

Do not rewrite these systems unless the architecture genuinely requires it.

If shared business logic needs restructuring to support mobile, extract reusable logic instead of duplicating incompatible implementations.

---

# 4. MOBILE PRODUCT GOAL

The long-term goal is to make Capti available as a real application for:

* Samsung / Android
* iPhone / iOS

The mobile experience should not be a crude desktop UI squeezed onto a phone.

It should be designed as a proper mobile product.

The architecture should therefore separate:

## Shared core

Reusable:

* project model
* settings model
* caption style model
* caption layout logic
* transcription abstraction
* subtitle generation
* video processing abstraction
* history model
* localization
* validation
* project state

from:

## Platform UI

Desktop:

* CustomTkinter

Mobile:

* appropriate cross-platform mobile framework or architecture selected after researching the repository and constraints.

Do not introduce a framework merely because it is fashionable.

Choose the technology based on:

* Android support
* iOS support
* video processing support
* audio/video file access
* performance
* native integration
* maintainability
* ability to share business logic
* realistic build/deployment requirements

Document the decision.

---

# 5. MOBILE UI PRINCIPLES

The mobile UI must be intentionally designed for touch.

Requirements:

* no tiny desktop controls
* no desktop-only layouts
* proper touch targets
* vertical scrolling
* responsive phone sizes
* portrait-first design
* support for larger phones/tablets where practical
* safe areas
* keyboard handling
* loading states
* error states
* progress states
* accessible text sizes
* clear navigation
* consistent spacing
* modern visual hierarchy

The Capti identity should remain recognizable.

The existing Capti wordmark/text treatment may be reused conceptually.

Do not replace the existing desktop logo unnecessarily.

---

# 6. MOBILE WORKFLOW

The primary mobile workflow should be:

## Home

User sees:

* Capti branding
* New Project
* recent projects/history where appropriate
* simple navigation

## New Project

User selects:

1. video
2. language
3. transcription model where supported

Then:

**Weiter → / Next →**

Do not immediately start processing.

## Caption Style

User selects the caption style.

The user must be able to:

* browse presets
* see the currently selected style
* modify supported style parameters
* preview the result

Then:

**Verarbeitung starten → / Start Processing →**

## Processing

Show:

* current stage
* meaningful progress where available
* status
* ability to cancel where technically safe

Do not pretend to have percentage progress if the underlying operation cannot provide reliable progress.

## Result

User can:

* preview the result
* save/export the video
* return to project creation
* start another project

---

# 7. CAPTION STYLE PREVIEW

This is a major product feature.

The current desktop preview already uses the renderer's layout information and animates Pop Scale.

Do not replace it with a fake static example.

The preview should communicate what the caption will actually look like in the generated video.

The preview should represent:

* 9:16 video
* caption position
* safe area
* font
* font size
* normal color
* highlight color
* outline
* shadow
* line wrapping
* maximum words per line
* active-word highlighting
* Pop Scale
* Pop Decay

The preview animation should visibly demonstrate the active word.

For example:

normal word → active word grows → active word returns to normal size

The exact timing should remain tied to the actual caption-rendering semantics where possible.

Do not create a second incompatible caption-animation implementation.

The renderer should remain the source of truth.

---

# 8. CAPTION STYLE ARCHITECTURE

There must be one coherent style representation.

Avoid having:

* one style format for desktop
* another for mobile
* another for preview
* another for rendering

Instead define a shared caption-style model.

The model should be serializable and platform-independent.

It should support at minimum:

* preset identity
* font
* font size / scale
* normal color
* highlight color
* outline
* shadow
* position
* maximum words per line
* Pop Scale
* Pop Decay

If a parameter cannot be supported on a platform, handle that explicitly rather than silently changing it.

---

# 9. SETTINGS

Settings must remain automatic.

There must be no unnecessary Save button.

Changes should be applied immediately when appropriate.

At minimum:

* theme
* language
* name
* model
* caption style

must persist correctly.

The application must not silently reset an existing value because a UI label could not be resolved.

Use stable internal codes and localized display labels.

Live language changes must not corrupt settings.

---

# 10. WINDOW / APP STATE

Desktop:

The last valid window state should be restored on startup.

Preserve:

* width
* height
* position
* maximized state

Mobile:

Persist appropriate navigation/project state where useful.

Do not persist temporary/private data unnecessarily.

---

# 11. USER DATA SAFETY

This is extremely important.

Never package the developer's personal settings into:

* EXE
* ZIP
* installer
* mobile build
* source release

Never commit:

* config.json
* history.json
* logs
* API keys
* credentials
* tokens
* private files
* machine-specific paths

The application must create its configuration in the correct user-specific location at runtime.

A fresh installation must behave like a fresh installation.

Test this explicitly.

---

# 12. CROSS-PLATFORM CONFIGURATION

The configuration system must use platform-appropriate user-data directories.

Do not hardcode:

D:\Python\App-Projects\Capti

Do not assume Windows APPDATA on mobile.

Implement a clean platform-independent configuration abstraction.

The same logical settings should be represented consistently across platforms.

---

# 13. VIDEO / AUDIO PROCESSING

Investigate the current FFmpeg/video-processing architecture.

Determine what can be shared and what needs platform-specific implementation.

Do not assume that the desktop FFmpeg implementation can simply be copied to iOS/Android.

If mobile processing needs:

* bundled native libraries
* platform-specific FFmpeg integration
* server-side processing
* background processing

research the realistic options.

Select an architecture that is actually buildable.

Do not create a fake mobile implementation that only displays screens.

---

# 14. TRANSCRIPTION

Investigate the current Whisper implementation.

Determine:

* where models are stored
* how models are downloaded
* how transcription runs
* memory requirements
* CPU/GPU assumptions
* desktop dependencies
* mobile feasibility

For mobile, choose a technically realistic approach.

If on-device transcription is practical, design for it.

If it is not practical for the target devices, investigate an appropriate alternative architecture.

Do not silently invent an online service.

Do not require users to provide an API key unless explicitly designed and documented.

---

# 15. PERFORMANCE

The application should remain responsive.

Avoid:

* blocking the UI thread
* unnecessary re-rendering
* duplicate timers
* memory leaks
* stale widget references
* unnecessary video copies
* repeated model initialization

For mobile especially:

* handle memory pressure
* handle app backgrounding
* handle interrupted processing
* handle limited storage
* handle large videos

---

# 16. ERROR HANDLING

Errors must be visible and understandable.

Never silently swallow meaningful failures.

Bad:

```python
except Exception:
    pass
```

unless there is a very strong documented reason.

For user-facing failures:

* show a localized message
* preserve the underlying technical error for diagnostics
* avoid crashing the entire application when recovery is possible

---

# 17. INTERNATIONALIZATION

German and English must continue working.

Do not introduce visible raw translation keys.

New user-facing text must use i18n.

Test both languages.

Do not use localized strings as internal identifiers.

---

# 18. TESTING

Testing is mandatory.

Do not remove tests simply to make the suite green.

Add regression tests for every substantial bug fixed.

At minimum test:

* configuration
* settings persistence
* theme
* language
* workflow
* caption styles
* preview
* Pop Scale
* Pop Decay
* navigation
* responsive layout
* mobile business logic
* serialization
* error paths

Before completion:

Run the entire existing test suite.

Then run newly added tests.

Then perform an integration/QA audit.

---

# 19. UI QA

Do not rely exclusively on unit tests.

Where possible, run real UI smoke tests.

Check:

* normal window
* small window
* large window
* navigation
* scrolling
* theme switching
* language switching
* caption preview
* project workflow
* processing
* result

For mobile:

check multiple representative screen sizes/orientations.

---

# 20. GIT SAFETY

Before major changes:

```bash
git status
```

Do not overwrite unrelated user work.

Never use destructive Git commands simply to clean up the workspace.

Before release:

* inspect diff
* inspect tracked files
* scan for secrets
* scan for personal configuration
* verify version
* verify build artifacts
* verify release contents

---

# 21. AUTONOMOUS WORK LOOP

You are explicitly authorized to work for a long period.

Use this loop repeatedly:

### Step 1

Inspect.

### Step 2

Create an implementation plan.

### Step 3

Implement one coherent subsystem.

### Step 4

Run tests.

### Step 5

Analyze failures.

### Step 6

Fix failures.

### Step 7

Run tests again.

### Step 8

Review the implementation for architectural problems.

### Step 9

Continue to the next subsystem.

Do not stop after Step 3.

---

# 22. DO NOT ASK CONSTANT QUESTIONS

Do not interrupt the user for minor decisions.

Use reasonable engineering judgment.

When multiple technically valid solutions exist:

1. prefer the simplest maintainable solution
2. prefer compatibility with the existing architecture
3. prefer shared code
4. prefer offline functionality where practical
5. prefer fewer dependencies
6. prefer robust error handling

Only stop and ask the user when a decision genuinely requires information that cannot reasonably be inferred.

---

# 23. DOCUMENTATION

Update documentation when functionality changes.

Keep:

* README
* release notes
* architecture documentation

consistent with the actual implementation.

Do not leave obvious placeholder descriptions.

---

# 24. BUILD / RELEASE

The release process must produce clean artifacts.

A release must not contain:

* personal config
* personal history
* logs
* development-only files
* .git
* .venv
* temporary files
* test artifacts

The build must work from a clean environment.

Test a fresh installation.

---

# 25. MOBILE DELIVERY

The final mobile implementation should provide a realistic path to:

## Android

A buildable application suitable for Samsung devices.

## iOS

A buildable application suitable for iPhone.

Do not claim iOS support merely because source code theoretically supports iOS.

The final report must distinguish:

* implemented
* tested
* buildable
* not tested due to platform/tooling limitations

If an Apple-specific build requires macOS/Xcode, state that clearly.

---

# 26. PRODUCT QUALITY

The final application should feel like one coherent product.

Avoid:

* prototype-looking screens
* inconsistent buttons
* inconsistent spacing
* duplicate concepts
* confusing navigation
* technical wording exposed to users
* dead controls
* fake functionality
* unfinished placeholders

Reuse the established Capti visual language.

---

# 27. DO NOT OVERENGINEER

Do not introduce unnecessary:

* microservices
* databases
* cloud infrastructure
* authentication
* accounts
* networking
* analytics
* third-party APIs

unless technically necessary and explicitly justified.

Capti should remain as simple as possible while providing the requested functionality.

---

# 28. FINAL ACCEPTANCE CRITERIA

Do not declare the task finished until you have verified:

### Desktop

* application starts
* existing functionality works
* all screens visible
* scrolling works
* responsive layout works
* themes work
* language works
* settings auto-save
* window state persists
* caption preview works
* Pop Scale works
* Pop Decay works
* project workflow works
* processing works
* result export works

### Mobile

* Android architecture/build is real
* iOS architecture/build is real
* UI is touch-friendly
* workflow works
* caption style selection works
* preview works
* processing architecture is real
* export works or has a clearly documented platform limitation
* settings persist correctly

### Security

* no personal config packaged
* no personal history packaged
* no secrets committed
* no machine-specific paths leaked

### Tests

* complete existing test suite passes
* all new regression tests pass
* integration tests pass where available
* fresh-install test passes

---

# 29. FINAL REPORT

At the end, provide a detailed report containing:

1. Summary of work
2. Architecture decisions
3. Files changed
4. Features implemented
5. Desktop status
6. Android status
7. iOS status
8. Tests run
9. Test counts
10. Build results
11. Security/config leak audit
12. Known limitations
13. Remaining work
14. Recommended next steps

Do not hide failures.

Do not claim something is tested if it was not actually tested.

Do not claim something is buildable if it was not actually built.

---

# 30. MOST IMPORTANT RULE

Quality is more important than speed.

You have permission to spend hours inspecting, implementing, testing, debugging, refactoring and verifying.

Do not optimize for finishing the conversation quickly.

Optimize for producing the best technically realistic version of Capti that can actually be maintained and released.

When you encounter an existing bug while working on the task:

* determine whether it is related
* fix it if it is within the mission
* add a regression test
* verify that the fix does not introduce a regression

When you encounter an unrelated issue:

* do not randomly modify it
* document it in the final report

The final result must be based on the actual repository state, not assumptions.

## BEGIN MISSION

Start by auditing the repository thoroughly.

Do not immediately rewrite the application.

First understand what already exists.
