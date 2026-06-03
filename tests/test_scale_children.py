"""Scale children to fit (!fit): shrinking a parent squeezes its subtree."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.items import _CORNER_BR
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(1400, 1000)
    view._mode = Mode.SELECT
    return view


# A !fit parent with two children that fill most of it.
_FIT = """\
#!grafli v2
@ box p "Parent" 0,0 600x400 !fit
@ box c1 "C1" 20,60 200x120 >p
@ box c2 "C2" 320,60 200x120 >p
"""


def test_shrink_parent_squeezes_children():
    view = _view(_FIT)
    parent = view._box_items["p"]
    c1_before = (view._box_items["c1"].box.w, view._box_items["c1"].box.h)
    # Corner-scale the parent down to half size.
    parent.setSelected(True)
    parent._begin_scale(_CORNER_BR, QPointF(600, 400))
    parent._scale_factor = parent._scale_factor_for(QPointF(300, 200))   # 0.5x
    parent._commit_scale()
    c1_after = (view._box_items["c1"].box.w, view._box_items["c1"].box.h)
    assert c1_after[0] < c1_before[0]                 # child shrank
    assert c1_after[1] < c1_before[1]


def test_children_stay_within_parent_after_squeeze():
    view = _view(_FIT)
    parent = view._box_items["p"]
    parent.setSelected(True)
    parent._begin_scale(_CORNER_BR, QPointF(600, 400))
    parent._scale_factor = parent._scale_factor_for(QPointF(330, 220))
    parent._commit_scale()
    p = parent.box
    for cid in ("c1", "c2"):
        c = view._box_items[cid].box
        assert c.x >= p.x - 1
        assert c.y >= p.y - 1
        assert c.x + c.w <= p.x + p.w + 1
        assert c.y + c.h <= p.y + p.h + 1


def test_growing_parent_does_not_scale_children_up():
    view = _view(_FIT)
    parent = view._box_items["p"]
    c1_before = view._box_items["c1"].box.w
    parent.setSelected(True)
    parent._begin_scale(_CORNER_BR, QPointF(600, 400))
    parent._scale_factor = parent._scale_factor_for(QPointF(1200, 800))  # 2x grow
    parent._commit_scale()
    assert view._box_items["c1"].box.w == c1_before    # children unchanged on grow


def test_no_fit_flag_leaves_children_untouched():
    view = _view(_FIT.replace("!fit", ""))
    parent = view._box_items["p"]
    c1_before = view._box_items["c1"].box.w
    parent.setSelected(True)
    parent._begin_scale(_CORNER_BR, QPointF(600, 400))
    parent._scale_factor = parent._scale_factor_for(QPointF(200, 133))
    parent._commit_scale()
    assert view._box_items["c1"].box.w == c1_before    # no !fit → no squeeze


def test_child_font_scales_down_on_squeeze():
    view = _view(_FIT.replace('@ box c1 "C1" 20,60 200x120 >p',
                              '@ box c1 "C1" 20,60 200x120 ~30 >p'))
    parent = view._box_items["p"]
    parent.setSelected(True)
    parent._begin_scale(_CORNER_BR, QPointF(600, 400))
    parent._scale_factor = parent._scale_factor_for(QPointF(300, 200))
    parent._commit_scale()
    assert int(view._box_items["c1"].box.textsize) < 30   # font shrank too


def test_squeeze_method_directly_shrinks_children():
    # The edge-resize and d-mode release paths both call this method.
    view = _view(_FIT)
    parent = view._box_items["p"]
    parent.set_geometry(0, 0, 300, 200)                # parent shrunk
    before = view._box_items["c1"].box.w
    view._squeeze_children_to_fit(parent)
    assert view._box_items["c1"].box.w < before


def test_projected_content_area_smaller_than_frame():
    from PySide6.QtCore import QRectF
    view = _view(_FIT)
    parent = view._box_items["p"]
    frame = QRectF(0, 0, 300, 200)                     # half-size prospective frame
    area = view._projected_content_area(parent, frame)
    assert area is not None
    assert area.width() <= frame.width()
    assert area.height() <= frame.height()
