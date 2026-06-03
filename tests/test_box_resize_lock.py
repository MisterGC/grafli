"""Aspect-ratio lock (!ratio): resizing a locked box preserves its ratio."""

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
    view.load_board(parse(src))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    return view


_LOCKED = """\
#!grafli v2
@ box a "A" 0,0 200x100 !ratio
"""

_FREE = """\
#!grafli v2
@ box a "A" 0,0 200x100
"""


def _box(view) -> BoxItem:
    return view._box_items["a"]


def test_locked_corner_drag_preserves_ratio():
    view = _view(_LOCKED)
    box = _box(view)
    box._apply_resize_delta(40, 0, _CORNER_BR)   # drag right only
    assert abs(box.box.w / box.box.h - 2.0) < 1e-6   # height followed width
    assert box.box.w == 240


def test_locked_right_edge_grows_height_about_center():
    view = _view(_LOCKED)
    box = _box(view)
    cy = box.box.y + box.box.h / 2
    box._apply_resize_delta(40, 0, _EDGE_R)
    assert abs(box.box.w / box.box.h - 2.0) < 1e-6
    # off-axis grew symmetrically: center stays put
    assert abs((box.box.y + box.box.h / 2) - cy) < 1e-6


def test_locked_bottom_edge_grows_width_about_center():
    view = _view(_LOCKED)
    box = _box(view)
    cx = box.box.x + box.box.w / 2
    box._apply_resize_delta(0, 50, _EDGE_B)       # taller → wider to keep ratio
    assert abs(box.box.w / box.box.h - 2.0) < 1e-6
    assert abs((box.box.x + box.box.w / 2) - cx) < 1e-6


def test_free_box_corner_drag_changes_one_axis():
    view = _view(_FREE)
    box = _box(view)
    box._apply_resize_delta(40, 0, _CORNER_BR)
    assert box.box.w == 240
    assert box.box.h == 100                         # unchanged — no ratio lock


def test_locked_resize_respects_min_floor():
    view = _view(_LOCKED)
    box = _box(view)
    box._apply_resize_delta(-1000, 0, _CORNER_BR)   # shrink hard
    from grafli.constants import MIN_BOX_SIZE
    assert box.box.w >= MIN_BOX_SIZE
    assert box.box.h >= MIN_BOX_SIZE


def test_dim_mode_grow_keeps_ratio_when_locked():
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    view = _view(_LOCKED)
    box = _box(view)
    box.setSelected(True)
    view._box_mode = "dimension"
    evt = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_L,
                    Qt.KeyboardModifier.ShiftModifier, "L")
    view.keyPressEvent(evt)                          # grow width
    assert abs(box.box.w / box.box.h - 2.0) < 1e-6   # height followed
