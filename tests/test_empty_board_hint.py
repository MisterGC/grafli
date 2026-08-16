"""The starting hint on an empty board (#153).

A board with nothing on it paints two muted lines in the middle of the
viewport — the first keys, and F1 for the rest — and drops them the moment
the first element lands. It is view chrome: painted, never hit-tested, and
absent from the scene-rendered exports.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.constants import Mode
from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    return QApplication.instance() or QApplication([])


def _window(tmp: Path | None = None, text: str = ""):
    _app()
    from grafli.app import MainWindow
    if tmp is None:
        w = MainWindow()
    else:
        f = tmp / "t.grafli"
        f.write_text(text)
        w = MainWindow(str(f))
    w.resize(900, 600)
    return w


def test_untitled_board_shows_the_hint():
    w = _window()
    lines = w._view._empty_hint_lines()
    assert [text for text, _ in lines] == ["n box  ·  t note  ·  i image",
                                           "F1 all keys"]


def test_empty_saved_board_shows_the_hint_too(tmp_path: Path):
    w = _window(tmp_path, "#!grafli v2\n")
    assert w._view._empty_hint_lines()


def test_a_board_with_an_element_has_no_hint(tmp_path: Path):
    w = _window(tmp_path, '#!grafli v2\n@ box a "A" 0,0 120x60\n')
    assert w._view._empty_hint_lines() == ()


def test_the_first_element_takes_the_hint_away():
    w = _window()
    assert w._view._empty_hint_lines()
    w._view._paste_text_note(QPointF(0, 0), "first")
    assert w._view._board.notes
    assert w._view._empty_hint_lines() == ()


def test_hint_keys_are_the_real_mode_keys():
    # The hint is a promise about the keyboard — keep it checkable, not a
    # comment that rots when a mode key moves.
    w = _window()
    line = w._view._empty_hint_lines()[0][0]
    keys = re.findall(r"(?:^|·)\s*([a-z]) ", line)
    assert keys == ["n", "t", "i"]
    for key, mode in zip(keys, (Mode.RECT, Mode.TEXT, Mode.IMAGE)):
        w._view.set_mode(Mode.SELECT)
        ev = QKeyEvent(QEvent.Type.KeyPress,
                       getattr(Qt.Key, f"Key_{key.upper()}"),
                       Qt.KeyboardModifier.NoModifier)
        w._view.keyPressEvent(ev)
        assert w._view._mode == mode


def _hint_ink_pixels(view) -> int:
    """Paint just the hint onto a scene-coloured image; count what it wrote."""
    img = QImage(view.viewport().width(), view.viewport().height(),
                 QImage.Format.Format_ARGB32)
    img.fill(theme.SCENE_BG)
    painter = QPainter(img)
    view._draw_empty_hint(painter)
    painter.end()
    bg = QImage(img.width(), img.height(), QImage.Format.Format_ARGB32)
    bg.fill(theme.SCENE_BG)
    return sum(img.pixel(x, y) != bg.pixel(x, y)
               for y in range(img.height()) for x in range(img.width()))


def test_the_hint_actually_paints_on_an_empty_board():
    w = _window()
    assert _hint_ink_pixels(w._view) > 0


def test_nothing_paints_once_the_board_has_content(tmp_path: Path):
    w = _window(tmp_path, '#!grafli v2\n@ box a "A" 0,0 120x60\n')
    assert _hint_ink_pixels(w._view) == 0


def test_headless_render_of_an_empty_board_stays_blank(tmp_path: Path):
    # `grafli render` draws the scene, not the view, so no view chrome — the
    # grid dots and the hint alike — can leak into the image.
    from grafli.app import _cmd_render
    board = tmp_path / "empty.grafli"
    board.write_text("#!grafli v2\n")
    out = tmp_path / "empty.png"
    assert _cmd_render([str(board), str(out)]) == 0
    img = QImage(str(out))
    assert not img.isNull()
    colors = {img.pixel(x, y)
              for y in range(img.height()) for x in range(img.width())}
    assert len(colors) == 1


def test_windowless_view_needs_no_board_for_the_hint():
    # A view built before any board is loaded must not trip the predicate.
    _app()
    from grafli.view import GrafliView
    view = GrafliView()
    assert view._empty_hint_lines() == ()
    view.load_board(parse("#!grafli v1\n"))
    assert view._empty_hint_lines()
