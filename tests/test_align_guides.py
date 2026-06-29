"""Smart alignment guides during free (drag) move.

The geometry lives in ``GrafliView.snap_drag_pos`` / ``_align_rect_for``: the
lead item of a single-selection drag snaps its edges/centres to nearby peers
(emitting guide lines), with a plain grid-snap fallback. Multi-item drags keep
the relative layout, so alignment is disabled for them.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_BOARD = (
    "#!grafli v1\n"
    '@ box a "A" 0,0 100x50\n'
    '@ box b "B" 400,400 100x50\n'
)


def _view(src: str = _BOARD) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    # Identity zoom so the ~6px threshold maps to 6 scene units, and the
    # content sits inside the viewport-cull used when gathering peers.
    view.resetTransform()
    view.centerOn(QPointF(250, 225))
    return view


def _select_only(view, box_id):
    view._scene.clearSelection()
    view._box_items[box_id].setSelected(True)


def test_align_rect_uses_model_geometry_not_chrome():
    view = _view()
    item = view._box_items["a"]
    item.setSelected(True)   # selection chrome must not inflate the rect
    r = view._align_rect_for(item)
    assert (r.x(), r.y(), r.width(), r.height()) == (0.0, 0.0, 100.0, 50.0)


def test_lead_snaps_edges_to_peer_and_emits_guides():
    view = _view()
    view._grid_mode = "off"
    b = view._box_items["b"]
    _select_only(view, "b")
    view.begin_drag_guides(b)
    # Proposed just 4/3 px off box a's top-left — within the snap threshold.
    out = view.snap_drag_pos(b, QPointF(4, 3))
    assert (out.x(), out.y()) == (0.0, 0.0)
    orients = {g["orient"] for g in view._drag_guides}
    assert orients == {"v", "h"}
    assert all(g["pos"] == 0 for g in view._drag_guides)
    # The guide lines are the feedback — no timed overlay races the drag.
    assert view._flashes == []


def test_no_snap_when_outside_threshold():
    view = _view()
    view._grid_mode = "off"
    b = view._box_items["b"]
    _select_only(view, "b")
    view.begin_drag_guides(b)
    out = view.snap_drag_pos(b, QPointF(40, 80))
    assert (out.x(), out.y()) == (40.0, 80.0)
    assert view._drag_guides == []


def test_grid_fallback_without_alignment():
    view = _view()
    view._grid_mode = "snap"   # grid on, no drag-guide session started
    b = view._box_items["b"]
    out = view.snap_drag_pos(b, QPointF(37, 8))
    assert (out.x(), out.y()) == (40.0, 0.0)   # rounded to GRID_SPACING (20)


def test_multi_select_disables_alignment():
    view = _view()
    view._grid_mode = "off"
    a, b = view._box_items["a"], view._box_items["b"]
    view._scene.clearSelection()
    a.setSelected(True)
    b.setSelected(True)
    view.begin_drag_guides(b)
    out = view.snap_drag_pos(b, QPointF(4, 3))
    assert (out.x(), out.y()) == (4.0, 3.0)   # relative layout preserved
    assert view._drag_guides == []


def test_end_drag_guides_clears_state():
    view = _view()
    view._grid_mode = "off"
    b = view._box_items["b"]
    _select_only(view, "b")
    view.begin_drag_guides(b)
    view.snap_drag_pos(b, QPointF(4, 3))
    assert view._drag_guides
    view.end_drag_guides()
    assert view._drag_guides == []
    assert view._drag_guide_refs is None
    assert view._drag_lead_item is None
