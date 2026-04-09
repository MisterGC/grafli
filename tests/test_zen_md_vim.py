"""Tests for the zen markdown Vim key handler."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from grafli.zen_md_vim import VimKeyHandler

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _handler(text: str) -> tuple[QPlainTextEdit, VimKeyHandler]:
    _app()
    editor = QPlainTextEdit(text)
    handler = VimKeyHandler(
        editor=editor,
        mode_changed=lambda mode: None,
        close_save=lambda: None,
        close_cancel=lambda: None,
    )
    return editor, handler


def test_normal_mode_autorepeat_moves_multiple_steps():
    editor, handler = _handler("abcd")
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_L,
        Qt.KeyboardModifier.NoModifier,
        "l",
        True,
        3,
    )

    assert handler.handle_key(event) is True
    assert editor.textCursor().position() == 3


def test_normal_mode_autorepeat_deletes_multiple_chars():
    editor, handler = _handler("abcdef")
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_X,
        Qt.KeyboardModifier.NoModifier,
        "x",
        True,
        3,
    )

    assert handler.handle_key(event) is True
    assert editor.toPlainText() == "def"
