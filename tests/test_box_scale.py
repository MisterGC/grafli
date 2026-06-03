"""Corner-drag uniform scale: size + font scale together, commit on release."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.items import BoxItem, _CORNER_BR, MIN_SCALE_FONT_PT
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(1200, 800)
    view._mode = Mode.SELECT
    return view


_SRC = """\
#!grafli v2
@ box a "A" 0,0 200x100 ~20
"""


def test_corner_scale_grows_size_and_font():
    view = _view(_SRC)
    box = view._box_items["a"]
    box.setSelected(True)
    box._begin_scale(_CORNER_BR, QPointF(200, 100))
    box._scale_factor = box._scale_factor_for(QPointF(400, 200))   # 2x
    box._commit_scale()
    assert box.box.w == 200 * 2
    assert box.box.h == 100 * 2
    assert box.box.textsize == "40"                                # 20 * 2
    assert (box.box.x, box.box.y) == (0, 0)                        # anchor TL fixed


def test_corner_scale_down_floors_font():
    view = _view(_SRC)
    box = view._box_items["a"]
    box.setSelected(True)
    box._begin_scale(_CORNER_BR, QPointF(200, 100))
    box._scale_factor = box._scale_factor_for(QPointF(2, 1))       # shrink hard
    box._commit_scale()
    assert int(box.box.textsize) == MIN_SCALE_FONT_PT


def _evt(view, etype, scene_pt, button, buttons):
    pos = QPointF(view.mapFromScene(scene_pt))
    g = view.viewport().mapToGlobal(pos.toPoint())
    return QMouseEvent(etype, pos, g, button, buttons,
                       Qt.KeyboardModifier.NoModifier)


def test_corner_drag_shows_foreshadow_then_clears_on_release():
    view = _view(_SRC)
    box = view._box_items["a"]
    box.setSelected(True)
    # Press on the bottom-right handle, drag out, release.
    box.mousePressEvent(_press(box, QPointF(200, 100)))
    assert box._scaling
    box.mouseMoveEvent(_move(box, QPointF(300, 150)))
    assert view._resize_foreshadow is not None                     # preview shown
    box.mouseReleaseEvent(_release(box, QPointF(300, 150)))
    assert not box._scaling
    assert view._resize_foreshadow is None                         # cleared
    assert box.box.w > 200                                          # committed larger


def _press(box, local_pt):
    return _box_evt(box, QEvent.Type.MouseButtonPress, local_pt,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)


def _move(box, local_pt):
    return _box_evt(box, QEvent.Type.MouseMove, local_pt,
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)


def _release(box, local_pt):
    return _box_evt(box, QEvent.Type.MouseButtonRelease, local_pt,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def _box_evt(box, etype, local_pt, button, buttons):
    """A graphics-scene mouse event with item-local + scene positions set."""
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent
    ev = QGraphicsSceneMouseEvent(etype)
    ev.setPos(local_pt)                                  # item-local
    ev.setScenePos(box.mapToScene(local_pt))
    ev.setButton(button)
    ev.setButtons(buttons)
    return ev
