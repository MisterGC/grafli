"""Tests for keyboard zoom anchoring (+/- shortcuts)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SAMPLE = """\
@ box a "A" 0,0 120x60
@ box b "B" 600,400 120x60
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(board):
    app = _app()
    from grafli.view import GrafliView
    v = GrafliView()
    v.resize(800, 600)
    v.show()
    v.load_board(board)
    app.processEvents()
    return v


def test_no_selection_anchors_on_viewport_center():
    board = parse(SAMPLE)
    view = _view(board)
    vp_center = view.viewport().rect().center()
    scene_before = view.mapToScene(vp_center)
    view._zoom_keyboard(1.15)
    # The scene point that was under the viewport center stays under it.
    scene_after = view.mapToScene(vp_center)
    assert abs(scene_after.x() - scene_before.x()) < 1.5
    assert abs(scene_after.y() - scene_before.y()) < 1.5


def test_selection_anchors_on_selected_item():
    board = parse(SAMPLE)
    view = _view(board)
    item = view._box_items["b"]
    item.setSelected(True)
    anchor_scene = item.sceneBoundingRect().center()
    vp_before = view.mapFromScene(anchor_scene)
    view._zoom_keyboard(1.15)
    # The selected item's center stays fixed on screen while the rest scales.
    vp_after = view.mapFromScene(anchor_scene)
    assert abs(vp_after.x() - vp_before.x()) <= 1
    assert abs(vp_after.y() - vp_before.y()) <= 1


def test_zoom_changes_scale():
    board = parse(SAMPLE)
    view = _view(board)
    z0 = view.transform().m11()
    view._zoom_keyboard(1.15)
    assert view.transform().m11() > z0
    view._zoom_keyboard(1 / 1.15)
    assert abs(view.transform().m11() - z0) < 1e-6
