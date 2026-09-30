"""Capti Render-Modell (Block 16): gemeinsame Renderer-Daten für Preview UND Export.

Beschreibt WAS gerendert werden soll (Text, Wörter, Timing, Style-Snapshot,
Layout, Zeilenzuordnung) – NIEMALS WIE (keine ASS-Tags, kein Tk, kein
Flutter, kein ffmpeg). Adapter (Tk-Preview, Flutter-Painter, ASS-Generator)
konsumieren das Modell; in Block 16 nutzt es noch kein Adapter.

Wiederverwendet statt neu erfunden:
- Style-Normalisierung: capti_core.caption_style.CaptionStyle
- Wort-Normalisierung: caption_renderer.normalize_word_timestamps
- Layout-Mathematik: AUSSERHALB (Aufrufer übergibt compute_layout-Dict –
  keine zweite Layout-Mathematik hier)
- Zeilenregel: spiegelt caption_renderer._apply_line_breaks
  (Wortlimit + Zeichenbudget, max. 2 Zeilen); Parität per Test gepinnt.
- Pop-Fenster: spiegelt die \\t-Zeitformeln aus _build_karaoke_text
  (reine ms-Offsets, KEINE ASS-Tags).
"""

from dataclasses import dataclass, field
from types import MappingProxyType

from capti_core.caption_style import CaptionStyle


@dataclass(frozen=True)
class RenderWord:
    """Ein Wort mit garantiert gültigem Zeitbereich (end > start)."""

    word: str
    start: float
    end: float


@dataclass(frozen=True)
class RenderCaption:
    """Eine renderbare Caption (entspricht später einer ASS-Dialogue-Zeile
    bzw. einem Preview-Timeline-Slot)."""

    text: str
    words: tuple[RenderWord, ...]
    start: float
    end: float
    # Style-Snapshot (MappingProxy über CaptionStyle.to_dict()): spätere
    # Style-Änderungen während eines Renderjobs ändern das Modell nicht.
    style: MappingProxyType
    # Layout-Snapshot (compute_layout-Dict, ebenfalls eingefroren).
    layout: MappingProxyType
    # Zeilenzuordnung als Wort-Indexgruppen, max. 2 Zeilen.
    lines: tuple[tuple[int, ...], ...] = field(default=())


def _snapshot_style(style) -> MappingProxyType:
    """Normalisiert Style -> unveränderlicher kanonischer Snapshot."""
    if isinstance(style, CaptionStyle):
        data = style.to_dict()
    elif isinstance(style, dict):
        data = CaptionStyle.from_dict(style).to_dict()
    else:
        data = CaptionStyle().to_dict()
    return MappingProxyType(dict(data))


def _snapshot_layout(layout: dict | None) -> MappingProxyType:
    """Friert das compute_layout-Dict ein (keine Mathematik hier)."""
    return MappingProxyType(dict(layout) if isinstance(layout, dict) else {})


def assign_lines(words: list[RenderWord], max_words_per_line: int,
                 chars_per_line: int | None = None) -> tuple[tuple[int, ...], ...]:
    """Zeilen als Wort-Indexgruppen (Export-Regel, max. 2 Zeilen).

    Spiegelt caption_renderer._apply_line_breaks (Wortlimit, dann
    Zeichenbudget); dort wird zusätzlich mit " " bzw. "\\N" gejoint –
    hier kommen nur Indexgruppen heraus (backend-neutral).
    """
    n = len(words)
    if n == 0:
        return ()
    max_per_line = max(1, int(max_words_per_line or 1))
    cut = n
    char_acc = 0
    for i, w in enumerate(words):
        add_chars = len(w.word) + (1 if i > 0 else 0)
        if i >= max_per_line:
            cut = i
            break
        if chars_per_line is not None and i > 0 and char_acc + add_chars > chars_per_line:
            cut = i
            break
        char_acc += add_chars
    if cut >= n:
        return (tuple(range(n)),)
    return (tuple(range(cut)), tuple(range(cut, n)))


def pop_windows(caption: RenderCaption) -> tuple[tuple[int, int, int], ...]:
    """Pop-Zeitfenster pro Wort in ms relativ zum Caption-Start.

    Spiegelt die \\t-Zeitformeln aus _build_karaoke_text (t_up/t_down/t_back),
    OHNE ASS-Tags. Leeres Tuple, wenn pop_enabled False ist (Adapter prüfen
    zusätzlich das Flag im Style-Snapshot).
    """
    # Style ist per Konstrukt immer ein Mapping (Factory-Snapshot).
    pop_enabled = bool(caption.style.get("pop_enabled", True))
    if not pop_enabled:
        return ()
    try:
        decay = int(caption.style.get("pop_decay_ms", 150))
    except (TypeError, ValueError):
        decay = 150
    out = []
    for w in caption.words:
        t_up = max(0, round((w.start - caption.start) * 1000))
        t_down = max(t_up + 1, round((w.end - caption.start) * 1000))
        out.append((t_up, t_down, t_down + max(0, decay)))
    return tuple(out)


