"""Snap-to-slide-ratio: reshape a container to the PDF slide aspect ratio."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.pdfexport import slide_content_ratio
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    return view


_SRC = """\
#!grafli v2
@ box a "A" 0,0 800x100
@ box b "B" 0,400 600x500
"""


def test_snap_sets_height_to_width_over_ratio():
    view = _view(_SRC)
    ratio = slide_content_ratio(view.board)
    item = view._box_items["a"]
    item.setSelected(True)
    view._snap_selection_to_slide_ratio()
    box = view.board.box_by_id("a")
    assert box.w == 800                                  # width held
    assert abs(box.w / box.h - ratio) < 0.02             # ratio matched
    assert (box.x, box.y) == (0, 0)                      # top-left anchored


def test_snap_is_idempotent():
    view = _view(_SRC)
    view._box_items["a"].setSelected(True)
    view._snap_selection_to_slide_ratio()
    h1 = view.board.box_by_id("a").h
    view._snap_selection_to_slide_ratio()                # re-apply: no change
    assert view.board.box_by_id("a").h == h1


def test_snap_applies_to_multiple_selected():
    view = _view(_SRC)
    ratio = slide_content_ratio(view.board)
    view._box_items["a"].setSelected(True)
    view._box_items["b"].setSelected(True)
    view._snap_selection_to_slide_ratio()
    for bid in ("a", "b"):
        box = view.board.box_by_id(bid)
        assert abs(box.w / box.h - ratio) < 0.02


def test_footer_shifts_the_target_ratio():
    plain = slide_content_ratio(parse(_SRC))
    withft = slide_content_ratio(parse(_SRC + '@ footer "© demo"\n'))
    assert withft > plain                                # footer -> taller box
