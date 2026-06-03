"""Corner-drag scales the selection (size + font) about its bbox; Shift locks ratio."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.items import BoxItem, _CORNER_BR, MIN_SCALE_FONT_PT
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view._grid_mode = "off"
    view.load_board(parse(src))
    view.resize(1400, 1000)
    view._mode = Mode.SELECT
    return view


def _scale(box, corner, cursor, keep=False):
    """Run a full corner-scale gesture to ``cursor`` and commit."""
    box._begin_scale(corner, QPointF(box.box.x, box.box.y))
    box._scale_fx, box._scale_fy = box._scale_factors_for(QPointF(*cursor), keep)
    box._commit_scale()


_ONE = """\
#!grafli v2
@ box a "A" 0,0 200x100 ~20
"""


def test_single_box_corner_scale_grows_size_and_font():
    view = _view(_ONE)
    box = view._box_items["a"]
    box.setSelected(True)
    _scale(box, _CORNER_BR, (400, 200))                # 2x both axes
    assert box.box.w == 400
    assert box.box.h == 200
    assert box.box.textsize == "40"                    # 20 * 2
    assert (box.box.x, box.box.y) == (0, 0)            # anchor (TL) fixed


def test_free_corner_scale_is_non_uniform():
    view = _view(_ONE)
    box = view._box_items["a"]
    box.setSelected(True)
    _scale(box, _CORNER_BR, (400, 150), keep=False)    # fx=2, fy=1.5
    assert box.box.w == 400
    assert box.box.h == 150                             # aspect distorts


def test_shift_corner_scale_keeps_ratio():
    view = _view(_ONE)
    box = view._box_items["a"]
    box.setSelected(True)
    _scale(box, _CORNER_BR, (400, 150), keep=True)     # max(2,1.5)=2 both
    assert box.box.w == 400
    assert box.box.h == 200


def test_corner_scale_down_floors_font():
    view = _view(_ONE)
    box = view._box_items["a"]
    box.setSelected(True)
    _scale(box, _CORNER_BR, (2, 1))                    # shrink hard
    assert int(box.box.textsize) == MIN_SCALE_FONT_PT


_GROUP = """\
#!grafli v2
@ box p "Parent" 0,0 400x300
@ box c "C" 40,60 120x80 >p
"""


def test_group_scale_scales_children_about_shared_pivot():
    view = _view(_GROUP)
    parent = view._box_items["p"]
    child = view._box_items["c"]
    parent.setSelected(True)
    child.setSelected(True)
    cw0 = child.box.w
    # Grab the parent BR corner; selection bbox == parent (child is inside).
    _scale(parent, _CORNER_BR, (200, 150))             # 0.5x
    assert child.box.w < cw0                            # child scaled with group
    # Child stays inside the parent after the group scale.
    p, c = parent.box, child.box
    assert c.x >= p.x - 1 and c.y >= p.y - 1
    assert c.x + c.w <= p.x + p.w + 1
    assert c.y + c.h <= p.y + p.h + 1


def test_group_scale_preserves_relative_position():
    view = _view(_GROUP)
    parent = view._box_items["p"]
    child = view._box_items["c"]
    parent.setSelected(True)
    child.setSelected(True)
    # child offset from pivot (parent TL at 0,0) is (40,60); at 0.5x -> (20,30)
    _scale(parent, _CORNER_BR, (200, 150))
    assert abs(child.box.x - 20) < 1e-6
    assert abs(child.box.y - 30) < 1e-6
