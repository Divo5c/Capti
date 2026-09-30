"""
Modul für Word-by-Word-Caption-Rendering als ASS-Datei.
Nutzt ASS-Karaoke-Tags für zeitlich exaktes Wort-Highlighting,
basierend auf den Word-Timestamps von faster-whisper.
"""

import logging
from types import MappingProxyType
from typing import List

from capti_core.render_model import RenderCaption, RenderWord, assign_lines

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Layout-Grenzen für extreme Videoformate (Phase 20/21-Audit)
# Normale Formate (720x1280, 1080x1920, 1920x1080) bleiben unverändert.
# ---------------------------------------------------------------------
MIN_FONT_SIZE = 12          # absolute Untergrenze (Lesbarkeit)
MAX_FONT_RATIO = 0.08       # Font nie größer als 8 % der Videohöhe
MAX_CHARS_PER_LINE = 60     # verhindert unrealistisch breite Zeilen bei Ultra-Wide

# Sicherer Fallback-Dauer für Words ohne jegliche Zeitinformation.
# 0.2 s ist deutlich über der ASS-Zentisekunden-Auflösung und erzeugt
# keine übermäßig langen Phantom-Anzeigen.
MIN_WORD_DURATION = 0.2

# Minimale Dialogue-Dauer in Sekunden (ASS-Auflösung: Zentisekunden)
MIN_DIALOGUE_DURATION = 0.01


def escape_ass_text(text: str) -> str:
    """Escapet Transkript-/Usertext für ASS-Dialogue-Zeilen (Block 11).

    Nur für USER-TEXT verwenden – NIEMALS auf bereits erzeugte
    Override-/Karaoke-Tags anwenden (die bleiben roh/valide):
        \\  ->  \\\\  (Backslash zuerst – sonst Doppel-Escaping)
        {   ->  \\{
        }   ->  \\}
    Unicode/Umlaute bleiben unverändert. Leere/fehlende Werte -> "".
    """
    if not text:
        return ""
    return str(text).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _valid_time_range(start, end) -> bool:
    """True, wenn end numerisch gültig und echt größer als start ist."""
    try:
        return end is not None and float(end) > float(start)
    except (TypeError, ValueError):
        return False


def normalize_word_timestamps(words: List[dict], fallback_end=None) -> List[dict]:
    """
    Füllt fehlende oder ungültige Word-End-Timestamps robust auf.

    Priorität (vorhandene Zeitinformation wird bevorzugt):
        1. Gültiges word.end bleibt exakt unverändert.
        2. Start des nächsten Words (falls größer als word.start).
        3. Übergeordnetes Segment-Ende (falls gültig).
        4. Sicherer Fallback: start + MIN_WORD_DURATION.

    Garantien: niemals end <= start, keine negativen Dauern,
    konsistente Karaoke-Intervalle. Kopiert die Word-Dicts, um die
    Eingabedaten nicht zu verändern.

    Args:
        words: Liste von Word-Dicts (start, [end], word)
        fallback_end: Optionales Segment-Ende als letzte Info-Quelle

    Returns:
        Neue Liste von Word-Dicts mit garantiert gültigen Ends
    """
    normalized: List[dict] = []
    n = len(words)
    for i, raw in enumerate(words):
        w = dict(raw)
        try:
            start = float(w["start"])
        except (KeyError, TypeError, ValueError):
            normalized.append(w)  # kaputtes Word unverändert durchreichen
            continue

        if _valid_time_range(start, w.get("end")):
            normalized.append(w)
            continue

        resolved = None
        # 1) Ende aus dem nächsten Word-Start ableiten
        if i + 1 < n:
            try:
                nxt_start = float(words[i + 1]["start"])
                if nxt_start > start:
                    resolved = nxt_start
            except (KeyError, TypeError, ValueError):
                pass
        # 2) Übergeordnetes Segment-Ende
        if resolved is None and _valid_time_range(start, fallback_end):
            resolved = float(fallback_end)
        # 3) Sicherer Fallback
        if resolved is None:
            resolved = start + MIN_WORD_DURATION

        w["end"] = resolved
        normalized.append(w)
    return normalized


