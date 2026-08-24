Capti v2.0.0 – Windows
======================

Start
-----
Capti starten durch Doppelklick auf:  Capti.exe

Anforderungen: Windows 10 oder 11 (64-bit).

Erster Start / Sprachmodelle
----------------------------
Capti nutzt lokale KI (faster-whisper) zur Erzeugung der Untertitel.
Beim ersten Start wird das gewÃ¤hlte Whisper-Modell aus dem Internet
heruntergeladen – dafÃ¼r ist eine Internetverbindung erforderlich.

Die Modelle werden lokal im Benutzerprofil gespeichert:
  %USERPROFILE%\.cache\huggingface\hub

UngefÃ¤hre ModellgrÃ¶ÃŸen:
  tiny   ~75 MB
  base   ~145 MB
  small  ~490 MB (Standard)
  medium ~1,5 GB

FFmpeg
------
Ein FFmpeg-Binary ist bereits als Fallback in Capti enthalten.
Falls systemweit ein FFmpeg installiert ist (im PATH), wird dieses
bevorzugt verwendet.

Hinweis: Einige Virenscanner markieren PyInstaller-Anwendungen
gelegentlich fÃ¤lschlich als verdÃ¤chtig. Dies ist ein bekanntes
Fehlverhalten ("false positive").

Konfiguration
-------------
Ihre Einstellungen (Theme, Sprache) werden gespeichert unter:
  %APPDATA%\Capti\config.json

TemporÃ¤re Dateien werden im Ordner "_temp" neben der Anwendung
abgelegt und beim Beenden automatisch gelÃ¶scht.