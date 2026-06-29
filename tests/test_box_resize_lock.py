"""Box edge handles always stretch a single axis (Shift no longer locks ratio).

Aspect-ratio preservation now lives on the *corner* handles via the
selection-scale path (see test_box_scale.py); edge handles are pure
single-axis stretch and ignore modifiers.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.constants import MIN_BOX_SIZE
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


def test_right_edge_changes_width_only():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(40, 0, _EDGE_R)
    assert box.box.w == 240
    assert box.box.h == 100                            # height untouched


def test_bottom_edge_changes_height_only():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(0, 50, _EDGE_B)
    assert box.box.h == 150
    assert box.box.w == 200                            # width untouched


def test_edge_ignores_keep_ratio_flag():
    # keep_ratio is accepted for symmetry but must not lock the ratio.
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(40, 0, _EDGE_R, keep_ratio=True)
    assert box.box.w == 240
    assert box.box.h == 100


def test_corner_path_is_free_per_axis():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(40, 60, _CORNER_BR)
    assert box.box.w == 240
    assert box.box.h == 160                            # both axes independent


def test_edge_resize_respects_min_floor():
    view = _view(_SRC)
    box = _box(view)
    box._apply_resize_delta(-1000, 0, _EDGE_R)
    assert box.box.w >= MIN_BOX_SIZE
    assert box.box.h >= MIN_BOX_SIZE
