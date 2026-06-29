"""Graph-connector thickness scales with the size of the nodes it links."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.constants import (
    ARROW_WIDTH, CONNECTOR_WIDTH_MIN, CONNECTOR_WIDTH_MAX,
)
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


_SRC = """\
#!grafli v2
@ box default "D" 0,0 160x80
@ box big "B" 400,0 800x600
@ box huge "H" 1400,0 2400x1800
@ box small "S" 0,400 40x40
"""


def _w(view, a, b):
    return view._connector_width(view.board.box_by_id(a), view.board.box_by_id(b))


def test_default_box_keeps_baseline_width():
    view = _view(_SRC)
    # min dimension 80 == reference → unchanged from today's flat width.
    assert abs(_w(view, "default", "default") - ARROW_WIDTH) < 1e-6


def test_bigger_nodes_get_thicker_connectors():
    view = _view(_SRC)
    assert _w(view, "big", "big") > _w(view, "default", "default")
    assert _w(view, "huge", "huge") > _w(view, "big", "big")


def test_width_capped_by_smaller_endpoint():
    view = _view(_SRC)
    # A connector to the default box is no heavier than default↔default.
    big_to_default = _w(view, "big", "default")
    assert abs(big_to_default - _w(view, "default", "default")) < 1e-6


def test_width_is_clamped():
    view = _view(_SRC)
    assert _w(view, "small", "small") == CONNECTOR_WIDTH_MIN   # floored
    assert _w(view, "huge", "huge") <= CONNECTOR_WIDTH_MAX     # capped


def test_thicker_connectors_have_proportional_geometry():
    # Smoke: drawing a board with big nodes must not error and produces arrows.
    view = _view("""\
#!grafli v2
@ box big1 "B1" 0,0 800x600
@ box big2 "B2" 1200,0 800x600
@ arrow big1 -> big2 "" ~kind=graph
""")
    view._redraw_arrows()
    assert len(view._arrow_items) >= 1
