"""Zen reading view: author a new comment by word-jump (pick the span's first
word, then its last) and type the body — the comment tool wraps it in
CriticMarkup; you never type the syntax by hand."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from grafli import md_comments  # noqa: E402
from grafli.zen_md import ZenMarkdownEditor  # noqa: E402

MD = "# Notes\n\nthe quick brown fox jumps over\n"


def _reading_editor(text: str = MD) -> ZenMarkdownEditor:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 600)
    ed = ZenMarkdownEditor(parent, text, title="t")
    ed._parent = parent
    ed._toggle_rendered()
    return ed


def _rspan(ed, sub):
    rendered = ed._rendered.document().toPlainText()
    r0 = rendered.index(sub)
    return r0, r0 + len(sub)


def test_author_wraps_selected_span():
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "quick brown")
    ed._begin_comment_for_span(r0, r1)
    assert ed._authoring_span is not None
    assert ed._comment_field.toPlainText() == ""        # starts empty
    ed._comment_field.setPlainText("why quick brown?")
    ed._commit_comment_field()
    comments = md_comments.parse(ed._editor.toPlainText())
    assert [(c.span, c.body) for c in comments] == [("quick brown", "why quick brown?")]
    assert ed._authoring_span is None                   # cleared
    assert ed._active_comment == 0                       # new comment is active


def test_author_empty_body_creates_nothing():
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "fox")
    ed._begin_comment_for_span(r0, r1)
    ed._comment_field.setPlainText("   ")               # nothing typed
    ed._commit_comment_field()
    assert md_comments.parse(ed._editor.toPlainText()) == []
    assert ed._authoring_span is None


def test_two_pick_state_machine():
    ed = _reading_editor()
    rendered = ed._rendered.document().toPlainText()
    activations = []

    class _StubJump:
        def activate(self, on_pick=None):
            activations.append(on_pick)

    ed._comment_jump = _StubJump()
    ed._author_pick_start = None
    ed._authoring_span = None
    ed._on_author_pick(rendered.index("quick"))         # first pick
    assert ed._author_pick_start is not None
    assert len(activations) == 1                         # re-armed for 2nd pick
    ed._on_author_pick(rendered.index("brown"))         # second pick closes span
    assert ed._author_pick_start is None
    assert ed._authoring_span is not None
    s0, s1, sel = ed._authoring_span
    assert ed._editor.toPlainText()[s0:s1] == "quick brown"


def test_c_key_starts_authoring():
    ed = _reading_editor()
    started = []

    class _StubJump:
        def activate(self, on_pick=None):
            started.append(on_pick)

    ed._comment_jump = _StubJump()        # pre-seed so no live overlay is shown
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C,
                   Qt.KeyboardModifier.NoModifier, "c", False, 1)
    assert ed._handle_rendered_key(ev) is True
    assert len(started) == 1 and started[0] == ed._on_author_pick


def test_unmappable_selection_falls_back_to_source():
    ed = _reading_editor()
    assert ed._rendered_mode is True
    r0, _ = _rspan(ed, "fox")
    ed._begin_comment_for_span(r0, r0)                  # empty span → unmappable
    assert ed._rendered_mode is False                   # dropped to source editor
    assert ed._authoring_span is None