def pop_state_at(caption: RenderCaption, t_ms: float):
    """Aktiver Wort-Index + Scale-% zum Zeitpunkt t_ms (Block 18).

    Zentrale Ableitung aus RenderCaption (ersetzt doppelte Implementierungen
    in Desktop-Preview und Mobile-`currentPopState`): während des Wortes auf
    Pop-Scale hoch (Rampe ×1.6 wie ASS-\\t), danach linear zurück über
    pop_decay_ms. Pop aus -> nur Highlight, Scale 100. Wortgrenzen werden
    auf ms gerundet (identisch zu pop_windows).

    Returns:
        (aktiver Index|None, Scale-% >= 100.0).
    """
    try:
        t = float(t_ms)
    except (TypeError, ValueError):
        return (None, 100.0)
    try:
        pop_enabled = bool(caption.style.get("pop_enabled", True))
    except Exception:
        pop_enabled = True
    if not pop_enabled:
        for i, w in enumerate(caption.words):
            start = round(w.start * 1000)
            end = round(w.end * 1000)
            if start <= t < end:
                return (i, 100.0)
        return (None, 100.0)
    try:
        target = max(100, int(caption.style.get("pop_scale", 112)))
    except (TypeError, ValueError):
        target = 112
    try:
        decay = max(1, int(caption.style.get("pop_decay_ms", 150)))
    except (TypeError, ValueError):
        decay = 150
    for i, w in enumerate(caption.words):
        start = round(w.start * 1000)
        end = round(w.end * 1000)
        decay_end = end + decay
        if start <= t < decay_end:
            if t < end:
                denom = max(1.0, end - start)
                frac = ((t - start) / denom) * 1.6
                scale = 100 + (target - 100) * min(1.0, max(0.0, frac))
            else:
                denom = max(1.0, decay_end - end)
                frac = min(1.0, (t - end) / denom)
                scale = target - (target - 100) * frac
            return (i, max(100.0, scale))
    return (None, 100.0)


def captions_from_segments(segments, style=None, layout: dict | None = None,
                            video_width: int | None = None,
                            video_height: int | None = None) -> tuple[RenderCaption, ...]:
    """Baut RenderCaptions aus (gruppierten) Transkript-Segmenten.

    Args:
        segments: Liste von Dicts (start, end, text, words mit
            word/start/[end]); fehlende Word-Ends werden über
            normalize_word_timestamps robust aufgelöst (keine neue Logik).
        style: CaptionStyle oder rohes Dict (None -> Defaults).
        layout: compute_layout-Dict ODER None + video_width/video_height
            (Layout wird dann per CaptionRenderer.compute_layout erzeugt –
            es gibt genau EINE Layout-Mathematik; der Import erfolgt lazy,
            damit capti_core importleicht bleibt).
    """
    from caption_renderer import normalize_word_timestamps

    if layout is None and video_width and video_height:
        from caption_renderer import CaptionRenderer
        layout = CaptionRenderer.compute_layout(video_width, video_height)
    style_snap = _snapshot_style(style)
    layout_snap = _snapshot_layout(layout)
    try:
        max_per_line = int(layout_snap.get("max_words_per_line", 5))
    except (TypeError, ValueError):
        max_per_line = 5
    try:
        chars = layout_snap.get("chars_per_line")
        chars_per_line = None if chars is None else int(chars)
    except (TypeError, ValueError):
        chars_per_line = None

    captions = []
    for segment in segments or []:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue  # kaputtes Segment überspringen (wie generate_ass)
        if not end > start:
            continue
        raw_words = segment.get("words") or []
        words = []
        if raw_words:
            for w in normalize_word_timestamps(list(raw_words), fallback_end=end):
                try:
                    words.append(RenderWord(
                        word=str(w["word"]),
                        start=float(w["start"]),
                        end=float(w["end"])))
                except (KeyError, TypeError, ValueError):
                    continue
        text = segment.get("text", "")
        captions.append(RenderCaption(
            text=text if isinstance(text, str) else str(text),
            words=tuple(words),
            start=start,
            end=end,
            style=style_snap,
            layout=layout_snap,
            lines=assign_lines(list(words), max_per_line, chars_per_line),
        ))
    return tuple(captions)


def style_of(caption: RenderCaption) -> dict:
    """Style-Snapshot als normales Dict (für Adapter bequem lesbar)."""
    return dict(caption.style)


def layout_of(caption: RenderCaption) -> dict:
    """Layout-Snapshot als normales Dict (für Adapter bequem lesbar)."""
    return dict(caption.layout)