def _coerce_karaoke_words(words, seg_start: float, seg_end):
    """Löst Wortzeiten exakt nach der Legacy-Regel auf.

    Returns:
        Liste von (text, start, end, next_start)-Tupeln. Wirft bei
        kaputten Wörtern dieselben Exceptions wie bisher (kein Stillhalten).
    """
    coerced = []
    n = len(words)
    for i, w in enumerate(words):
        word_start = float(w["start"])
        word_end = float(w.get("end", word_start))
        if i + 1 < n:
            try:
                next_start = float(words[i + 1]["start"])
            except (KeyError, TypeError, ValueError):
                next_start = word_end
        else:
            next_start = float(seg_end) if _valid_time_range(word_start, seg_end) else word_end
        coerced.append((w["word"], word_start, word_end, next_start))
    return coerced


def _render_karaoke_parts(coerced, seg_start: float, *, pop_enabled: bool,
                          pop_scale: int, pop_decay_ms: int):
    """Baut Karaoke-Parts + Wortlängen mit exakt der Legacy-Mathematik.

    Usertext wird escapet, Renderer-Tags (\\k, \\t) bleiben roh.
    Returns:
        (parts, word_lengths) für den Zeilenumbruch.
    """
    parts = []
    word_lengths = []
    for text, word_start, word_end, next_start in coerced:
        # Karaoke-Dauer immer positiv halten (min. 1 Zentisekunde)
        duration_cs = max(1, int(round((max(next_start, word_end) - word_start) * 100)))

        # Pop/Scale-Effekt: \\t-Zeiten sind ms relativ zum Dialogue-Start.
        # Hochskalieren während das Wort gesprochen wird, danach zurück auf 100 %.
        t_up = max(0, int(round((word_start - seg_start) * 1000)))
        t_down = max(t_up + 1, int(round((word_end - seg_start) * 1000)))
        t_back = t_down + pop_decay_ms
        pop_tag = (
            f"{{\\t({t_up},{t_down},\\fscx{pop_scale}\\fscy{pop_scale})"
            f"\\t({t_down},{t_back},\\fscx100\\fscy100)}}"
            if pop_enabled else ""
        )
        parts.append(f"{{\\k{duration_cs}}}{pop_tag}{escape_ass_text(text)}")
        word_lengths.append(len(text))
    return parts, word_lengths


def _join_karaoke_lines(parts, word_lengths, max_words_per_line: int,
                        chars_per_line=None) -> str:
    """Verteilt Karaoke-Wörter auf maximal 2 Zeilen (Export-Regel).

    Identische Logik wie CaptionRenderer._apply_line_breaks (Wortlimit,
    dann Zeichenbudget); die Methode delegiert hierher.
    """
    n = len(parts)
    lengths = word_lengths if word_lengths else [0] * n
    max_per_line = max(1, max_words_per_line)
    chars_limit = chars_per_line

    # Größtes erstes-Zeilen-Ende finden, das beide Limits einhält
    cut = n
    word_count = 0
    char_acc = 0
    for i in range(n):
        add_chars = lengths[i] + (1 if i > 0 else 0)
        if word_count >= max_per_line:
            cut = i
            break
        if chars_limit is not None and i > 0 and char_acc + add_chars > chars_limit:
            cut = i
            break
        word_count += 1
        char_acc += add_chars

    if cut >= n:
        return " ".join(parts)

    return "\\N".join([
        " ".join(parts[:cut]),
        " ".join(parts[cut:])
    ])


def _captions_for_ass(segments, style: dict, layout: dict):
    """Baut RenderCaption-Liste für den ASS-Adapter (Block 17).

    Byte-Identitäts-Regeln (exakt wie die Legacy-Schleife in generate_ass):
    - Style wird ROH übernommen (ASS-Farben, KEIN from_dict – das würde
      &H-Farben auf Defaults zurücksetzen).
    - Wörter werden mit der Legacy-Regel (_coerce_karaoke_words) aufgelöst,
      NICHT normalisiert (normalize würde degenerierte Fälle anders lösen).
    - Ungültige Segmente werden übersprungen (mit identischer Warnung).
    """
    captions = []
    for segment in segments:
        try:
            seg_start = float(segment["start"])
            seg_end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Segment ohne gültige Zeiten übersprungen")
            continue
        words = segment.get("words") or []
        coerced = _coerce_karaoke_words(words, seg_start, segment.get("end")) \
            if words else []
        captions.append(RenderCaption(
            text=segment.get("text", ""),
            words=tuple(
                RenderWord(word=text, start=start, end=end)
                for text, start, end, _next in coerced),
            start=seg_start,
            end=seg_end,
            style=MappingProxyType(dict(style)),
            layout=MappingProxyType(dict(layout)),
            lines=assign_lines(
                [RenderWord(word=text, start=start, end=end)
                 for text, start, end, _next in coerced],
                int(layout.get("max_words_per_line", 5)),
                layout.get("chars_per_line")),
        ))
    return tuple(captions)


