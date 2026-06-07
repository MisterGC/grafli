"""Shift held *before* grabbing a corner handle must start a ratio-locked scale.

Shift+click normally toggles selection, but on a resize handle of an already
selected item it has to begin the scale gesture instead — otherwise holding
Shift before dragging would deselect the box and never resize it.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

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


def _vp(view, scene_pt) -> QPointF:
    return QPointF(view.mapFromScene(scene_pt))


def _evt(view, etype, pos, button, buttons, mods):
    g = view.viewport().mapToGlobal(pos.toPoint())
    return QMouseEvent(etype, pos, g, button, buttons, mods)


_ONE = """\
#!grafli v2
@ box a "A" 0,0 200x100 ~20
"""


def test_shift_press_on_corner_handle_starts_scale():
    view = _view(_ONE)
    box = view._box_items["a"]
    box.setSelected(True)
    br = box.rect().bottomRight()
    corner = box.mapToScene(QPointF(br.x() - 5, br.y() - 5))  # in the BR grab margin
    pos = _vp(view, corner)
    view.mousePressEvent(_evt(view, QEvent.Type.MouseButtonPress, pos,
                              Qt.MouseButton.LeftButton,
                              Qt.MouseButton.LeftButton,
                              Qt.KeyboardModifier.ShiftModifier))
    # Scale gesture started, and the box was not toggled out of selection.
    assert getattr(box, "_scaling", False) is True
    assert box.isSelected()
