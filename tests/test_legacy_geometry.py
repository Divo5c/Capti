"""Fix-Block 7 (C4): Legacy-Geometry/MinSize-Widerspruch.

Regression: CaptiApp startete mit geometry("800x700") bei minsize(1135, 1160).
Tk clampet dann still auf die Mindestgroesse – der Code log ueber die
tatsaechliche Startgroesse, auf kleinen Displays startet die Legacy-UI
entsprechend ueberraschend gross.

Der Test parst main.py per AST (kein Tk noetig, deterministisch) und fordert:
  initial_width >= min_width und initial_height >= min_height
fuer die Legacy-CaptiApp. Die neue Architektur ist explizit ausgenommen
(eigener Test stellt sicher, dass sie unveraendert bleibt).
"""

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAIN_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")


def _parse_size(text: str):
    """'BxH' -> (B, H); None bei ungueltigem Format."""
    try:
        w, h = text.split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return None


def _legacy_geometry_minsize():
    """Liest (geometry, minsize) aus CaptiApp.__init__ per AST.

    Returns:
        ((init_w, init_h), (min_w, min_h)) – None, wenn nicht auffindbar.
    """
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    geometry = minsize = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "CaptiApp":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                continue
            for stmt in ast.walk(item):
                if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
                    continue
                func = stmt.value.func
                if not isinstance(func, ast.Attribute):
                    continue
                recv = func.value
                if not (isinstance(recv, ast.Attribute) and recv.attr == "root"):
                    continue
                if func.attr == "geometry" and stmt.value.args:
                    arg = stmt.value.args[0]
                    if isinstance(arg, ast.Constant):
                        geometry = _parse_size(arg.value)
                elif func.attr == "minsize" and len(stmt.value.args) >= 2:
                    a, b = stmt.value.args[0], stmt.value.args[1]
                    if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
                        minsize = (int(a.value), int(b.value))
    return geometry, minsize


def _new_arch_minsize_present():
    """True, wenn main() weiterhin minsize(820, 560) fuer die neue Architektur setzt."""
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
                continue
            func = stmt.value.func
            if isinstance(func, ast.Attribute) and func.attr == "minsize":
                args = stmt.value.args
                if (len(args) >= 2 and isinstance(args[0], ast.Constant)
                        and isinstance(args[1], ast.Constant)
                        and args[0].value == 820 and args[1].value == 560):
                    return True
    return False


class TestLegacyGeometry(unittest.TestCase):

    def test_initial_not_smaller_than_minimum(self):
        """C4: Legacy-Startgroesse >= Mindestgroesse (kein stiller Tk-Clamp)."""
        geometry, minsize = _legacy_geometry_minsize()
        self.assertIsNotNone(geometry, "kein geometry()-Aufruf in CaptiApp gefunden")
        self.assertIsNotNone(minsize, "kein minsize()-Aufruf in CaptiApp gefunden")
        init_w, init_h = geometry
        min_w, min_h = minsize
        self.assertGreaterEqual(
            init_w, min_w,
            f"Startbreite {init_w} kleiner als Mindestbreite {min_w}")
        self.assertGreaterEqual(
            init_h, min_h,
            f"Starthoehe {init_h} kleiner als Mindesthoehe {min_h}")

    def test_minsize_sane(self):
        """Minsize bleibt positiv (kein versehentlicher 0-/Negativwert)."""
        _, minsize = _legacy_geometry_minsize()
        self.assertIsNotNone(minsize)
        self.assertGreater(minsize[0], 0)
        self.assertGreater(minsize[1], 0)

    def test_new_arch_untouched(self):
        """Die neue Architektur (minsize 820x560) bleibt unveraendert."""
        self.assertTrue(
            _new_arch_minsize_present(),
            "Neue Architektur veraendert – ausserhalb von C4-Scope")


if __name__ == "__main__":
    unittest.main()
