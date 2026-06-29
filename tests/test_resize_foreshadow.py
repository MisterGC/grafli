"""Resize/scale foreshadow overlay: target frame + content-occupied area."""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.items import ResizeForeshadow
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view() -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse("#!grafli v2\n@ box a \"A\" 0,0 200x100\n"))
    return view


def test_show_adds_overlay_then_clear_removes_it():
    view = _view()
    assert view._resize_foreshadow is None
    view._show_resize_foreshadow(QRectF(0, 0, 300, 150),
                                 content=QRectF(10, 10, 100, 50), locked=True)
    fs = view._resize_foreshadow
    assert isinstance(fs, ResizeForeshadow)
    assert fs.scene() is view._scene
    view._clear_resize_foreshadow()
    assert view._resize_foreshadow is None
    assert fs.scene() is None


def test_show_reuses_single_overlay():
    view = _view()
    view._show_resize_foreshadow(QRectF(0, 0, 300, 150))
    first = view._resize_foreshadow
    view._show_resize_foreshadow(QRectF(0, 0, 400, 200), locked=True)
    assert view._resize_foreshadow is first          # reused, not re-added


def test_bounding_rect_covers_frame_and_content():
    fs = ResizeForeshadow()
    fs.set_preview(QRectF(0, 0, 200, 100),
                   QRectF(150, 80, 200, 120), locked=False)
    br = fs.boundingRect()
    assert br.contains(QRectF(0, 0, 200, 100))       # frame inside
    assert br.right() >= 350                          # content extent included
