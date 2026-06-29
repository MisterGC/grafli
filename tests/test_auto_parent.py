"""load_board must respect an authored >parent, even for overflowing children.

A note (or box) deliberately wider/taller than its container is still authored
into it. Geometric reparenting on load must not yank it up to a grandparent
that merely encloses its bounds, or container-slide detection in the PDF
exporter breaks.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    return view


# An outer box, a small inner box, and a note authored into the small box but
# rendered wider than it (long single line, narrow box).
_OVERFLOW = """\
#!grafli v2
@ box outer "Outer" 0,0 1200x800
@ box inner "Why OSM?" 40,40 200x120 >outer
@ note cap 50,80 "A fairly long caption line that is wider than the inner box" >inner
"""


def test_authored_parent_survives_load_when_child_overflows():
    view = _view(_OVERFLOW)
    # The note overflows `inner`, but its authored parent must be preserved.
    assert view.board.note_by_id("cap").parent == "inner"


def test_unparented_item_is_still_nested_by_geometry():
    # No authored parent → geometric nesting still applies.
    src = """\
#!grafli v2
@ box outer "Outer" 0,0 600x400
@ note cap 60,60 "short"
"""
    view = _view(src)
    assert view.board.note_by_id("cap").parent == "outer"


def test_dangling_parent_falls_back_to_geometry():
    # Authored parent names a missing box → derive geometrically instead.
    src = """\
#!grafli v2
@ box outer "Outer" 0,0 600x400
@ note cap 60,60 "short" >ghost
"""
    view = _view(src)
    assert view.board.note_by_id("cap").parent == "outer"


def test_self_parent_cycle_is_not_kept():
    # A box authored as its own parent must not be preserved (cycle guard).
    src = """\
#!grafli v2
@ box a "A" 0,0 300x200 >a
"""
    view = _view(src)
    assert view.board.box_by_id("a").parent == ""
