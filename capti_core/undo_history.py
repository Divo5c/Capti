"""Undo/Redo-History (Block 27, Tk-frei).

Kleine Snapshot-History für den Caption-Editor. Speichert unveränderliche
Deep-Copies beliebiger Plain-Data-Snapshots (Dicts/Listen/Primitives –
keine Tk-Objekte, kein Pickle, kein eval).

Semantik:
    A (push) -> B (push) -> C (push)
    undo -> B, undo -> A, undo -> None (leere History-Seite, kein Crash)
    redo -> B -> C; redo am Ende -> None
    Neue Änderung nach Undo verwirft den Redo-Zweig.
    push() identischer States ist ein No-Op (kein leerer Schritt).

Begrenzung: MAX_HISTORY Einträge (älteste fallen weg).
"""

import copy

MAX_HISTORY = 100


class UndoHistory:
    """Lineare Undo/Redo-History über Snapshot-Dicts."""

    def __init__(self, initial=None):
        self._states: list = []
        self._index: int = -1
        if initial is not None:
            self.push(initial)

    def push(self, snapshot) -> bool:
        """Legt einen neuen Stand oben ab (Redo-Zweig verworfen).

        Returns:
            True bei neuem Schritt, False wenn identisch zum Top
            (kein leerer Schritt).
        """
        frozen = copy.deepcopy(snapshot)
        if self._index >= 0 and self._states[self._index] == frozen:
            return False
        del self._states[self._index + 1:]
        self._states.append(frozen)
        if len(self._states) > MAX_HISTORY:
            del self._states[0]
        self._index = len(self._states) - 1
        return True

    def undo(self):
        """Vorheriger Stand (Deep-Copy) oder None (nichts zu tun)."""
        if not self.can_undo:
            return None
        self._index -= 1
        return copy.deepcopy(self._states[self._index])

    def redo(self):
        """Nächster Stand (Deep-Copy) oder None (nichts zu tun)."""
        if not self.can_redo:
            return None
        self._index += 1
        return copy.deepcopy(self._states[self._index])

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self._index < len(self._states) - 1

    @property
    def depth(self) -> int:
        """Anzahl gespeicherter Schritte (für Tests/Diagnose)."""
        return len(self._states)

    def clear(self):
        """Vergisst alle Schritte."""
        del self._states[:]
        self._index = -1
