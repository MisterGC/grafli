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


# ── Zoom bounds: content-aware min, fixed max, limit clamp ──────────

def _set_zoom(view, z):
    from PySide6.QtGui import QTransform
    view.setTransform(QTransform().scale(z, z))


def test_zoom_bounds_are_content_aware_min_and_fixed_max():
    view = _view(parse(SAMPLE))
    lo, hi = view._zoom_bounds()
    assert hi == view.MAX_ZOOM == 5.0
    assert view.MIN_ZOOM_ABS < lo <= 1.0        # never forced above 100%


def test_zoom_in_blocked_at_max():
    view = _view(parse(SAMPLE))
    _set_zoom(view, view.MAX_ZOOM)
    eff, hit = view._clamp_zoom_factor(1.15)
    assert hit and abs(eff - 1.0) < 1e-9        # blocked at the cap
    _, hit_out = view._clamp_zoom_factor(1 / 1.15)
    assert not hit_out                          # zooming out is still allowed


def test_last_zoom_step_snaps_to_cap_without_overshoot():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 4.8)
    eff, hit = view._clamp_zoom_factor(1.15)
    assert not hit
    assert abs(4.8 * eff - view.MAX_ZOOM) < 1e-6   # lands exactly on the cap


def test_zoom_out_blocked_at_content_aware_min():
    view = _view(parse(SAMPLE))
    lo, _ = view._zoom_bounds()
    _set_zoom(view, lo)
    _, hit = view._clamp_zoom_factor(1 / 1.15)
    assert hit                                  # can't shrink past the speck point


def test_empty_board_falls_back_to_absolute_min():
    view = _view(parse(""))
    lo, hi = view._zoom_bounds()
    assert lo == view.MIN_ZOOM_ABS and hi == view.MAX_ZOOM


# ── Wheel routing: trackpad pans, wheel / Ctrl+scroll zooms ─────────

def test_trackpad_scroll_pans_and_wheel_zooms():
    from PySide6.QtCore import QPoint, Qt
    view = _view(parse(SAMPLE))
    NONE = Qt.KeyboardModifier.NoModifier
    CTRL = Qt.KeyboardModifier.ControlModifier
    META = Qt.KeyboardModifier.MetaModifier
    Z = QPoint(0, 0)
    # Trackpad two-finger scroll (synthesized gesture, no modifier) -> pan.
    assert view._wheel_action(QPoint(5, -30), Z, NONE, True) == ("pan", 5, -30)
    # A high-res / Bluetooth mouse wheel ALSO emits pixel deltas, but it is not
    # a trackpad gesture -> it must zoom, not pan (regression guard).
    assert view._wheel_action(QPoint(0, 40), Z, NONE, False)[0] == "zoom"
    # Classic mouse wheel (angle only) -> zoom.
    assert view._wheel_action(Z, QPoint(0, 120), NONE)[0] == "zoom"
    assert view._wheel_action(Z, QPoint(0, 120), NONE)[1] > 1
    assert view._wheel_action(Z, QPoint(0, -120), NONE)[1] < 1
    # Ctrl / Cmd + scroll -> zoom even on a trackpad with pixel deltas.
    assert view._wheel_action(QPoint(0, 20), Z, CTRL, True)[0] == "zoom"
    assert view._wheel_action(Z, QPoint(0, 120), META)[0] == "zoom"
    # Nothing to do.
    assert view._wheel_action(Z, Z, NONE) is None


def test_wheel_zoom_is_proportional_to_delta():
    from PySide6.QtCore import QPoint, Qt
    view = _view(parse(SAMPLE))
    NONE = Qt.KeyboardModifier.NoModifier
    Z = QPoint(0, 0)
    one_notch = view._wheel_action(Z, QPoint(0, 120), NONE)[1]
    half_notch = view._wheel_action(Z, QPoint(0, 60), NONE)[1]
    two_notch = view._wheel_action(Z, QPoint(0, 240), NONE)[1]
    assert abs(one_notch - 1.15) < 1e-6          # one notch is the 1.15x step
    assert half_notch < one_notch < two_notch    # smooth, proportional
    assert abs(half_notch * half_notch - one_notch) < 1e-6   # exponential
