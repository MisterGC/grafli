"""Tests for the reusable inline vim editor widget."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from grafli.editor import InlineVimEditor
from grafli.zen_md_vim import VimMode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _editor(text: str = "", **kw) -> InlineVimEditor:
    _app()
    # Commit-on-focus-out off by default in tests so we exercise key paths
    # without spurious commits when widgets lose focus during teardown.
    kw.setdefault("commit_on_focus_out", False)
    return InlineVimEditor(text, **kw)


def _key(ed, key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    ed.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods, text))


def test_opens_in_insert_mode():
    ed = _editor("hi")
    assert ed.mode == VimMode.INSERT


def test_esc_drops_to_normal():
    ed = _editor("hi")
    _key(ed, Qt.Key.Key_Escape)
    assert ed.mode == VimMode.NORMAL


def test_esc_in_normal_commits_text():
    ed = _editor("hello")
    captured: list[str] = []
    ed.committed.connect(captured.append)
    _key(ed, Qt.Key.Key_Escape)  # insert -> normal
    _key(ed, Qt.Key.Key_Escape)  # normal -> commit
    assert captured == ["hello"]


def test_shift_esc_in_normal_cancels():
    ed = _editor("hello")
    fired = []
    ed.cancelled.connect(lambda: fired.append(True))
    _key(ed, Qt.Key.Key_Escape)  # insert -> normal
    _key(ed, Qt.Key.Key_Escape, Qt.KeyboardModifier.ShiftModifier)
    assert fired == [True]


def test_commit_emitted_once():
    ed = _editor("x")
    captured: list[str] = []
    ed.committed.connect(captured.append)
    _key(ed, Qt.Key.Key_Escape)  # normal
    _key(ed, Qt.Key.Key_Escape)  # commit
    _key(ed, Qt.Key.Key_Escape)  # would commit again -> guarded
    assert captured == ["x"]


def test_normal_mode_motion_does_not_insert():
    ed = _editor("abc")
    _key(ed, Qt.Key.Key_Escape)  # normal
    _key(ed, Qt.Key.Key_L, text="l")  # motion, not text
    assert ed.toPlainText() == "abc"


def test_autosizes_height_to_content_with_cap():
    ed = _editor("one", max_lines=10)
    ed.fit_to_width(240)
    h1 = ed.height()
    ed.setPlainText("a\nb\nc\nd\ne\nf")
    assert ed.height() > h1  # grew to fit more lines
    ed.setPlainText("\n".join(str(i) for i in range(100)))
    capped = ed.height()
    ls = ed.fontMetrics().lineSpacing()
    assert capped <= 10 * ls + ed._CHROME + 1  # never beyond the cap


def test_markdown_highlighter_attached_only_when_requested():
    assert _editor("# h", markdown=True)._highlighter is not None
    assert _editor("# h", markdown=False)._highlighter is None
