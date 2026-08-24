# Capti 2.0

Capti ist eine leichtgewichtige Windows-Desktop-App, die Videos und Shorts
per lokaler KI (faster-whisper) automatisch transkribiert und stilvolle,
wortweise animierte Untertitel direkt ins Video einbrennt – ohne Cloud,
ohne API-Keys.

## Features

- **Video-Transkription** lokal mit faster-whisper (tiny/base/small/medium)
- **Automatische Untertitel** mit Word-by-Word-Karaoke-Highlighting
- **Caption-Rendering** als ASS + FFmpeg-Burn-in (adaptives Portrait-/Landscape-Layout)
- **Caption Styles**: Farben, Outline, Shadow, Font, Presets (Capti Default / Clean / Strong)
- **Animierte Caption-Style-Preview** mit echtem Pop Scale / Pop Decay
- **Mehrere Sprachen**: UI auf Deutsch & English, Transkriptionssprache frei wählbar
- **Themes**: Dark, Light und Yellow – live umschaltbar
- **Drag & Drop** sowie Datei-Dialog für die Videoauswahl
- **History** der letzten Verarbeitungen mit Schnellzugriff
- **Auto-Save**: Einstellungen werden sofort übernommen und gespeichert
- **Fensterzustand**: Größe/Position/Maximiert wird gemerkt
- **Responsives UI**: Inhalte zentriert, bei kleinen Fenstern scrollbar

## Installation

### EXE / ZIP (empfohlen)

1. `Capti-v2.0.0-Windows.zip` entpacken
2. `Capti.exe` starten

Windows 10/11 (64-bit). Ein FFmpeg-Binary ist enthalten; beim ersten Start
wird das gewählte Whisper-Modell aus dem Internet geladen und lokal im
Benutzerprofil gespeichert.

### Aus dem Quellcode

```powershell
uv sync
uv run python main.py
```

Tests:

```powershell
uv run python -m unittest discover tests
```

## Nutzung

```text
Neues Projekt
→ Video auswählen (oder hineinziehen)
→ Sprache/Modell auswählen
→ Weiter
→ Caption Style auswählen
→ Verarbeitung starten
→ Ergebnis speichern
```

## Einstellungen

Alle Einstellungen (Name, Theme, Sprache, Standardmodell) werden
**sofort angewendet und automatisch gespeichert** – es gibt keinen
Speichern-Button.

## Konfiguration

Benutzereinstellungen liegen außerhalb des Programms in der
Windows-Benutzerkonfiguration unter `%APPDATA%\Capti\`
(`config.json`, `history.json`). Im Projektverzeichnis selbst werden
keine persönlichen Daten gespeichert.

## Legacy UI

Der alte Vorgänger-Interface bleibt als Kompatibilitätsmodus erhalten und
ist explizit per Umgebungsvariable aktivierbar:

```powershell
$env:CAPTI_LEGACY_UI = "1"
```

Die moderne Oberfläche ist der Standard.

## Entwicklung

```powershell
uv sync                                   # Umgebung
uv run python main.py                     # App starten
uv run python -m unittest discover tests  # Testsuite
uv run python build.py                    # Release-Build (EXE + ZIP)
```

