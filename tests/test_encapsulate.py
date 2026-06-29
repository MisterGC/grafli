"""Ctrl+G encapsulates the selection in a new parent box that contains it."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view._grid_mode = "off"
    view.load_board(parse(src))
    view.resize(1200, 900)
    view._mode = Mode.SELECT
    return view


def _new_box_id(view, before: set[str]) -> str:
    after = {b.id for b in view.board.boxes}
    return next(iter(after - before))


_TWO = """\
#!grafli v2
@ box a "A" 0,0 100x60
@ box b "B" 300,0 100x60
"""


def test_encapsulate_creates_enclosing_parent():
    view = _view(_TWO)
    before = {b.id for b in view.board.boxes}
    view._box_items["a"].setSelected(True)
    view._box_items["b"].setSelected(True)
    view._encapsulate_selection()

    gid = _new_box_id(view, before)
    g = view.board.box_by_id(gid)
    # Both originals are now children of the new box.
    assert view.board.box_by_id("a").parent == gid
    assert view.board.box_by_id("b").parent == gid
    # The new box geometrically encloses both originals.
    assert g.x < 0 and g.y < 0
    assert g.x + g.w > 400
    assert g.y + g.h > 60
    # New box is flagged as a container and is the live selection.
    assert view._box_items[gid]._is_parent is True
    assert view._box_items[gid].isSelected()


def test_encapsulate_single_element():
    view = _view(_TWO)
    before = {b.id for b in view.board.boxes}
    view._box_items["a"].setSelected(True)
    view._encapsulate_selection()
    gid = _new_box_id(view, before)
    assert view.board.box_by_id("a").parent == gid
    assert view.board.box_by_id("b").parent == ""   # untouched


_NESTED = """\
#!grafli v2
@ box p "P" 0,0 400x300
@ box c "C" 40,60 120x80 >p
@ box d "D" 600,0 100x60
"""


def test_encapsulate_preserves_inner_nesting_and_inherits_parent():
    # Selecting p (a parent) and d: only the top-level items reparent; c stays
    # under p. p and d share no common parent, so the new box is top-level.
    view = _view(_NESTED)
    before = {b.id for b in view.board.boxes}
    view._box_items["p"].setSelected(True)
    view._box_items["d"].setSelected(True)
    view._encapsulate_selection()
    gid = _new_box_id(view, before)
    assert view.board.box_by_id("p").parent == gid
    assert view.board.box_by_id("d").parent == gid
    assert view.board.box_by_id("c").parent == "p"   # inner nesting kept
    assert view.board.box_by_id(gid).parent == ""


def test_encapsulate_inherits_common_parent():
    # Two siblings already inside p: their wrapper should also sit inside p.
    view = _view("""\
#!grafli v2
@ box p "P" 0,0 500x400
@ box c1 "C1" 40,60 120x80 >p
@ box c2 "C2" 200,60 120x80 >p
""")
    before = {b.id for b in view.board.boxes}
    view._box_items["c1"].setSelected(True)
    view._box_items["c2"].setSelected(True)
    view._encapsulate_selection()
    gid = _new_box_id(view, before)
    assert view.board.box_by_id(gid).parent == "p"
    assert view.board.box_by_id("c1").parent == gid
    assert view.board.box_by_id("c2").parent == gid


def test_encapsulate_noop_without_selection():
    view = _view(_TWO)
    before = {b.id for b in view.board.boxes}
    view._encapsulate_selection()
    assert {b.id for b in view.board.boxes} == before
