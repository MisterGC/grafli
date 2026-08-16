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


def _save_dialog(monkeypatch, answer: str):
    """Answer the save-location dialog with *answer* ("" cancels)."""
    from PySide6.QtWidgets import QFileDialog
    asked = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (asked.append(a), (answer, ""))[1]),
    )
    return asked


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


def _untitled_window(monkeypatch):
    QApplication.instance() or QApplication([])
    from grafli.app import MainWindow
    w = MainWindow()
    w.resize(900, 600)
    _no_desktop_open(monkeypatch)
    return w


def test_untitled_board_asks_for_a_save_location_then_places(tmp_path,
                                                             monkeypatch):
    w = _untitled_window(monkeypatch)
    target = tmp_path / "fresh.grafli"
    asked = _save_dialog(monkeypatch, str(target))
    w._view.set_mode(Mode.IMAGE)
    where = w._view.mapToScene(QPointF(450, 300).toPoint())
    _press(w._view, QPointF(450, 300))

    assert len(asked) == 1
    assert w._file_path == target
    img = w._view._board.images[0]
    assert img.image_path == f"fresh-res/{img.id}.svg"
    assert (tmp_path / img.image_path).exists()
    # The mockup lands on the click, not wherever the dialog left the mouse.
    assert (img.x + img.w / 2, img.y + img.h / 2) == (where.x(), where.y())


def test_cancelling_the_save_dialog_places_nothing(tmp_path, monkeypatch):
    w = _untitled_window(monkeypatch)
    _save_dialog(monkeypatch, "")
    w._view.set_mode(Mode.IMAGE)
    _press(w._view, QPointF(450, 300))

    assert w._view._board.images == []
    assert w._file_path is None
    assert w._view._toast_text == ""        # a cancel says nothing
    assert w._view._mode == Mode.SELECT


def test_windowless_view_still_toasts(tmp_path):
    # `grafli render` builds a view with no MainWindow above it — there is
    # nobody to ask for a save location, so the old advice stands.
    QApplication.instance() or QApplication([])
    from grafli.format import parse
    from grafli.view import GrafliView
    view = GrafliView()
    view.load_board(parse('#!grafli v1\n'))
    view.resize(900, 600)
    view.set_mode(Mode.IMAGE)
    _press(view, QPointF(450, 300))

    assert view._board.images == []
    assert "Save the board first" in view._toast_text


def test_starter_carries_the_theme_palette(tmp_path, monkeypatch):
    from grafli import theme
    from grafli.resources import svg_starter
    theme.set_theme("light")
    content = svg_starter()
    assert "SVG · TODO" in content
    for name, hexv in theme.color_tokens().items():
        assert hexv in content
        assert f"%{name}" in content     # eyedrop hint via <title>