def ass_from_captions(captions) -> list[str]:
    """Serialisiert RenderCaptions zu ASS-Dialogue-TEXTEN (Block 17).

    Liest Pop-Parameter und Limits aus den Caption-Snapshots (dort liegen
    exakt die Werte, die generate_ass() auch direkt verwenden würde).
    Leere Texte -> "" (Aufrufer überspringt wie bisher).
    """
    texts = []
    for cap in captions:
        st = cap.style
        lo = cap.layout
        if not cap.words:
            texts.append(escape_ass_text(cap.text))
            continue
        try:
            pop_enabled = bool(st.get("pop_enabled", True))
            pop_scale = int(st.get("pop_scale", 112))
            pop_decay = int(st.get("pop_decay_ms", 150))
            max_per_line = int(lo.get("max_words_per_line", 5))
        except (TypeError, ValueError):
            pop_enabled, pop_scale, pop_decay, max_per_line = True, 112, 150, 5
        chars_limit = lo.get("chars_per_line")
        raw = [{"word": w.word, "start": w.start, "end": w.end}
               for w in cap.words]
        coerced = _coerce_karaoke_words(raw, cap.start, cap.end)
        parts, lens = _render_karaoke_parts(
            coerced, cap.start,
            pop_enabled=pop_enabled, pop_scale=pop_scale,
            pop_decay_ms=pop_decay)
        texts.append(_join_karaoke_lines(parts, lens, max_per_line, chars_limit))
    return texts


