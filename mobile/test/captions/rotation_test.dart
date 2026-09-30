import 'package:flutter_test/flutter_test.dart';
import 'package:capti_mobile/captions/renderer.dart';

void main() {
  group('Rotation/Orientation Regression', () {
    test('Portrait 1080x1920 bleibt Portrait (9:16)', () {
      final layout = computeLayout(1080, 1920);
      expect(layout.format, 'portrait');
      expect(layout.playResX, 1080);
      expect(layout.playResY, 1920);
      expect(layout.playResX < layout.playResY, isTrue);
    });

    test('Landscape 1920x1080 bleibt Landscape (16:9)', () {
      final layout = computeLayout(1920, 1080);
      expect(layout.format, 'landscape');
      expect(layout.playResX, 1920);
      expect(layout.playResY, 1080);
      expect(layout.playResX > layout.playResY, isTrue);
    });

    test('Portrait Shorts 720x1280 bleibt Portrait', () {
      final layout = computeLayout(720, 1280);
      expect(layout.format, 'portrait');
      expect(layout.playResX, 720);
      expect(layout.playResY, 1280);
    });

    test('Rotation 90: coded 1920x1080 mit rotate 90 -> display 1080x1920 (swap)', () {
      // Simuliert C-Seite get_rotation -> swapped probe
      // Dart-Seite: probe würde swapped liefern, Layout muss trotzdem portrait sein
      final rotatedW = 1080; // nach Swap
      final rotatedH = 1920;
      final layout = computeLayout(rotatedW, rotatedH);
      expect(layout.format, 'portrait');
      expect(layout.playResX, 1080);
      expect(layout.playResY, 1920);
    });

    test('Keine feste 16:9 Konvertierung – Portrait bleibt 9:16', () {
      final portrait = computeLayout(1080, 1920);
      final landscape = computeLayout(1920, 1080);
      // Sicherstellen, dass nicht beide auf 16:9 normalisiert werden
      expect(portrait.playResX / portrait.playResY, closeTo(9/16, 0.01));
      expect(landscape.playResX / landscape.playResY, closeTo(16/9, 0.01));
    });

    test('Kein Stretch/Crop – PlayRes entspricht Input', () {
      final w = 1080, h = 1920;
      final layout = computeLayout(w, h);
      expect(layout.playResX, w);
      expect(layout.playResY, h);
    });
  });

  group('Native transpose contract (CCW-Semantik, media_bridge.c)', () {
    // Ausführbare Dokumentation des nativen Vertrags (verifiziert via
    // av_display_rotation_get-Doku + transpose-Filter-Doku):
    // CCW 90 -> cclock, CCW 270 -> clock, CCW 180 -> clock+clock, 0 -> kein Filter.
    // Inversion (90->clock) erzeugt gleiche Dimensionen aber KOPFUEBER (180 Fehler).
    String transposeForCcw(int ccw) {
      if (ccw == 90) return 'cclock';
      if (ccw == 270) return 'clock';
      if (ccw == 180) return 'clock+clock';
      return 'none';
    }

    test('CCW 90 -> cclock (nicht clock)', () {
      expect(transposeForCcw(90), 'cclock');
    });

    test('CCW 270 -> clock (nicht cclock)', () {
      expect(transposeForCcw(270), 'clock');
    });

    test('CCW 180 -> clock+clock', () {
      expect(transposeForCcw(180), 'clock+clock');
    });

    test('CCW 0 -> kein transpose', () {
      expect(transposeForCcw(0), 'none');
    });

    test('MP4 rotate-Tag (CW) 90 entspricht CCW 270 -> clock', () {
      // Tag ist CLOCKWISE (ffmpeg cmdutils negiert av_display_rotation_get).
      int tagCwToCcw(int cw) => (360 - (cw % 360)) % 360;
      expect(tagCwToCcw(90), 270);
      expect(transposeForCcw(tagCwToCcw(90)), 'clock');
      expect(tagCwToCcw(270), 90);
      expect(transposeForCcw(tagCwToCcw(270)), 'cclock');
    });

    test('Dimensionen nach transpose bleiben 9:16 (Portrait)', () {
      // Beide Richtungen liefern 1080x1920 aus 1920x1080 – nur Vertikale unterscheidet sich.
      // Darum faellt ein Richtungsfehler im Dimensions-Check NICHT auf (Kopfstand bei gleichen Massen).
      Pair swapForCcw(int ccw, int w, int h) =>
          (ccw == 90 || ccw == 270) ? Pair(h, w) : Pair(w, h);
      expect(swapForCcw(90, 1920, 1080), const Pair(1080, 1920));
      expect(swapForCcw(270, 1920, 1080), const Pair(1080, 1920));
      expect(swapForCcw(0, 1080, 1920), const Pair(1080, 1920));
    });
  });
}

class Pair {
  final int w, h;
  const Pair(this.w, this.h);
  @override
  bool operator ==(Object other) =>
      other is Pair && other.w == w && other.h == h;
  @override
  int get hashCode => Object.hash(w, h);
  @override
  String toString() => 'Pair($w,$h)';
}
