"""Caption-Draft-Schicht (Block 21): editierbare Hülle um RenderCaption.

RenderCaption/RenderWord bleiben bewusst immutable und die zentrale
Render-Datenbasis. Edits laufen immer über einen CaptionDraft:

    RenderCaption -> draft_from_caption() -> CaptionDraft
        -> apply_text() -> to_caption() -> RenderCaption (neu)
        -> Preview + (später) ASS-Adapter

Der Draft speichert NIEMALS abgeleitete Werte (keine Lines, keine
Pop-Windows, kein Layout, keine Pixelpositionen) – diese werden bei
to_caption() erneut aus dem Render-Modell abgeleitet. Es gibt genau
EINE Render-Mathematik, EINE Line-Break-Logik, EINE Pop-Logik
(capti_core.render_model).

Timing-Transfer-Regel bei Textänderung (deterministisch, dokumentiert):
- Der neue Text wird an Whitespace in Wörter tokenisiert.
- Per difflib.SequenceMatcher werden unveränderte Wortblöcke erkannt;
  deren Wörter behalten exakt ihre alten Timings.
- Geänderte/eingefügte Wörter teilen sich die Lücke zwischen den
  umgebenden Anker-Zeiten gleichmäßig (links: Caption-Start, rechts:
  Caption-Ende). Jedes neue Wort bekommt mindestens MIN_WORD_DURATION
  (0.04 s); reicht der Platz nicht, wird die Lücke gleichmäßig
  aufgeteilt und end > start per Epsilon-Kaskade garantiert.
- Caption start/end ändern sich durch Text-Edits NIE.
- Leerer Text -> keine Wörter, aber gültige Caption-Spanne.

Word-APIs (Block 25, Tk-frei testbar):
- set_word_timing(index, start, end): Timing-Edit in Caption-Spanne,
  ohne Nachbar-Wörter zu verändern; ungültig -> False, Draft unberührt.
- split_word(index[, parts]): Wort in Teile (proportional zur
  Zeichenanzahl, Spanne bleibt); Auto-Split via Whitespace/Hälften.
- merge_words(index): Nachbarn index+index+1 zu "w1 w2" (start1..end2).

Tk-frei (reine Logik, direkt testbar).
"""

import difflib
import math
from dataclasses import dataclass, field

from capti_core.render_model import RenderCaption, captions_from_segments

MIN_WORD_DURATION = 0.04
_EPS = 1e-6


@dataclass
class CaptionDraft:
    """Editierbarer Entwurf EINER Caption (Plain-Daten, keine Tk-Refs)."""

    text: str = ""
    words: list = field(default_factory=list)  # [{word, start, end}]
    start: float = 0.0
    end: float = 0.0
    style: object = None   # Style-Snapshot (Mapping) – wird durchgereicht
    layout: object = None  # Layout-Snapshot (Mapping) – wird durchgereicht


def draft_from_caption(caption: RenderCaption) -> CaptionDraft:
    """Erzeugt einen Draft aus einer RenderCaption (Kopie, keine Aliase)."""
    return CaptionDraft(
        text=caption.text,
        words=[{"word": w.word, "start": w.start, "end": w.end}
               for w in caption.words],
        start=caption.start,
        end=caption.end,
        style=caption.style,
        layout=caption.layout,
    )


def _tokenize(text: str) -> list[str]:
    """Wörter aus Edit-Text (Whitespace-Split, deterministisch)."""
    if not isinstance(text, str):
        text = str(text)
    return text.split()


def _even_split(count: int, span_start: float, span_end: float) -> list[tuple[float, float]]:
    """Teilt [span_start, span_end) gleichmäßig auf count Wörter auf.

    Garantiert end > start für jedes Wort (Epsilon-Kaskade); klemmt auf
    die Spanne. count <= 0 -> [].
    """
    if count <= 0:
        return []
    span_end = max(span_end, span_start + _EPS)
    total = span_end - span_start
    slot = total / count
    out = []
    for i in range(count):
        s = span_start + i * slot
        e = span_start + (i + 1) * slot
        if not e > s:
            e = s + _EPS
        out.append((s, min(e, span_end) if e > span_end and i < count - 1 else e))
    # Letztes Ende exakt auf span_end, aber > Start halten
    s, _ = out[-1]
    out[-1] = (s, max(span_end, s + _EPS))
    return out


