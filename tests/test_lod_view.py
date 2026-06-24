"""View-level tests for the LoD simplified-paint tier (zoom clock + toggle)."""

from __future__ import annotations

import os

from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SAMPLE = """\
@ box group "Group" 0,0 400x400 !flat
@ box child "Child" 40,80 200x80 >group
@ box loose "Loose" 600,0 200x80
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


def _set_zoom(view, z):
    view.setTransform(QTransform().scale(z, z))
    view._refresh_lod()


def test_boxes_detailed_at_full_zoom():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 1.0)
    assert view._lod_simplified == set()
    for item in view._box_items.values():
        assert not item._lod_simplified
        assert item._label.isVisible()


def test_boxes_simplify_when_zoomed_far_out():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.05)               # labels would be sub-pixel
    assert view._lod_simplified == {"group", "child", "loose"}
    for item in view._box_items.values():
        assert item._lod_simplified
        assert not item._label.isVisible()   # label hidden -> bare shell


def test_zooming_back_in_restores_detail():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.05)
    assert view._lod_simplified
    _set_zoom(view, 1.0)
    assert view._lod_simplified == set()
    assert all(it._label.isVisible() for it in view._box_items.values())


def test_toggle_off_keeps_full_detail_even_zoomed_out():
    view = _view(parse(SAMPLE))
    view._lod_enabled = False
    _set_zoom(view, 0.05)
    assert view._lod_simplified == set()
    assert all(not it._lod_simplified for it in view._box_items.values())
    assert all(it._label.isVisible() for it in view._box_items.values())


def test_toggle_helper_flips_and_reapplies():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.05)
    assert view._lod_simplified                # simplified while on
    view._toggle_lod()                         # -> off
    assert not view._lod_enabled
    assert view._lod_simplified == set()
    assert all(it._label.isVisible() for it in view._box_items.values())
    view._toggle_lod()                         # -> on again
    assert view._lod_enabled
    assert view._lod_simplified == {"group", "child", "loose"}
