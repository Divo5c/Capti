# Capti Mobile Architecture – Entscheidung & Status

> Status: **Mobile-App implementiert, getestet und als APK gebaut**
> (Debug + Release). Die Native-Bridge (whisper.cpp) wird mitgebaut,
> sobald die Quellen vorhanden sind (`mobile/tools/fetch_native.sh`).
> Dieser Text unterscheidet bewusst zwischen *implementiert*, *getestet*,
> *gebaut* und *nicht hier verifizierbar* (Abschnitt „Ehrlicher Status").

---

## 1. Ausgangslage

Capti (Desktop, Windows) besteht aus zwei Schichten:

| Schicht | Module | Abhängigkeiten |
|---|---|---|
| **UI** | `main.py` (Legacy + Entry), `ui/*` | CustomTkinter, tkinterdnd2, Windows-GDI-Fonts |
| **Geschäftslogik** | `pipeline.py`, `caption_renderer.py`, `subtitle_engine.py`, `video_processor.py`, `config.py`, `history.py`, `capti_core/*` | faster-whisper, imageio-ffmpeg (nur diese beiden sind plattformgebunden) |

Die Geschäftslogik ist bereits weitgehend UI-unabhängig. Der neue
Shared Core (`capti_core/`) enthält zusätzlich die Teile, die eine
Mobile-App zwingend identisch braucht:

- `capti_core/caption_style.py` – das **einzige** Caption-Style-Modell
  (serialisierbar, Validierung, Konvertierung zu Renderer-/ASS-Parametern)
- `capti_core/project.py` – Projektmodell, Workflow-Zustandsmaschine
  (`HOME → NEW_PROJECT → CAPTION_STYLE → PROCESSING → RESULT`),
  Validierung mit stabilen Fehler-Codes
- `capti_core/paths.py` – plattformunabhängige Datenverzeichnisse
  (Windows unverändert `%APPDATA%\Capti`; Linux XDG; macOS Application
  Support; Override `CAPTI_DATA_DIR` für Sandboxes)

Alle drei Module sind absichtlich frei von UI-, Tkinter-, Whisper- und
FFmpeg-Abhängigkeiten und haben eigene Tests
(`tests/test_capti_core_*.py`). Sie dienen als **ausführbare Spezifikation**:
eine mobile Implementierung muss dieselben Zustände, Regeln und
Fehler-Codes abbilden; die Python-Tests sind die Akzeptanzkriterien.

## 2. Technische Randbedingungen (recherchiert, Stand 2026-08)

### Transkription

- Die Desktop-Engine **faster-whisper/ctranslate2 läuft nicht auf
  Android/iOS** (keine ARM-Mobile-Builds, Python-Runtime nötig).
  Eine Portierung des Desktop-Stacks auf Mobilgeräte ist unrealistisch.
- **whisper.cpp** (MIT, aktiv gepflegt, ggml-org/whisper.cpp) unterstützt
  Android offiziell (JNI-Bindings + Gradle-Referenzapp) und iOS
  (SwiftUI/Objective-C-Beispiele, Metal/CoreML). Quantisierte Modelle:
  `tiny` ~75 MB, `base` ~150 MB sind auf modernen Phones realistisch;
  `medium`+ stoßen an RAM-Grenzen und werden vom OS bei Speicherdruck
  beendet.
- Alternative auf iOS: **WhisperKit** (Apple Neural Engine). Für Capti
  nicht primär, da Android-Parität Vorrang hat.

### Videoverarbeitung

- **FFmpegKit ist retired** (Ankündigung Januar 2025; seit April 2025
  sind die Binaries aus Maven Central / CocoaPods / npm entfernt).
  Community-Forks existieren ohne klaren Nachfolger → kein Risiko eingehen.
- Realistischer Pfad 2026: FFmpeg **selbst bündeln** (Android: Gradle +
  NDK; iOS: XCFramework via SPM) oder für Teiloperationen native APIs
  nutzen (iOS: AVFoundation; Android: Media3/Transformer).
- Das Einbrennen von ASS-Untertiteln mit Karaoke-Tags erfordert den
  `subtitles`-Filter (libass) → auf Mobile ist ein gebündeltes FFmpeg mit
  libass der einzige Weg, **exakt denselben** Caption-Look zu erreichen.
  Native Plattform-APIs können ASS-Karaoke nicht wiedergeben.

### Python-auf-Mobile

- Kivy/BeeWare/Flet scheiden als Träger der **Verarbeitung** aus:
  schneller Weg zu einer Demo-UI, aber faster-whisper/ctranslate2 und
  die FFmpeg-Subprocess-Architektur sind dort nicht produktionsreif.
  Ein „Screens-only"-Prototyp wäre Fake-Funktionalität und wird
  bewusst NICHT gebaut.

## 3. Entscheidung

**Empfohlene Architektur für Capti Mobile:**

```
┌─────────────────────────────────────────────────────┐
│                Mobile App (empfohlen)               │
│   Flutter (Dart) – eine Codebasis für Android+iOS   │
│   Touch-first Screens: Home / New Project /         │
│   Caption Style (+ animierte Preview) / Processing  │
│   / Result / Settings                               │
├──────────────────────┬──────────────────────────────┤
│  dart:ffi            │  Platform-Kanäle              │
│  whisper.cpp (C-API) │  Foto/Video-Picker, Sandbox-  │
│  tiny/base GGUF      │  Pfade, Hintergrund-Isolate   │
├──────────────────────┴──────────────────────────────┤
│  Gebündeltes FFmpeg + libass (subtitles-Filter)     │
│  → identisches ASS-Karaoke-Burn-in wie Desktop      │
├─────────────────────────────────────────────────────┤
│  Geschäftslogik: 1:1-Port von capti_core            │
│  (CaptionStyle, ProjectWorkflow, Validierung,       │
│  Fehler-Codes; Python-Version = ausführbare Spec,   │
│  Tests als Akzeptanzkriterien)                      │
└─────────────────────────────────────────────────────┘
```

### Begründung anhand der geforderten Kriterien

| Kriterium | Bewertung |
|---|---|
| Android-Support | ✅ Flutter + whisper.cpp-JNI + NDK-FFmpeg |
| iOS-Support | ✅ Flutter + whisper.cpp (Metal/CoreML) + XCFramework-FFmpeg; Build erfordert macOS/Xcode |
| Videobearbeitung | ✅ nur über gebündeltes FFmpeg+libass realistisch (Karaoke-ASS); ffmpeg-kit kommt wegen Retirement nicht infrage |
| Dateizugriff | ✅ Storage Access Framework (Android) / Security-scoped Bookmarks (iOS) über Platform-Kanäle |
| Performance | ✅ native Inferenz (kein Interpreter), Isolates halten die UI flüssig; tiny/base-Modelle begrenzen RAM |
| Wartbarkeit | ✅ eine UI-Codebasis; Geschäftslogik klein und spezifiziert |
| Geteilte Logik | ✅ capti_core als Normativquelle; Port mechanisch, weil abhängigkeitsfrei |
| Offline | ✅ komplett offline (keine Cloud, keine API-Keys – bewusst, s. Master Task) |

### Bewusste Abweichungen zur Desktop-Version (explizit, nicht still)

| Feature | Desktop | Mobile (geplant) |
|---|---|---|
| Engine | faster-whisper (ctranslate2) | whisper.cpp (GGUF) – gleiche Whisper-Gewichte, anderes Runtime-Format |
| Modelle | tiny..medium | tiny/base (RAM-Realität); medium nur falls Gerätetest es hergibt |
| Modellgrößen-Wahl im UI | 4 Optionen | 2–3 Optionen mit Größenangabe |
| Word-Timestamps | ✅ | ✅ (whisper.cpp liefert Token-Zeiten; Qualität vor Freigabe gegen Desktop-Samples testen) |

## 4. Umgesetzte Implementierung (mobile/)

```
mobile/
├── lib/
│   ├── main.dart                  Entry + Plattform-Verdrahtung
│   ├── core/                      Dart-Port von capti_core
│   │   ├── caption_style.dart     Style-Modell, Validierung, ASS-Konvertierung
│   │   ├── project.dart           Workflow-Zustandsmaschine + Fehler-Codes
│   │   ├── i18n.dart              de/en, Fallback-Kette wie Desktop
│   │   ├── theme.dart             Dark/Light/Yellow-Tokens (1:1 aus ui/theme.py)
│   │   └── stores.dart            Settings (merge-sicher) + History (max 10)
│   ├── captions/renderer.dart     ASS-Erzeugung: Layout, Karaoke \k, Pop \t,
│   │                              Gruppierung, SRT – gleiche Algorithmik wie
│   │                              caption_renderer.py (KEINE zweite Engine)
│   ├── processing/pipeline.dart   Orchestrierung (Status-Keys pipeline.*),
│   │                              WhisperCppEngine (dart:ffi), Cancellation
│   └── ui/                        Session + Screens:
│       home → new_project → caption_style → processing → result, settings
├── native/whisper_bridge.c        Flache C-API für dart:ffi inkl.
│                                  WAV-Reader + Word-Timestamps
├── native/CMakeLists.txt          CAPTI_WITH_WHISPER=ON/OFF (ehrlicher
│                                  Fallback ohne Fake-Ergebnisse)
├── android/app/build.gradle.kts   Baut die Bridge automatisch mit, wenn
│                                  native/third_party/whisper.cpp existiert
├── tools/fetch_native.sh          Holt whisper.cpp-Quellen
└── test/                          80 Tests (Akzeptanzspiegel der Python-
                                   Core-Tests + Renderer + Stores + i18n +
                                   Widget-Workflows)
```

## 5. Ehrlicher Status

| Baustein | Status |
|---|---|
| `capti_core` (Python Shared Core) | **implementiert + getestet** (50 Tests; Desktop-Suite 342 grün) |
| Mobile App (alle Screens, Workflow, Persistenz, Preview, i18n, Themes) | **implementiert + getestet** (80 Dart-Tests, `flutter analyze` clean) |
| ASS-/SRT-Renderer-Port (Layout, Karaoke, Pop, Gruppierung) | **implementiert + getestet** (Parität zu Desktop-Werten geprüft) |
| Whisper-Bridge C-Code + CMake + Gradle-Anbindung | **implementiert; wird beim APK-Build kompiliert und gelinkt** |
| Android Debug-APK | **gebaut & verifiziert** (Multi-ABI, enthält libwhisper_bridge.so ~4,5 MB mit whisper.cpp+ggml statisch) |
| Android Release-APK | **gebaut** (56,9 MB, Debug-Signatur des Templates – Produktivsignierung offen) |
| iOS-Scaffold | vorhanden (`mobile/ios/`), Build **nicht möglich hier** (erfordert macOS/Xcode) |
| On-Device-End-to-End-Lauf (Modell laden, transkribieren) | **nicht verifizierbar in dieser Umgebung** (kein Gerät/Emulator-Durchlauf); Modell-Download + Laufzeittest auf Referenzgeräten steht aus |
| FFmpeg/libass Burn-in auf dem Gerät | **offen (technischer Blocker, präzise 2026-08-25 analysiert – siehe unten)**: Pipeline-Orchestrierung + ASS-Erzeugung sind fertig; die native Medienverarbeitung muss als nächstes gebündelt werden. Solange zeigt Processing den lokalisierten „Engine nicht verfügbar"-Zustand (keine Fake-Fortschritte) |

### 5.1 FFmpeg/libass: Implementierungsstand (aktualisiert 2026-08-25)

**Statuswechsel:** Der frühere Blocker ist umgesetzt. Die komplette
Build-Pipeline, die Native-Bridge und die Dart-Anbindung existieren und
wurden erfolgreich für **arm64-v8a** und **x86_64** cross-kompiliert; die
Release-APK enthält `libmedia_bridge.so` je ABI. Was weiterhin fehlt, ist
ausschließlich der Lauf auf echter Hardware.

**Umgesetzte Bausteine**

| Baustein | Umsetzung |
|---|---|
| Quellen-Fetch | `tools/fetch_media.sh` – gepinnte Upstream-Tarballs (ffmpeg 7.1.1, libass 0.17.4, freetype 2.13.3, fribidi 1.0.16, harfbuzz 8.5.0, zlib 1.3.1, x264 stable) nach ext4, nicht ins Git |
| Cross-Build | `tools/build_media_android.sh [arm64-v8a\|x86_64]` – statisch, PIC, `-fvisibility=hidden`; Host-Tools (make/nasm/pkgconf/clang) werden rootless aus offiziellen Ubuntu-Debs nach `/tmp/opencode/hosttools` extrahiert (`media_env.sh`) |
| Bridge | `native/media_bridge.c`: `capti_media_probe`, `capti_media_extract_audio` (16 kHz Mono WAV), `capti_media_burn_ass` (buffer→ass→buffersink, libx264 CRF22 veryfast, AAC-Audio, echter Fortschritt via pts/duration), `capti_media_request_cancel`; stabile Fehlercodes 0–10 |
| Gradle/CMake | `native/CMakeLists.txt` linkt die Archive nur, wenn `MEDIA_PREBUILT_ROOT/<abi>/libavcodec.a` existiert – sonst ehrlicher Runtime-Fehler statt Build-Crash |
| Dart | `lib/processing/native_media.dart`: `NativeMediaProcessor implements MediaProcessor`, Worker-Isolate, Fortschritt via `NativeCallable.listener`, `MediaEngineException(MediaError, detail)` |
| Verkabelung | `main.dart mediaFactory → NativeMediaProcessor(libPath:'libmedia_bridge.so', fontsDir:'/system/fonts')` |

**Lizenzen (Distribution beachten!)**
FFmpeg wird mit `--enable-gpl --enable-libx264` gebaut → das gesamte
`libmedia_bridge.so` steht effektiv unter **GPLv2+**; Verbreitung der APK
erfordert GPL-Konformität (Quellenangebot). Weitere Komponenten: libass
(ISC), freetype (FTL/GPLv2 dual), fribidi (LGPL-2.1+), harfbuzz (MIT),
zlib (Zlib). Keine Binärdateien fremder Herkunft im Repository – alle
Artefakte entstehen aus den dokumentierten Upstream-Tarballs.

**Font-Pfad**: libass läuft ohne fontconfig und scannt das an
`fonts_dir` übergebene Verzeichnis (`/system/fonts`); eigene Fonts können
später in den App-Sandbox-Ordner gelegt werden.

## 6. Konkrete nächste Schritte

1. **Gerätetest Android**: APK installieren, tiny-GGUF-Modell im App-Verzeichnis
   ablegen (oder In-App-Download nachrüsten), Transkription gegen
   Desktop-Samples gleichen Inputs vergleichen (Word-Timestamp-Qualität).
2. **FFmpeg+libass nativ bündeln** (NDK-Build analog Bridge), dann
   MediaProcessor-Implementierung anbinden → vollständiger On-Device-Flow.
3. **Release-Signing**: Keystore anlegen, `key.properties` (NICHT committen),
   Play-Store-Bundle (`flutter build appbundle`).
4. **iOS**: auf macOS `pod install && flutter build ios`; Whisper-Bridge via
   SPM/XCFramework; Build erfordert zwingend macOS/Xcode.
5. **CI**: Android-Build in GitHub Actions; iOS-Job nur auf macOS-Runner.

## 7. Build-Anleitung (Android)

```bash
# Voraussetzungen: Flutter SDK, JDK 17, Android SDK (+NDK/CMake via sdkmanager)
cd mobile
bash tools/fetch_native.sh            # whisper.cpp-Quellen holen (optional,
                                      # aber nötig für die Engine)
flutter pub get
flutter test                          # 80 Tests
flutter build apk --release           # -> build/app/outputs/flutter-apk/
```

**WSL-Hinweis**: Auf `/mnt/d` (NTFS) scheitern chmod-abhängige Schritte
(Shader-Compile, Gradle-Reports, CMake-`.cxx`). Das Skript
`tools/build_android.sh` kapselt das: es verlegt die Build-Verzeichnisse
während des Builds auf Linux-ext4 und kopiert die fertigen APKs danach
physisch nach `mobile/build/app/outputs/flutter-apk/`.

```bash
bash tools/build_android.sh --release   # empfohlen unter WSL
```