class CaptionRenderer:
    """
    Rendert Transkriptions-Segmente mit Word-Timestamps als ASS-Untertitel.

    Highlight-Mechanismus:
        ASS-Karaoke-Tags ({\\k<Zentisekunden>}) pro Wort.
        - SecondaryColour = Normal-Zustand (noch nicht gesprochen)
        - PrimaryColour   = Highlight-Zustand (gesprochen/aktiv)

    Die Farben sind bewusst einfache Konstruktor-Parameter und können später
    durch ein dediziertes Style-System ersetzt werden.
    """

    def __init__(
        self,
        normal_color: str = "&H00FFFFFF",      # Weiß (BGR in ASS)
        highlight_color: str = "&H0000FFFF",   # Gelb (BGR in ASS)
        outline_color: str = "&H00101010",     # Fast Schwarz (dunkle Outline)
        shadow_color: str = "&H80000000",      # Halbtransparentes Schwarz
        font_name: str = "Arial Black",        # Fett, überall auf Windows verfügbar
        font_size: int = 68,                   # Relativ zu PlayResY=1280 (skaliert mit)
        margin_v: int = 280,                   # Safe Area für Shorts/Reels/TikTok-UI
        max_words_per_line: int = 5,           # Max. Wörter pro Zeile (max. 2 Zeilen)
        pop_scale: int = 112,                  # Pop-Effekt: Skalierung des aktiven Worts (%)
        pop_decay_ms: int = 150,               # Pop-Effekt: Rückanimation nach Wortende (ms)
        pop_enabled: bool = True               # Pop-Effekt ein/aus
    ):
        self.normal_color = normal_color
        self.highlight_color = highlight_color
        self.outline_color = outline_color
        self.shadow_color = shadow_color
        self.font_name = font_name
        self.font_size = font_size
        self.margin_v = margin_v
        self.max_words_per_line = max_words_per_line
        self.pop_scale = pop_scale
        self.pop_decay_ms = pop_decay_ms
        self.pop_enabled = bool(pop_enabled)

    @staticmethod
    def compute_layout(video_width: int, video_height: int) -> dict:
        """
        Berechnet das Caption-Layout abhängig von Videoauflösung und Seitenverhältnis.

        Landscape behält den bisherigen Look (proportional zu PlayResY=1280),
        Portrait passt Fontgröße, Wortanzahl pro Zeile und Safe Area an die
        begrenzte Breite an.

        Returns:
            Dict mit format, play_res_x, play_res_y, font_size,
            max_words_per_line, margin_v, chars_per_line
        """
        aspect = video_width / video_height if video_height else 1.0
        if aspect < 1.0:
            # Portrait / Shorts (z.B. 1080x1920, 720x1280)
            font_size = max(36, int(round(min(video_width, video_height) * 0.062)))
            margin_v = int(video_height * 0.20)
            max_words_per_line = 4
        else:
            # Landscape (z.B. 1920x1080, 1280x720) – bisheriger Look
            font_size = max(24, int(round(video_height * 68 / 1280)))
            margin_v = int(video_height * 280 / 1280)
            max_words_per_line = 5

        # Grenzfälle: sehr kleine Videos -> Font relativ zur Höhe begrenzen
        # (trifft normale Formate nicht: dort liegt der Font deutlich unter 8 %)
        font_size = max(MIN_FONT_SIZE, min(font_size, int(video_height * MAX_FONT_RATIO)))

        # Geschätzte Zeichen pro Zeile aus verfügbarer Breite und Fontgröße;
        # hartes Maximum gegen unrealistisch breite Zeilen bei Ultra-Wide
        usable_width = video_width * 0.88
        avg_char_width = font_size * 0.58
        chars_per_line = max(10, min(MAX_CHARS_PER_LINE,
                                     int(usable_width / avg_char_width)))

        return {
            "format": "portrait" if aspect < 1.0 else "landscape",
            "play_res_x": video_width,
            "play_res_y": video_height,
            "font_size": font_size,
            "max_words_per_line": max_words_per_line,
            "margin_v": margin_v,
            "chars_per_line": chars_per_line,
        }

    @staticmethod
    def format_ass_time(seconds: float) -> str:
        """
        Konvertiert Sekunden in ASS-Zeitformat (H:MM:SS.cc).

        Rundet mathematisch korrekt auf Zentisekunden (C7): Überläufe
        werden weitergetragen (z.B. 0.999 -> 0:00:01.00 statt bisher
        fälschlich 0:00:00.99), Minuten-/Stundenüberlauf inklusive.
        Das Ergebnis enthält dadurch niemals ungültige ".100".
        Negative/ungültige Eingaben -> 0:00:00.00 (niemals Crash).

        Args:
            seconds: Zeit in Sekunden

        Returns:
            Zeitstring im ASS-Format
        """
        try:
            total_cs = round(max(0.0, float(seconds)) * 100)
        except (TypeError, ValueError):
            total_cs = 0
        hours, rem = divmod(total_cs, 360000)
        minutes, rem = divmod(rem, 6000)
        secs, centis = divmod(rem, 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    def _build_karaoke_text(self, segment: dict) -> str:
        """
        Baut die Karaoke-Dialogue-Zeile für ein Segment.

        Die Dauer jedes Karaoke-Tags basiert auf dem tatsächlichen Start des
        nächsten Wortes (bzw. Segmentende beim letzten Wort) – nicht auf
        gleichmäßig verteilten Intervallen. Usertext (Wörter/Segmenttext)
        wird via escape_ass_text() escapet; Renderer-Tags (\\k, \\t) bleiben
        roh und valide.

        Delegiert an den Shared Core (_coerce_karaoke_words +
        _render_karaoke_parts); keine eigene Mathematik mehr hier.

        Args:
            segment: Segment-Dict mit "start", "end" und "words"

        Returns:
            Dialogue-Text mit Karaoke-Tags
        """
        words = segment.get("words") or []
        if not words:
            return escape_ass_text(segment.get("text", ""))

        seg_start = float(segment["start"])
        seg_end = segment.get("end")
        coerced = _coerce_karaoke_words(words, seg_start, seg_end)
        parts, word_lengths = _render_karaoke_parts(
            coerced, seg_start,
            pop_enabled=self.pop_enabled,
            pop_scale=self.pop_scale,
            pop_decay_ms=self.pop_decay_ms)

        return self._apply_line_breaks(parts, word_lengths)

    def _apply_line_breaks(self, parts: List[str], word_lengths: List[int] = None) -> str:
        """
        Verteilt die Karaoke-Wörter auf maximal 2 Zeilen.

        Berücksichtigt sowohl max_words_per_line als auch eine geschätzte
        Zeichenbreite (chars_per_line), da Wörter unterschiedlich lang sind.
        Delegiert an _join_karaoke_lines (Shared Core, keine eigene Logik).

        Args:
            parts: Liste von Karaoke-Wort-Strings
            word_lengths: Optionale Liste der reinen Wortlängen

        Returns:
            Zeilen als String, verbunden mit ASS-Zeilenumbruch \\N
        """
        return _join_karaoke_lines(
            parts, word_lengths,
            max_words_per_line=self.max_words_per_line,
            chars_per_line=getattr(self, "chars_per_line", None))

    def generate_ass(
        self,
        segments: List[dict],
        output_path: str,
        video_width: int = None,
        video_height: int = None
    ) -> str:
        """
        Generiert eine ASS-Datei mit Word-by-Word-Highlighting.

        Args:
            segments: Liste von Segment-Dicts (start, end, text, words)
            output_path: Pfad für die Ausgabedatei
            video_width: Echte Videobreite (optional, für adaptives Layout)
            video_height: Echte Videohöhe (optional, für adaptives Layout)

        Returns:
            Pfad zur generierten ASS-Datei
        """
        logger.info(f"Generiere ASS-Datei: {output_path}")

        # Adaptives Layout – Fallback: bisherige feste Werte (720x1280)
        if video_width and video_height:
            layout = self.compute_layout(video_width, video_height)
            play_res_x = layout["play_res_x"]
            play_res_y = layout["play_res_y"]
            font_size = layout["font_size"]
            margin_v = layout["margin_v"]
            self.max_words_per_line = layout["max_words_per_line"]
            self.chars_per_line = layout["chars_per_line"]
            logger.info(
                f"Caption-Layout: {layout['format']} ({play_res_x}x{play_res_y}), "
                f"font={font_size}, marginV={margin_v}, "
                f"wörter/zeile={self.max_words_per_line}, zeichen/zeile={self.chars_per_line}"
            )
            layout_snapshot = dict(layout)
        else:
            play_res_x, play_res_y = 720, 1280
            font_size = self.font_size
            margin_v = self.margin_v
            self.chars_per_line = None
            layout_snapshot = {
                "play_res_x": play_res_x, "play_res_y": play_res_y,
                "font_size": font_size, "margin_v": margin_v,
                "max_words_per_line": self.max_words_per_line,
                "chars_per_line": None,
            }

        # Block 17: interne RenderCaptions (rohe ASS-Style-Werte, KEIN
        # from_dict – das würde &H-Farben auf Defaults zurücksetzen).
        style_snapshot = {
            "normal_color": self.normal_color,
            "highlight_color": self.highlight_color,
            "outline_color": self.outline_color,
            "shadow_color": self.shadow_color,
            "font_name": self.font_name,
            "font_size": self.font_size,
            "pop_enabled": self.pop_enabled,
            "pop_scale": self.pop_scale,
            "pop_decay_ms": self.pop_decay_ms,
        }
        captions = _captions_for_ass(segments, style_snapshot, layout_snapshot)
        texts = ass_from_captions(captions)

        header = f"""[Script Info]
Title: Capti Captions
ScriptType: v4.00+
WrapStyle: 2
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{self.font_name},{font_size},{self.highlight_color},{self.normal_color},{self.outline_color},{self.shadow_color},1,0,0,0,100,100,0,0,1,4,1,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        lines = [header]
        for cap, text in zip(captions, texts):
            seg_start, seg_end = cap.start, cap.end
            if not text:
                continue
            # Garantie: Dialogue-Ende immer echt nach dem Start
            if seg_end <= seg_start:
                seg_end = seg_start + MIN_DIALOGUE_DURATION
            start = self.format_ass_time(seg_start)
            end = self.format_ass_time(seg_end)
            lines.append(
                f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{text}"
            )

        newline = chr(10)
        # Block 11: normales UTF-8 ohne BOM (manche ASS-Parser stolpern über BOM)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(newline.join(lines) + newline)

        logger.info(f"ASS-Datei erfolgreich erstellt: {output_path} ({len(segments)} Segmente)")
        return output_path


def create_caption_renderer(**kwargs) -> CaptionRenderer:
    """Factory-Funktion zum Erstellen eines CaptionRenderers."""
    return CaptionRenderer(**kwargs)


# Zentrale Konfiguration der Caption-Gruppierung
GROUPING_DEFAULTS = {
    "pause_threshold": 0.4,   # Sekunden Sprechpause -> neue Gruppe
    "max_words_portrait": 8,  # Sicherheitslimit Wörter pro Gruppe (Portrait)
    "max_words_landscape": 10 # Sicherheitslimit Wörter pro Gruppe (Landscape)
}


def group_caption_segments(
    segments: List[dict],
    layout: dict = None,
    pause_threshold: float = None,
    max_words_per_group: int = None,
    max_chars_per_group: int = None
) -> List[dict]:
    """
    Teilt lange Whisper-Segmente in kurze, natürlich wirkende Caption-Gruppen auf.

    Break-Priorität (erste zutreffende Regel beendet die Gruppe):
        1. Zeichenbudget für maximal 2 Zeilen erreicht
        2. Natürliche Sprechpause zwischen zwei Wörtern (Standard: 0.4 s)
        3. Sicherheitslimit an Wörtern pro Gruppe

    Die Word-Timestamps werden unverändert übernommen – jede Gruppe erhält:
        start = Start des ersten Wortes, end = Ende des letzten Wortes,
        text = zusammengefügter Text, words = exakt die zugehörigen Word-Dicts.

    Args:
        segments: Whisper-Segmente (start, end, text, words)
        layout: Optional Layout-Dict von CaptionRenderer.compute_layout()
                (steuert Portrait/Landscape-Limits und Zeichenbudget)
        pause_threshold: Pausen-Schwelle in Sekunden (überschreibt Default)
        max_words_per_group: Wortlimit pro Gruppe (überschreibt Default)
        max_chars_per_group: Zeichenbudget pro Gruppe (überschreibt Default)

    Returns:
        Liste von gruppierten Segment-Dicts
    """
    defaults = dict(GROUPING_DEFAULTS)
    if pause_threshold is None:
        pause_threshold = defaults["pause_threshold"]

    if layout is not None:
        if max_words_per_group is None:
            max_words_per_group = (
                defaults["max_words_portrait"]
                if layout.get("format") == "portrait"
                else defaults["max_words_landscape"]
            )
        if max_chars_per_group is None:
            # Budget für maximal 2 Zeilen
            max_chars_per_group = int(layout.get("chars_per_line", 24) * 2)

    grouped: List[dict] = []
    for segment in segments:
        words = segment.get("words") or []
        if len(words) <= 1:
            grouped.append(segment)  # nichts zu gruppieren
            continue

        # Fehlende/ungültige Word-Ends VOR der Gruppierung robust auflösen
        # (Kopien – Whisper-Rohdaten bleiben unberührt)
        words = normalize_word_timestamps(words, fallback_end=segment.get("end"))

        current_words: List[dict] = [words[0]]
        current_chars = len(words[0]["word"])

        def _flush():
            text = " ".join(w["word"] for w in current_words)
            grouped.append({
                "start": float(current_words[0]["start"]),
                "end": float(current_words[-1].get("end", current_words[-1]["start"])),
                "text": text,
                "words": list(current_words),
            })

        for prev, nxt in zip(words, words[1:]):
            gap = float(nxt["start"]) - float(prev.get("end", prev["start"]))
            would_exceed_chars = (
                max_chars_per_group is not None
                and current_chars + 1 + len(nxt["word"]) > max_chars_per_group
            )
            reached_word_limit = (
                max_words_per_group is not None
                and len(current_words) >= max_words_per_group
            )

            if gap >= pause_threshold or would_exceed_chars or reached_word_limit:
                _flush()
                current_words = [nxt]
                current_chars = len(nxt["word"])
            else:
                current_words.append(nxt)
                current_chars += 1 + len(nxt["word"])

        _flush()

    return grouped
