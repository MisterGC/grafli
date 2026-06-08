"""Selection vs. reparenting: a plain/shift click must not nest items.

Drag-to-nest follows the mouse cursor, so reparenting may only happen after a
real drag — never when a click merely changes the set of selected items.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(src: str) -> GrafliView:
    _app()
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    return view


def _vp(view, scene_pt) -> QPointF:
    return QPointF(view.mapFromScene(scene_pt))


def _evt(view, etype, pos, button, buttons, mods):
    g = view.viewport().mapToGlobal(pos.toPoint())
    return QMouseEvent(etype, pos, g, button, buttons, mods)


def _click(view, box_id, *, shift=False):
    pos = _vp(view, view._box_items[box_id].sceneBoundingRect().center())
    mods = (Qt.KeyboardModifier.ShiftModifier if shift
            else Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(_evt(view, QEvent.Type.MouseButtonPress, pos,
                              Qt.MouseButton.LeftButton,
                              Qt.MouseButton.LeftButton, mods))
    view.mouseReleaseEvent(_evt(view, QEvent.Type.MouseButtonRelease, pos,
                                Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton, mods))


def _drag(view, box_id, target_id):
    start = view._box_items[box_id].sceneBoundingRect().center()
    target = view._box_items[target_id].sceneBoundingRect().center()
    p0 = _vp(view, start)
    view.mousePressEvent(_evt(view, QEvent.Type.MouseButtonPress, p0,
                              Qt.MouseButton.LeftButton,
                              Qt.MouseButton.LeftButton,
                              Qt.KeyboardModifier.NoModifier))
    for t in (0.3, 0.6, 1.0):
        sp = QPointF(start.x() + (target.x() - start.x()) * t,
                     start.y() + (target.y() - start.y()) * t)
        vp = _vp(view, sp)
        view.mouseMoveEvent(_evt(view, QEvent.Type.MouseMove, vp,
                                 Qt.MouseButton.NoButton,
                                 Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier))
    vpt = _vp(view, target)
    view.mouseReleaseEvent(_evt(view, QEvent.Type.MouseButtonRelease, vpt,
                                Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier))


_SIBLINGS = """\
#!grafli v2
@ box box1 "A" 0,0 160x100
@ box box2 "B" 400,0 160x100
"""


def test_shift_click_adds_to_selection_without_reparenting():
    view = _view(_SIBLINGS)
    board = view.board
    _click(view, "box1")
    _click(view, "box2", shift=True)
    selected = {view._item_id(i) for i in view._scene.selectedItems()}
    assert {"box1", "box2"} <= selected
    assert board.box_by_id("box1").parent == ""
    assert board.box_by_id("box2").parent == ""


_SMALL_AND_BIG = """\
#!grafli v2
@ box small "A" 0,0 100x60
@ box big "B" 300,0 400x300
"""


def _hover(view, scene_pt, *, shift=False):
    pos = _vp(view, scene_pt)
    mods = (Qt.KeyboardModifier.ShiftModifier if shift
            else Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(_evt(view, QEvent.Type.MouseMove, pos,
                             Qt.MouseButton.NoButton,
                             Qt.MouseButton.NoButton, mods))


def test_hover_over_box_does_not_flash_reparent_outline():
    # With one item selected, moving the cursor (no button) over another box
    # must not draw the reparent grow-outline — only an actual drag may.
    view = _view(_SMALL_AND_BIG)
    _click(view, "small")
    assert view._grow_preview is None
    _hover(view, view._box_items["big"].sceneBoundingRect().center(), shift=True)
    assert view._grow_preview is None


def test_drag_into_box_still_previews_reparent():
    view = _view(_SMALL_AND_BIG)
    _click(view, "small")
    _drag(view, "small", "big")          # release nests it
    # After the drag the preview is cleared, and nesting actually happened.
    assert view._grow_preview is None
    assert view.board.box_by_id("small").parent == "big"


def test_plain_click_does_not_reparent():
    view = _view(_SIBLINGS)
    board = view.board
    _click(view, "box1")
    _click(view, "box2")
    assert board.box_by_id("box1").parent == ""
    assert board.box_by_id("box2").parent == ""


def test_drag_onto_box_still_reparents():
    view = _view("""\
#!grafli v2
@ box box1 "Child" 0,0 80x50
@ box box2 "Big" 300,0 400x300
""")
    board = view.board
    _drag(view, "box1", "box2")
    assert board.box_by_id("box1").parent == "box2"


def test_multiselect_move_does_not_reparent_into_a_sibling():
    # Regression: moving a multi-selection must just relocate the items
    # together — never nest the group into whichever selected member happens
    # to sit under the cursor on release (which previously made the last-
    # selected box "absorb" all the others).
    view = _view(_SIBLINGS)
    board = view.board
    a, b = view._box_items["box1"], view._box_items["box2"]
    a.setSelected(True)
    b.setSelected(True)
    view._drag_moved = True   # a real move just happened
    pos = _vp(view, b.sceneBoundingRect().center())   # cursor over sibling box2
    view.mouseReleaseEvent(_evt(view, QEvent.Type.MouseButtonRelease, pos,
                                Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier))
    assert board.box_by_id("box1").parent == ""
    assert board.box_by_id("box2").parent == ""
