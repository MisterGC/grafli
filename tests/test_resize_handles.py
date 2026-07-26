"""Inkscape-style resize handles: visible squares, per-handle hit-testing,
corner = aspect-locked by default (Shift frees), edges = single-axis stretch.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QGraphicsItem, QApplication

from grafli import theme
from grafli.format import parse
from grafli.items import (
    BoxItem, ImageItem, HANDLE_SIZE,
    _CORNER_BR, _EDGE_R, _EDGE_T, _ALL_HANDLES,
)
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_IGNORES_XF = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view._grid_mode = "off"
    view.load_board(parse(src))
    view.resize(1200, 900)
    view._mode = Mode.SELECT
    return view


def _evt(view, etype, scene_pt, button, buttons, mods):
    pos = QPointF(view.mapFromScene(scene_pt))
    g = view.viewport().mapToGlobal(pos.toPoint())
    return QMouseEvent(etype, pos, g, button, buttons, mods)


_BOX = """\
#!grafli v2
@ box a "A" 0,0 200x100 ~20
"""

_IMG = """\
#!grafli v2
@ image img "shots/a.png" 0,0 120x80
"""


# ── Visible, constant-size, 8 handles ──────────────────────────────

def test_box_shows_eight_constant_size_handles_when_selected():
    view = _view(_BOX)
    box = view._box_items["a"]
    assert len(box._handles) == 8
    assert all(h.flags() & _IGNORES_XF for h in box._handles)
    assert not any(h.isVisible() for h in box._handles)   # hidden until selected
    box.setSelected(True)
    assert all(h.isVisible() for h in box._handles)
    box.setSelected(False)
    assert not any(h.isVisible() for h in box._handles)


def test_image_shows_eight_handles():
    view = _view(_IMG)
    img = view._image_items["img"]
    assert len(img._handles) == 8
    assert {h.corner for h in img._handles} == set(_ALL_HANDLES)
    img.setSelected(True)
    assert all(h.isVisible() for h in img._handles)


# ── Per-handle hit-testing ─────────────────────────────────────────

def test_handle_at_distinguishes_corner_edge_and_miss():
    view = _view(_BOX)
    box = view._box_items["a"]
    r = box.rect()
    assert box._handle_at(r.bottomRight()) == _CORNER_BR
    cx = (r.left() + r.right()) / 2
    assert box._handle_at(QPointF(cx, r.top())) == _EDGE_T
    # Dead centre is no handle — that starts a move, not a resize.
    assert box._handle_at(QPointF(cx, (r.top() + r.bottom()) / 2)) is None


# ── Corner flip: aspect-locked by default, Shift frees ─────────────

def _corner_drag(view, item, corner_local_pt, target_scene, *, shift):
    mods = (Qt.KeyboardModifier.ShiftModifier if shift
            else Qt.KeyboardModifier.NoModifier)
    item.setSelected(True)
    start = item.mapToScene(corner_local_pt)
    view.mousePressEvent(_evt(view, QEvent.Type.MouseButtonPress, start,
                              Qt.MouseButton.LeftButton,
                              Qt.MouseButton.LeftButton, mods))
    view.mouseMoveEvent(_evt(view, QEvent.Type.MouseMove, target_scene,
                             Qt.MouseButton.NoButton,
                             Qt.MouseButton.LeftButton, mods))
    view.mouseReleaseEvent(_evt(view, QEvent.Type.MouseButtonRelease,
                                target_scene, Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton, mods))


def test_box_corner_drag_keeps_ratio_without_shift():
    view = _view(_BOX)
    box = view._box_items["a"]
    # Grab just inside the BR corner; drag so fx=2, fy=1.5 → ratio-lock picks 2.
    _corner_drag(view, box, QPointF(197, 97), QPointF(400, 150), shift=False)
    assert box.box.w == 400
    assert box.box.h == 200                 # height locked to the width factor


def test_box_corner_drag_free_with_shift():
    view = _view(_BOX)
    box = view._box_items["a"]
    _corner_drag(view, box, QPointF(197, 97), QPointF(400, 150), shift=True)
    assert box.box.w == 400
    assert box.box.h == 150                 # non-uniform


# ── Edge handles: single axis, modifier-agnostic ───────────────────

def test_image_edge_stretches_single_axis():
    view = _view(_IMG)
    img = view._image_items["img"]
    img._apply_resize_delta(40, 0, _EDGE_R)
    assert img.image.w == 160
    assert img.image.h == 80


def test_image_corner_keeps_aspect_by_default():
    view = _view(_IMG)
    img = view._image_items["img"]
    img._aspect_ratio = 1.5                  # 120/80
    img._apply_resize_delta(30, 0, _CORNER_BR, keep_ratio=True)
    assert img.image.w == 150
    assert abs(img.image.h - 100) < 1e-6     # height followed width / ar


def test_image_corner_free_with_shift():
    view = _view(_IMG)
    img = view._image_items["img"]
    img._apply_resize_delta(30, 0, _CORNER_BR, keep_ratio=False)
    assert img.image.w == 150
    assert img.image.h == 80                 # height untouched


# ── Hover feedback + interactivity ─────────────────────────────────

def test_handles_are_interactive():
    view = _view(_BOX)
    h = view._box_items["a"]._handles[0]
    assert h.acceptHoverEvents()
    assert h.acceptedMouseButtons() & Qt.MouseButton.LeftButton


def test_handle_hover_grows_and_recolours():
    view = _view(_BOX)
    h = view._box_items["a"]._handles[0]
    idle = h.rect().width()
    assert idle == HANDLE_SIZE
    assert h.brush().color() == theme.HANDLE_FILL
    h._set_hover(True)
    assert h.rect().width() > idle               # grows to advertise the grab
    assert h.brush().color() == theme.HANDLE_HOVER_FILL  # fills with the accent
    h._set_hover(False)
    assert h.rect().width() == idle
    assert h.brush().color() == theme.HANDLE_FILL


def test_handles_follow_a_theme_switch():
    """A live switch has to reach the handles — they cache brush/pen."""
    view = _view(_BOX)
    h = view._box_items["a"]._handles[0]
    assert h.brush().color() == theme.LIGHT.HANDLE_FILL
    try:
        theme.set_theme("dark")
        view.apply_theme()
        assert h.brush().color() == theme.DARK.HANDLE_FILL
    finally:
        theme.set_theme("light")
