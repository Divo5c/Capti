#!/usr/bin/env bash
# Lädt die Native-Media-Quellen (FFmpeg + libass + Text-Stack) in
# gepinnten Versionen von den offiziellen Upstream-Servern.
#
#   ffmpeg  7.1.1   https://ffmpeg.org          (LGPL-2.1+; mit --enable-gpl/libx264 -> GPLv2+)
#   libass  0.17.4  https://github.com/libass   (ISC)
#   freetype2       2.13.3  https://freetype.org        (FTL / GPLv2)
#   fribidi         1.0.16  https://github.com/fribidi  (LGPL-2.1+)
#   harfbuzz        8.5.0   https://github.com/harfbuzz (MIT)
#   zlib            1.3.1   https://zlib.net            (Zlib)
#   x264            stable  https://code.videolan.org   (GPLv2+)
#
# Zielordner: $SRC (default /tmp/opencode/media-build/srcs) – NICHT im Repo,
# damit keine fremden Binär-/Quellmassen ins Git gelangen.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1090
source "$here/media_env.sh"

fetch() { # fetch <name> <url>
  local name="$1"
  local url="$2"
  local out="$SRC/$name"
  if [ -d "$out" ] && [ -n "$(ls -A "$out" 2>/dev/null)" ]; then
    echo "== $name bereits vorhanden, überspringe"
    return 0
  fi
  mkdir -p "$out.dl"
  echo "== Lade $name: $url"
  curl -fL --retry 3 -o "$out.dl/$(basename "$url")" "$url"
  case "$url" in
    *.tar.xz) tar -xJf "$out.dl/$(basename "$url")" -C "$out.dl" --strip-components=1 ;;
    *.tar.gz) tar -xzf "$out.dl/$(basename "$url")" -C "$out.dl" --strip-components=1 ;;
    *.tar.bz2) # Host hat kein bzip2-Binary -> Python-tarfile nutzen
      python3 - "$out.dl/$(basename "$url")" "$out.dl" <<'PY'
import sys, tarfile
arc, dest = sys.argv[1], sys.argv[2]
with tarfile.open(arc, 'r:bz2') as t:
    t.extractall(dest, filter='data')
PY
      first="$(find "$out.dl" -mindepth 1 -maxdepth 1 -type d | head -1)"
      mv "$first"/* "$first"/.[!.]* "$out.dl/" 2>/dev/null || true
      rmdir "$first" ;;
    *) echo "Unbekanntes Archivformat: $url" >&2; exit 1 ;;
  esac
  mv "$out.dl" "$out"
}

fetch ffmpeg   https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz
fetch libass   https://github.com/libass/libass/releases/download/0.17.4/libass-0.17.4.tar.xz
fetch freetype https://gitlab.freedesktop.org/freetype/freetype/-/archive/VER-2-13-3/freetype-VER-2-13-3.tar.gz
fetch fribidi  https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz
fetch harfbuzz https://github.com/harfbuzz/harfbuzz/releases/download/8.5.0/harfbuzz-8.5.0.tar.xz
fetch zlib     https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz
fetch x264     https://code.videolan.org/videolan/x264/-/archive/stable/x264-stable.tar.bz2

echo "Alle Media-Quellen bereit unter: $SRC"
ls -1 "$SRC"
