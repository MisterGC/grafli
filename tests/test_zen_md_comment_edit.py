"""Zen reading view: navigate to a commented span, reveal/edit it inline, and
delete it — the focus-first comment loop (comments never show until asked for)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from grafli import md_comments  # noqa: E402
from grafli.zen_md import ZenMarkdownEditor  # noqa: E402

MD = (
    "# Notes\n\n"
    "The {==quarterly numbers==}{>>pre-audit?<<} look off, and the "
    "{==caching layer==}{>>still Redis?<<} too.\n"
)


def _reading_editor(text: str = MD) -> ZenMarkdownEditor:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1000, 700)
    ed = ZenMarkdownEditor(parent, text, title="t")
    ed._parent = parent  # keep ref alive
    ed._toggle_rendered()
    return ed


def _key(ed, key, *, shift=False, ctrl=False, text=""):
    mods = Qt.KeyboardModifier.NoModifier
    if shift:
        mods |= Qt.KeyboardModifier.ShiftModifier
    if ctrl:
        mods |= Qt.KeyboardModifier.ControlModifier
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, text, False, 1)
    return ed._handle_rendered_key(ev)


def _span_text(ed, start, end):
    cur = ed._rendered.textCursor()
    cur.setPosition(start)
    cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    return cur.selectedText()


def test_rendered_comments_map_to_source():
    ed = _reading_editor()
    rc = ed._rendered_comments
    assert len(rc) == 2
    for start, end, comment in rc:
        assert _span_text(ed, start, end) == comment.span
    assert [c.body for _, _, c in rc] == ["pre-audit?", "still Redis?"]


def test_bracket_c_steps_through_comments():
    ed = _reading_editor()
    assert ed._active_comment == -1
    assert _key(ed, Qt.Key.Key_BracketRight) is True   # ']' pending
    assert _key(ed, Qt.Key.Key_C) is True              # 'c' -> next
    assert ed._active_comment == 0
    assert ed._rendered.textCursor().selectedText() == "quarterly numbers"
    _key(ed, Qt.Key.Key_BracketRight)
    _key(ed, Qt.Key.Key_C)
    assert ed._active_comment == 1
    # wraps back to the first
    _key(ed, Qt.Key.Key_BracketRight)
    _key(ed, Qt.Key.Key_C)
    assert ed._active_comment == 0


def test_prev_comment_from_none_lands_on_last():
    ed = _reading_editor()
    _key(ed, Qt.Key.Key_BracketLeft)   # '[' pending
    _key(ed, Qt.Key.Key_C)             # prev from none -> last
    assert ed._active_comment == 1


def test_enter_reveals_active_body():
    ed = _reading_editor()
    _key(ed, Qt.Key.Key_BracketRight)
    _key(ed, Qt.Key.Key_C)             # active 0
    assert _key(ed, Qt.Key.Key_Return) is True
    assert ed._comment_field is not None and not ed._comment_field.isHidden()
    assert ed._comment_field.toPlainText() == "pre-audit?"


def test_edit_commit_writes_body_back():
    ed = _reading_editor()
    ed._goto_comment(1)                # active 0
    ed._reveal_active_comment()
    ed._comment_field.setPlainText("are these final?")
    ed._commit_comment_field()
    comments = md_comments.parse(ed._editor.toPlainText())
    assert comments[0].body == "are these final?"
    assert comments[0].span == "quarterly numbers"   # span untouched
    assert ed._comment_field.isHidden()              # back to reading


def test_empty_body_on_commit_deletes_comment():
    ed = _reading_editor()
    ed._goto_comment(1)
    ed._reveal_active_comment()
    ed._comment_field.setPlainText("   ")            # cleared
    ed._commit_comment_field()
    src = ed._editor.toPlainText()
    assert len(md_comments.parse(src)) == 1
    assert "quarterly numbers" in src and "{==quarterly" not in src


def test_shift_d_deletes_active_comment():
    ed = _reading_editor()
    ed._goto_comment(1)                # active 0
    assert _key(ed, Qt.Key.Key_D, shift=True) is True
    src = ed._editor.toPlainText()
    assert len(md_comments.parse(src)) == 1
    # the surviving comment is the caching one
    assert md_comments.parse(src)[0].span == "caching layer"


def test_c_on_existing_comment_reveals_it_without_visual():
    ed = _reading_editor()
    start, _end, comment = ed._rendered_comments[0]
    cur = ed._rendered.textCursor()
    cur.setPosition(start + 1)            # caret inside the span, no selection
    ed._rendered.setTextCursor(cur)
    assert _key(ed, Qt.Key.Key_C, text="c") is True
    assert ed._active_comment == 0
    assert ed._comment_field is not None and not ed._comment_field.isHidden()
    assert ed._comment_field.toPlainText() == comment.body


def test_c_off_any_comment_does_nothing():
    ed = _reading_editor()
    cur = ed._rendered.textCursor()
    cur.setPosition(0)                    # on the heading, not a comment
    ed._rendered.setTextCursor(cur)
    _key(ed, Qt.Key.Key_C, text="c")
    assert ed._active_comment == -1
    assert ed._comment_field is None


def test_no_comments_navigation_is_noop():
    ed = _reading_editor("# Plain\n\nno comments here\n")
    assert ed._rendered_comments == []
    _key(ed, Qt.Key.Key_BracketRight)
    _key(ed, Qt.Key.Key_C)
    assert ed._active_comment == -1
    assert _key(ed, Qt.Key.Key_Return) is True   # consumed, but nothing to reveal
    assert ed._comment_field is None
