"""Integration tests for inline (proxy-hosted) note editing in the view."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str):
    _app()
    from grafli.view import GrafliView
    v = GrafliView()
    v.load_board(parse(text))
    return v


def test_start_editing_note_opens_inline_widget():
    v = _view('@ note n1 0,0 "hello"')
    note = v._note_items["n1"]
    v._start_editing(note)
    assert v._note_widget is not None
    assert v._note_proxy is not None
    assert note.isVisible() is False
    assert v._editor is None  # not the box/arrow path


def test_commit_writes_new_text_and_tears_down():
    v = _view('@ note n1 0,0 "hello"')
    note = v._note_items["n1"]
    v._start_editing(note)
    v._note_widget.setPlainText("world")
    v._commit_editor()
    assert note.note.text == "world"
    assert v._note_widget is None
    assert v._note_proxy is None
    assert note.isVisible() is True


def test_cancel_discards_changes():
    v = _view('@ note n1 0,0 "hello"')
    note = v._note_items["n1"]
    v._start_editing(note)
    v._note_widget.setPlainText("changed")
    v._cancel_editor()
    assert note.note.text == "hello"
    assert v._note_widget is None
    assert note.isVisible() is True


def test_empty_text_keeps_original():
    v = _view('@ note n1 0,0 "keep me"')
    note = v._note_items["n1"]
    v._start_editing(note)
    v._note_widget.setPlainText("   ")
    v._commit_editor()
    assert note.note.text == "keep me"


def test_md_note_gets_markdown_highlighting():
    v = _view('@ note n1 0,0 "md: # Title"')
    note = v._note_items["n1"]
    v._start_editing(note)
    assert v._note_widget._highlighter is not None


def _key(w, key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods, text))


def test_real_key_path_type_then_commit():
    """Drive the widget via real key events: type, then Esc Esc to commit."""
    v = _view('@ note n1 0,0 ""')
    note = v._note_items["n1"]
    v._start_editing(note)
    w = v._note_widget
    for ch in "hi":
        _key(w, getattr(Qt.Key, f"Key_{ch.upper()}"), text=ch)
    _key(w, Qt.Key.Key_Escape)  # INSERT -> NORMAL
    _key(w, Qt.Key.Key_Escape)  # NORMAL -> commit (emits committed)
    assert note.note.text == "hi"
    assert v._note_widget is None


def test_editing_second_note_commits_first():
    v = _view('@ note n1 0,0 "one"\n@ note n2 0,200 "two"')
    n1 = v._note_items["n1"]
    n2 = v._note_items["n2"]
    v._start_editing(n1)
    v._note_widget.setPlainText("edited one")
    v._start_editing(n2)  # should commit n1 first
    assert n1.note.text == "edited one"
    assert v._edit_target is n2
