"""Edge/corner resize with Shift = keep aspect ratio (no persistent flag)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.items import (
    BoxItem,
    _CORNER_BR,
    _EDGE_R,
    _EDGE_B,
)
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view._grid_mode = "off"          # pin off so geometry isn't snapped
    view.load_board(parse(src))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    return view


_SRC = """\
#!grafli v2
@ box a "A" 0,0 200x100
"""


def _box(view) -> BoxItem:
    return view._box_items["a"]


def test_shift_right_edge_keeps_ratio():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(40, 0, _EDGE_R, keep_ratio=True)
    assert abs(box.box.w / box.box.h - 2.0) < 1e-6   # height followed width


def test_shift_corner_keeps_ratio():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(40, 0, _CORNER_BR, keep_ratio=True)
    assert abs(box.box.w / box.box.h - 2.0) < 1e-6
    assert box.box.w == 240


def test_shift_bottom_edge_grows_width_about_center():
    view = _view(_SRC)
    box = _box(view)
    cx = box.box.x + box.box.w / 2
    box._apply_resize_delta(0, 50, _EDGE_B, keep_ratio=True)
    assert abs(box.box.w / box.box.h - 2.0) < 1e-6
    assert abs((box.box.x + box.box.w / 2) - cx) < 1e-6


def test_no_shift_edge_changes_one_axis():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(40, 0, _EDGE_R, keep_ratio=False)
    assert box.box.w == 240
    assert box.box.h == 100                            # unchanged — free resize


def test_no_shift_corner_is_free():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(40, 60, _CORNER_BR, keep_ratio=False)
    assert box.box.w == 240
    assert box.box.h == 160                            # both axes independent


def test_shift_resize_respects_min_floor():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(-1000, 0, _CORNER_BR, keep_ratio=True)
    from grafli.constants import MIN_BOX_SIZE
    assert box.box.w >= MIN_BOX_SIZE
    assert box.box.h >= MIN_BOX_SIZE