def apply_text(draft: CaptionDraft, new_text: str) -> CaptionDraft:
    """Übernimmt neuen Text in den Draft (Timing-Transfer, s. Modul-Doku).

    Caption start/end bleiben unverändert. Gibt denselben Draft zurück
    (verkettbar); draft.words wird ersetzt.
    """
    new_words = _tokenize(new_text)
    draft.text = new_text if isinstance(new_text, str) else str(new_text)
    old = draft.words or []
    cap_start = draft.start
    cap_end = draft.end
    if not cap_end > cap_start:
        cap_end = cap_start + _EPS
        draft.end = cap_end

    if not new_words:
        draft.words = []
        return draft

    old_tokens = [str(w.get("word", "")) for w in old]
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_words, autojunk=False)
    # Anker: (new_index -> (start, end)) für unveränderte Wörter
    anchors: dict[int, tuple[float, float]] = {}
    for a0, _b0, size in matcher.get_matching_blocks():
        for k in range(size):
            w = old[a0 + k]
            try:
                s, e = float(w["start"]), float(w.get("end", w["start"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not e > s:
                continue
            anchors[_b0 + k] = (s, e)

    timed: list[tuple[float, float] | None] = [None] * len(new_words)
    for idx, se in anchors.items():
        # Anker auf Caption-Spanne klemmen (defensiv, keine negativen Zeiten)
        s = max(cap_start, se[0])
        e = min(cap_end, se[1])
        if not e > s:
            continue  # degenerierter Anker -> wie geändert behandeln
        timed[idx] = (s, e)

    # Lücken zwischen Ankern (inkl. Ränder) gleichmäßig füllen
    i = 0
    n = len(new_words)
    while i < n:
        if timed[i] is not None:
            i += 1
            continue
        j = i
        while j < n and timed[j] is None:
            j += 1
        gap_start = timed[i - 1][1] if i > 0 and timed[i - 1] is not None else cap_start
        gap_end = timed[j][0] if j < n and timed[j] is not None else cap_end
        if not gap_end > gap_start:
            # Keine Lücke (z.B. direkt aufeinanderfolgende Anker):
            # minimaler Slot am Anker-Ende, in Spanne geklemmt.
            gap_end = min(cap_end, gap_start + MIN_WORD_DURATION * (j - i))
            if not gap_end > gap_start:
                gap_start = max(cap_start, gap_end - MIN_WORD_DURATION * (j - i))
        for k, (s, e) in enumerate(_even_split(j - i, gap_start, gap_end)):
            # Mindestdauer wahren, aber Spanne/Anker nicht sprengen
            if e - s < MIN_WORD_DURATION and j < n and timed[j] is not None:
                e = min(s + MIN_WORD_DURATION, timed[j][0])
            if not e > s:
                e = s + _EPS
            timed[i + k] = (max(cap_start, s), min(cap_end, e) if min(cap_end, e) > s else s + _EPS)
        i = j

    draft.words = [
        {"word": tok, "start": s, "end": e}
        for tok, (s, e) in zip(new_words, timed)
    ]
    return draft


def _word_span(draft: CaptionDraft, index: int):
    """(Start, Ende) von Wort index (robust, inkl. fehlender Ends).

    Returns:
        (start, end)-Tupel oder None bei ungültigem Index/Start.
    """
    try:
        word = draft.words[index]
    except (IndexError, TypeError):
        return None
    if not isinstance(word, dict):
        return None
    try:
        start = float(word["start"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        end = float(word.get("end", start))
    except (TypeError, ValueError):
        end = start
    if not end > start:
        # Fallback-Kette: nächster Word-Start -> Caption-Ende.
        nxt = None
        try:
            nxt = float(draft.words[index + 1]["start"])
        except (IndexError, KeyError, TypeError, ValueError):
            nxt = None
        end = nxt if (nxt is not None and nxt > start) else draft.end
        if not end > start:
            return None
    return (start, end)


def _raw_bound(draft: CaptionDraft, index: int, key: str):
    """Roher Float-Wert eines Wortfelds oder None (Block 29)."""
    try:
        word = draft.words[index]
        if not isinstance(word, dict):
            return None
        return float(word[key])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def set_word_timing(draft: CaptionDraft, index: int, start, end) -> bool:
    """Setzt Start/Ende von Wort index (Block 25, erweitert Block 29).

    Regeln: start < end, keine negativen Zeiten, innerhalb der
    Caption-Spanne [draft.start, draft.end], keine Überschneidung mit
    Nachbarwörtern (Berühren ist erlaubt). Andere Wörter werden NICHT
    verändert. Ungültige Eingaben lassen den Draft unberührt.

    Returns:
        True bei Übernahme, False bei Ablehnung.
    """
    span = _word_span(draft, index)
    if span is None:
        return False
    try:
        pos = int(index)
    except (TypeError, ValueError):
        return False
    try:
        new_start = float(start)
        new_end = float(end)
    except (TypeError, ValueError):
        return False
    if not new_end > new_start:
        return False
    if new_start < 0:
        return False
    if new_start < draft.start - _EPS or new_end > draft.end + _EPS:
        return False
    prev_end = _raw_bound(draft, pos - 1, "end") if pos > 0 else None
    next_start = _raw_bound(draft, pos + 1, "start")
    if prev_end is not None and new_start < prev_end - _EPS:
        return False
    if next_start is not None and new_end > next_start + _EPS:
        return False
    draft.words[index] = {"word": str(draft.words[index].get("word", "")),
                          "start": new_start, "end": new_end}
    return True


def split_word(draft: CaptionDraft, index: int, parts=None) -> bool:
    """Teilt Wort index in mehrere Wörter (Block 25, deterministisch).

    Args:
        parts: explizite Teilliste oder None für Auto-Split (Whitespace;
            sonst Zeichenhälften). Explizite Teile müssen das Wort ergeben
            (verkettet oder whitespace-getrennt), sonst Ablehnung.

    Timing: Gesamtspanne S..E bleibt erhalten, Verteilung proportional
    zur Zeichenanzahl (leere Teile verboten); jedes Teil bekommt
    end > start (Epsilon-Kaskade, letztes Ende exakt E).
    draft.text wird aus den Wörtern neu zusammengesetzt.

    Returns:
        True bei Split, False bei Ablehnung (Draft unberührt).
    """
    span = _word_span(draft, index)
    if span is None:
        return False
    word = str(draft.words[index].get("word", ""))
    start, end = span
    start = max(start, draft.start)
    end = min(end, draft.end)
    if not end > start:
        return False
    if parts is None:
        tokens = word.split()
        if len(tokens) >= 2:
            parts = tokens
        elif len(word) >= 2:
            half = len(word) // 2
            parts = [word[:half], word[half:]]
        else:
            return False
    else:
        parts = list(parts)
        if not parts or any(not isinstance(p, str) or not p for p in parts):
            return False
        if "".join(parts) != word and parts != word.split():
            return False
    new_words = _distribute(start, end, parts)
    if new_words is None:
        return False
    draft.words[index:index + 1] = new_words
    draft.text = " ".join(str(w.get("word", "")) for w in draft.words)
    return True


def _distribute(start: float, end: float, parts: list) -> list | None:
    """Verteilt Teile proportional zur Zeichenanzahl auf [start, end).

    Erstes Teil startet exakt bei start, letztes endet exakt bei end,
    jedes mit end > start (Epsilon-Kaskade). None bei unmöglicher Spanne.
    """
    total_span = end - start
    if total_span < len(parts) * _EPS:
        return None
    weights = [max(1, len(p)) for p in parts]
    total_weight = sum(weights)
    bounds = [start]
    acc = 0
    for w in weights[:-1]:
        acc += w
        bounds.append(start + total_span * acc / total_weight)
    bounds.append(end)
    # Epsilon-Kaskade (Rundungsschutz) + exakt E am Ende.
    for i in range(1, len(bounds) - 1):
        bounds[i] = max(bounds[i], bounds[i - 1] + _EPS)
    if bounds[-2] >= end:
        even = _even_split(len(parts), start, end)
        bounds = [start] + [e for _, e in even]
    else:
        bounds[-1] = end
    return [{"word": p, "start": s, "end": e}
            for p, s, e in zip(parts, bounds[:-1], bounds[1:])]


def split_word_at(draft: CaptionDraft, index: int, char_index) -> bool:
    """Teilt Wort index an Zeichenposition char_index (Block 28).

    Beispiel: "Hallo", 2 -> "Ha" + "llo" (Timing proportional, Spanne
    bleibt). Nur 1 <= char_index < len(word) (Zeichen = Codepoints,
    Unicode-sicher); sonst False, Draft unberührt.
    """
    span = _word_span(draft, index)
    if span is None:
        return False
    try:
        word = draft.words[index].get("word", "")
    except (AttributeError, TypeError):
        return False
    if not isinstance(word, str):
        word = str(word)
    if isinstance(char_index, bool):
        return False
    if isinstance(char_index, int):
        ci = char_index
    elif isinstance(char_index, str):
        try:
            ci = int(char_index.strip())
        except (TypeError, ValueError):
            return False
    else:
        return False
    if not 1 <= ci < len(word):
        return False
    start, end = span
    start = max(start, draft.start)
    end = min(end, draft.end)
    if not end > start:
        return False
    new_words = _distribute(start, end, [word[:ci], word[ci:]])
    if new_words is None:
        return False
    draft.words[index:index + 1] = new_words
    draft.text = " ".join(str(w.get("word", "")) for w in draft.words)
    return True


def _neighbor_bound(draft: CaptionDraft, index: int, side: str):
    """Start (rechts) bzw. Ende (links) des Nachbarworts oder None."""
    if side == "left" and index <= 0:
        return None
    try:
        neighbor = draft.words[index - 1] if side == "left" \
            else draft.words[index]
    except (IndexError, TypeError):
        return None
    if not isinstance(neighbor, dict):
        return None
    try:
        return float(neighbor["end"] if side == "left"
                     else neighbor["start"])
    except (KeyError, TypeError, ValueError):
        return None


def insert_word(draft: CaptionDraft, index, word, start=None, end=None) -> bool:
    """Fügt ein Wort an Position index ein (Block 28, deterministisch).

    Wort muss genau ein Token sein (kein/leeres/Whitespace-Wort -> False).
    Timing: explizit (start+end, validiert, ohne Nachbar-Überschneidung)
    oder automatisch (größte freie Lücke: Nachbarlücke bzw. Rand bis
    Caption-Grenze; zu klein -> False). Caption-Spanne und bestehende
    Wörter bleiben unverändert; Draft unberührt bei False.
    """
    words = draft.words
    if not isinstance(words, list):
        return False
    try:
        pos = int(index)
    except (TypeError, ValueError):
        return False
    if not 0 <= pos <= len(words):
        return False
    if not isinstance(word, str) or word.split() != [word]:
        return False
    cap_start, cap_end = draft.start, draft.end
    if not cap_end > cap_start:
        return False
    if (start is None) != (end is None):
        return False  # halb-explizites Timing ist mehrdeutig
    if start is not None:
        try:
            new_start, new_end = float(start), float(end)
        except (TypeError, ValueError):
            return False
        if not new_end > new_start or new_start < 0:
            return False
        if new_start < cap_start or new_end > cap_end:
            return False
        left_end = _neighbor_bound(draft, pos, "left")
        right_start = _neighbor_bound(draft, pos, "right")
        if left_end is not None and new_start < left_end:
            return False
        if right_start is not None and new_end > right_start:
            return False
    else:
        left_end = _neighbor_bound(draft, pos, "left")
        right_start = _neighbor_bound(draft, pos, "right")
        gap_start = left_end if left_end is not None else cap_start
        gap_end = right_start if right_start is not None else cap_end
        if left_end is not None and left_end < cap_start:
            gap_start = cap_start
        if right_start is not None and right_start > cap_end:
            gap_end = cap_end
        if not gap_end > gap_start or \
                gap_end - gap_start < MIN_WORD_DURATION and (
                    left_end is not None and right_start is not None):
            # Zwischen zwei Wörtern ist kein Platz -> ablehnen statt
            # schieben (keine stillen Änderungen an Nachbarn).
            if left_end is not None and right_start is not None:
                return False
            if not gap_end > gap_start:
                return False
        new_start, new_end = gap_start, gap_end
    words.insert(pos, {"word": word, "start": new_start, "end": new_end})
    draft.text = " ".join(str(w.get("word", "")) for w in words)
    return True


def delete_word(draft: CaptionDraft, index) -> bool:
    """Löscht Wort index (Block 28).

    Restliche Timings und Caption-Spanne bleiben erhalten (Lücken dürfen
    bestehen). Leeres Ergebnis (0 Wörter) ist gültig. False bei
    ungültigem Index, Draft unberührt.
    """
    try:
        pos = int(index)
    except (TypeError, ValueError):
        return False
    if not isinstance(draft.words, list) or not 0 <= pos < len(draft.words):
        return False
    del draft.words[pos]
    draft.text = " ".join(str(w.get("word", "")) for w in draft.words)
    return True


def merge_words(draft: CaptionDraft, index: int) -> bool:
    """Verschmilzt Wort index + index+1 (Block 25, nur Nachbarn).

    Text: "w1 w2"; Timing: start=w1.start, end=w2.end (Lücke bleibt
    erhalten). Kein Merge über Caption-Grenzen (nur ein Draft = eine
    Caption). Draft.text wird neu zusammengesetzt.

    Returns:
        True bei Merge, False bei Ablehnung (Draft unberührt).
    """
    try:
        first = draft.words[index]
        second = draft.words[index + 1]
    except (IndexError, TypeError):
        return False
    span1 = _word_span(draft, index)
    span2 = _word_span(draft, index + 1)
    if span1 is None or span2 is None:
        return False
    if not span2[1] > span1[0]:
        return False
    merged = {"word": f"{first.get('word', '')} {second.get('word', '')}",
              "start": span1[0], "end": span2[1]}
    draft.words[index:index + 2] = [merged]
    draft.text = " ".join(str(w.get("word", "")) for w in draft.words)
    return True


def set_caption_timing(draft: CaptionDraft, start, end) -> bool:
    """Setzt Start/Ende der Caption (Block 36).

    Regeln: endliche Zahlen, 0 <= start < end. Alle parsebaren Wörter
    müssen vollständig in der neuen Spanne liegen (Berühren erlaubt,
    _EPS-Toleranz); Wörter werden NIEMALS verschoben oder gestreckt.
    Ungültige Eingaben lassen den Draft vollständig unberührt.

    Returns:
        True bei Übernahme, False bei Ablehnung.
    """
    try:
        new_start = float(start)
        new_end = float(end)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(new_start) or not math.isfinite(new_end):
        return False
    if not new_end > new_start:
        return False
    if new_start < 0:
        return False
    for word in draft.words or []:
        try:
            word_start = float(word["start"])
            word_end = float(word["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(word_start) or not math.isfinite(word_end):
            return False
        if word_start < new_start - _EPS or word_end > new_end + _EPS:
            return False
    draft.start = new_start
    draft.end = new_end
    return True


def snapshot_of_draft(draft: CaptionDraft) -> dict:
    """Draft -> unveränderlicher Plain-Data-Snapshot (Block 27).

    Enthält alles für eine vollständige Wiederherstellung: text, words,
    start, end, style, layout. Style/Layout werden als plain Dicts
    kopiert (MappingProxy ist nicht deepcopy-fähig); keine Tk-Refs.
    """
    return {
        "text": draft.text,
        "words": [{"word": str(w.get("word", "")), "start": w["start"],
                   "end": w["end"]} for w in draft.words],
        "start": draft.start,
        "end": draft.end,
        "style": dict(draft.style) if draft.style else None,
        "layout": dict(draft.layout) if draft.layout else None,
    }


def apply_snapshot(draft: CaptionDraft, snapshot: dict) -> CaptionDraft:
    """Stellt einen Snapshot im Draft wieder her (Block 27, komplett).

    Text, Wortanzahl/-texte/-zeiten, Caption start/end, Style, Layout.
    Gibt denselben Draft zurück (verkettbar).
    """
    snap = snapshot if isinstance(snapshot, dict) else {}
    words = snap.get("words") or []
    draft.text = snap.get("text", "")
    draft.words = [{"word": str(w.get("word", "")), "start": w["start"],
                    "end": w["end"]} for w in words
                   if isinstance(w, dict)]
    draft.start = snap.get("start", draft.start)
    draft.end = snap.get("end", draft.end)
    draft.style = snap.get("style")
    draft.layout = snap.get("layout")
    return draft


def to_caption(draft: CaptionDraft) -> RenderCaption:
    """Erzeugt eine NEUE RenderCaption aus dem Draft (Ableitungen neu).

    Nutzt captions_from_segments (Normalisierung + Zeilenregel aus dem
    Render-Modell); Style-/Layout-Snapshots werden durchgereicht.
    """
    segment = {
        "start": draft.start,
        "end": draft.end,
        "text": draft.text,
        "words": [{"word": w["word"], "start": w["start"], "end": w.get("end")}
                  for w in draft.words],
    }
    # Snapshots als plain Dicts durchreichen (_snapshot_style/_snapshot_layout
    # akzeptieren nur CaptionStyle/dict – kein MappingProxy).
    style = dict(draft.style) if draft.style else None
    layout = dict(draft.layout) if draft.layout else None
    (caption,) = captions_from_segments([segment], style, layout)
    return caption


def to_segment(draft: CaptionDraft) -> dict:
    """Draft als plain Segment-Dict (Whisper-/ASS-Adapter-Format).

    Export-Vorbereitung: so strukturiert, dass es direkt in den
    bestehenden ASS-Adapter (generate_ass) gegeben werden kann.
    """
    return {
        "start": draft.start,
        "end": draft.end,
        "text": draft.text,
        "words": [{"word": w["word"], "start": w["start"], "end": w["end"]}
                  for w in draft.words],
    }


def split_segment(segment: dict, word_index: int):
    """Teilt ein Segment vor Wort `word_index` in zwei Segmente.

    Linker Teil: Wörter [:word_index], Start = Segment-Start, Ende =
    Ende des letzten linken Worts. Rechter Teil: Wörter [word_index:],
    Start = Start des ersten rechten Worts, Ende = Segment-Ende.
    Texte werden aus den jeweiligen Wörtern zusammengesetzt, Timings
    aus den tatsächlichen Wort-Timestamps abgeleitet (kein Re-Timing).
    Beide Hälften werden per set_caption_timing() validiert.

    Gültig nur für 0 < word_index < len(Wörter); sonst None. Das
    Original wird nicht mutiert. Ungültiges/inkonsistentes Input ->
    None (keine Exception).
    """
    try:
        words = segment.get("words") if isinstance(segment, dict) else None
        if not isinstance(words, list) or len(words) < 2:
            return None
        if isinstance(word_index, bool) \
                or not isinstance(word_index, int):
            return None
        k = word_index
        if not 0 < k < len(words):
            return None
        left_words = [dict(w) for w in words[:k]]
        right_words = [dict(w) for w in words[k:]]
        left_end = float(left_words[-1]["end"])
        right_start = float(right_words[0]["start"])
        seg_start = float(segment["start"])
        seg_end = float(segment["end"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        left_text = " ".join(str(w["word"]) for w in left_words)
        right_text = " ".join(str(w["word"]) for w in right_words)
    except (KeyError, TypeError):
        return None
    left = CaptionDraft(
        text=left_text,
        words=left_words, start=seg_start, end=left_end)
    right = CaptionDraft(
        text=right_text,
        words=right_words, start=right_start, end=seg_end)
    if not set_caption_timing(left, seg_start, left_end):
        return None
    if not set_caption_timing(right, right_start, seg_end):
        return None
    return to_segment(left), to_segment(right)
