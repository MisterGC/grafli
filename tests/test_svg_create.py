"""Creating an SVG mockup in place (#149).

`i` enters image-placement mode; a click writes the "SVG · TODO" starter
into the vault, adds the element, and opens the file in the system app.
Shift keeps the mode so several mockups can be placed before drawing.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from grafli.constants import Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _window(tmp: Path):
    QApplication.instance() or QApplication([])
    f = tmp / "t.grafli"
    f.write_text('#!grafli v2\n@ box a "A" 0,0 120x60\n')
    from grafli.app import MainWindow
    w = MainWindow(str(f))
    w.resize(900, 600)
    return w


def _press(view, vp_pos: QPointF, shift: bool = False):
    mods = (Qt.KeyboardModifier.ShiftModifier if shift
            else Qt.KeyboardModifier.NoModifier)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, vp_pos,
                     view.viewport().mapToGlobal(vp_pos.toPoint()),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     mods)
    view.mousePressEvent(ev)


def _no_desktop_open(monkeypatch):
    from PySide6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url) or True))
    return opened


def test_click_places_starter_svg_and_opens_it(tmp_path, monkeypatch):
    w = _window(tmp_path)
    opened = _no_desktop_open(monkeypatch)
    w._view.set_mode(Mode.IMAGE)
    _press(w._view, QPointF(450, 300))

    images = w._view._board.images
    assert len(images) == 1
    img = images[0]
    assert img.image_path == f"t-res/{img.id}.svg"
    assert (img.w, img.h) == (320.0, 240.0)
    svg_file = tmp_path / img.image_path
    assert "SVG · TODO" in svg_file.read_text(encoding="utf-8")
    assert len(opened) == 1
    assert opened[0].toLocalFile() == str(svg_file)
    assert w._view._mode == Mode.SELECT
    item = w._view._image_items[img.id]
    assert item.isSelected()
    assert not item._placeholder            # the starter renders


def test_shift_click_stays_in_mode_and_does_not_open(tmp_path, monkeypatch):
    w = _window(tmp_path)
    opened = _no_desktop_open(monkeypatch)
    w._view.set_mode(Mode.IMAGE)
    _press(w._view, QPointF(300, 200), shift=True)
    _press(w._view, QPointF(500, 400), shift=True)

    assert len(w._view._board.images) == 2
    assert w._view._mode == Mode.IMAGE
    assert opened == []


def test_existing_file_is_never_overwritten(tmp_path, monkeypatch):
    w = _window(tmp_path)
    _no_desktop_open(monkeypatch)
    res = tmp_path / "t-res"
    res.mkdir()
    (res / "img1.svg").write_text("precious")
    w._view.set_mode(Mode.IMAGE)
    _press(w._view, QPointF(450, 300))

    img = w._view._board.images[0]
    assert img.image_path == "t-res/img1-1.svg"
    assert (res / "img1.svg").read_text() == "precious"


def test_unsaved_board_toasts_and_leaves_mode(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    from grafli.app import MainWindow
    w = MainWindow()
    w.resize(900, 600)
    opened = _no_desktop_open(monkeypatch)
    w._view.set_mode(Mode.IMAGE)
    _press(w._view, QPointF(450, 300))

    assert w._view._board.images == []
    assert "Save the board first" in w._view._toast_text
    assert w._view._mode == Mode.SELECT
    assert opened == []
