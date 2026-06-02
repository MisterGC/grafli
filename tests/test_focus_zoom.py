"""Focus-zoom toggle (gz): zoom to selection, press again to fly back."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view() -> GrafliView:
    _app()
    view = GrafliView()
    view.load_board(parse("""\
#!grafli v2
@ box box1 "A" 0,0 120x80
@ box box2 "B" 2000,1500 120x80
"""))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    # Make navigation instant so we can assert on the resulting transform.
    view._animate_to_rect = lambda rect: view.goto_rect(rect, animate=False)
    view._zoom_to_fit()
    return view


def _zoom(view) -> float:
    return view.transform().m11()


def test_focus_zooms_in_then_back():
    view = _view()
    overview = _zoom(view)
    view._box_items["box1"].setSelected(True)

    view._toggle_focus_zoom()
    assert _zoom(view) > overview * 1.5          # zoomed into the small box
    assert view._focus_return is not None

    view._toggle_focus_zoom()
    assert abs(_zoom(view) - overview) < 0.05    # flew back to the overview
    assert view._focus_return is None


def test_focus_without_selection_is_noop():
    view = _view()
    before = _zoom(view)
    view._toggle_focus_zoom()
    assert view._focus_return is None
    assert abs(_zoom(view) - before) < 0.01


def test_refocus_on_changed_selection_keeps_return():
    view = _view()
    overview = _zoom(view)
    view._box_items["box1"].setSelected(True)
    view._toggle_focus_zoom()
    saved = view._focus_return
    assert saved is not None

    # Change selection and re-press: re-focus on box2, keep the return view.
    view._scene.clearSelection()
    view._box_items["box2"].setSelected(True)
    view._toggle_focus_zoom()
    assert view._focus_return is saved
    center = view.mapToScene(view.viewport().rect().center())
    assert abs(center.x() - 2060) < 80 and abs(center.y() - 1540) < 80

    # Final press returns all the way to the original overview.
    view._toggle_focus_zoom()
    assert view._focus_return is None
    assert abs(_zoom(view) - overview) < 0.05
