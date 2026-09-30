#!/usr/bin/env bash
# Synthetischer Rotationstest TOP/BOTTOM/LEFT/RIGHT (Samsung-Verifikation).
# Erzeugt zwei MP4-Dateien mit eindeutig lesbarer Orientierung:
#   1) rotation_test_upright.mp4 – physisch 1080x1920, rotation=0, TOP oben
#   2) rotation_test_coded_landscape.mp4 – physisch 1920x1080 + rotate=90 (Display 1080x1920, TOP oben)
# Erwartung nach Capti-Burn-in (beide):
#   - Ausgabe 1080x1920 (9:16), TOP oben, BOTTOM unten, LEFT links, RIGHT rechts
#   - KEIN Kopfstand, KEIN Stretch, KEIN Crop
# Benutzung (Host mit ffmpeg):
#   bash tools/make_rotation_test.sh
#   adb push rotation_test_upright.mp4 /sdcard/Download/
#   adb push rotation_test_coded_landscape.mp4 /sdcard/Download/
# Danach in Capti verarbeiten und Galerie-Ausgabe visuell pruefen.
set -euo pipefail
cd "$(dirname "$0")"
OUTDIR="${1:-.}"
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg nicht gefunden – bitte ffmpeg installieren, dann erneut ausfuehren." >&2
  exit 1
fi
if ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffprobe nicht gefunden – bitte ffmpeg-Paket installieren." >&2
  exit 1
fi
# Gemeinsamer Drawtext-Stil: fette Positionsmarker
DT="fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=120:fontcolor=white:borderw=4:bordercolor=black"
# 1) Upright portrait 1080x1920, 3s, 30fps, TOP oben
ffmpeg -y -f lavfi -i "testsrc2=size=1080x1920:rate=30:duration=3" \
  -vf "drawtext=${DT}:text='TOP':x=(w-text_w)/2:y=120,drawtext=${DT}:text='BOTTOM':x=(w-text_w)/2:y=h-280,drawtext=${DT}:text='LEFT':x=60:y=(h-text_h)/2,drawtext=${DT}:text='RIGHT':x=w-text_w-60:y=(h-text_h)/2,format=yuv420p" \
  -c:v libx264 -preset veryfast -crf 22 "$OUTDIR/rotation_test_upright.mp4"
# 2) Coded landscape 1920x1080 mit rotate=90 -> Display 1080x1920, TOP oben
ffmpeg -y -f lavfi -i "testsrc2=size=1920x1080:rate=30:duration=3" \
  -vf "drawtext=${DT}:text='TOP':x=(w-text_w)/2:y=120,drawtext=${DT}:text='BOTTOM':x=(w-text_w)/2:y=h-280,drawtext=${DT}:text='LEFT':x=60:y=(h-text_h)/2,drawtext=${DT}:text='RIGHT':x=w-text_w-60:y=(h-text_h)/2,format=yuv420p" \
  -c:v libx264 -preset veryfast -crf 22 -metadata:s:v rotate=90 "$OUTDIR/rotation_test_coded_landscape.mp4"
echo "--- ffprobe upright ---"
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,display_aspect_ratio,codec_name:stream_tags=rotate -of default=noprint_wrappers=1 "$OUTDIR/rotation_test_upright.mp4"
echo "--- ffprobe coded_landscape(+rotate90) ---"
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,display_aspect_ratio,codec_name:stream_tags=rotate -of default=noprint_wrappers=1 "$OUTDIR/rotation_test_coded_landscape.mp4"
# Erwartung Burn-in (Capti):
#   beide -> 1080x1920, TOP oben. Pruefung: ffprobe Ausgabe + visuell in Galerie.
echo "Fertig: $OUTDIR/rotation_test_upright.mp4 + $OUTDIR/rotation_test_coded_landscape.mp4"
