#!/usr/bin/env bash
# Holt die whisper.cpp-Quellen als Grundlage für den nativen Build.
# Ausführen VOR einem APK/IPA-Build mit Transkriptions-Engine:
#   mobile/tools/fetch_native.sh [version|commit]
set -euo pipefail

DEST="$(dirname "$0")/../native/third_party/whisper.cpp"
REF="${1:-master}"

mkdir -p "$(dirname "$DEST")"

if [ -d "$DEST/.git" ]; then
    echo "whisper.cpp bereits vorhanden: $DEST"
else
    echo "Klone whisper.cpp (${REF})..."
    git clone --depth 1 --branch "${REF}" \
        https://github.com/ggml-org/whisper.cpp "$DEST"
fi

echo "OK: $DEST"
echo "Hinweis: Für Android wird der Build automatisch eingebunden, sobald"
echo "dieses Verzeichnis existiert (android/app/build.gradle prüft es)."
