#!/usr/bin/env bash
# Android-Release-Build für Capti Mobile.
#
# WSL-Besonderheit: Auf /mnt/d (NTFS/DrvFs) schlagen chmod-Aufrufe von
# Flutter/Gradle fehl. Daher zeigt mobile/build während des Builds auf
# ein Linux-ext4-Verzeichnis; nach erfolgreichem Build werden die
# fertigen Artefakte PHYSISCH ins Repository kopiert, damit sie am
# Standardpfad (mobile/build/app/outputs/flutter-apk/) dauerhaft liegen.
#
# Nutzung: bash tools/build_android.sh [--debug]
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="release"
[ "${1:-}" = "--debug" ] && MODE="debug"

REAL_BUILD="${CAPTI_FLUTTER_BUILD_DIR:-/tmp/opencode/capti-flutter-build}"
APK_DIR="$REAL_BUILD/app/outputs/flutter-apk"

# 1) Build-Verzeichnis auf ext4 lenken (falls nicht bereits Symlink)
if [ ! -L build ]; then
    rm -rf build
fi
mkdir -p "$(dirname "$REAL_BUILD")"
ln -sfn "$REAL_BUILD" build
if [ ! -L android/build ]; then
    mkdir -p android
    rm -rf android/build
    ln -sfn "$REAL_BUILD/android-build" android/build
fi

# 2) Bauen
flutter build apk --"$MODE"

# 3) Artefakte physisch ins Repo übernehmen (Symlink durch echten Ordner
#    ersetzen), damit der Standardpfad dauerhaft existiert.
cp "$APK_DIR"/app-"$MODE".apk "$APK_DIR"/app-"$MODE".apk.sha1 /tmp/opencode/
rm build
mkdir -p build/app/outputs/flutter-apk
mv /tmp/opencode/app-"$MODE".apk /tmp/opencode/app-"$MODE".apk.sha1 \
   build/app/outputs/flutter-apk/

echo "Fertig:"
ls -lh build/app/outputs/flutter-apk/
