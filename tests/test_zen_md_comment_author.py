"""Zen reading view: author a comment by selecting the span in vim visual mode
(v + motions), then typing the body — the comment tool wraps it in CriticMarkup;
you never type the syntax by hand."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QTextCursor  # noqa: E402
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


def _key(ed, key, *, shift=False, ctrl=False, text=""):
    mods = Qt.KeyboardModifier.NoModifier
    if shift:
        mods |= Qt.KeyboardModifier.ShiftModifier
    if ctrl:
        mods |= Qt.KeyboardModifier.ControlModifier
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, text, False, 1)
    return ed._handle_rendered_key(ev)


def _rspan(ed, sub):
    rendered = ed._rendered.document().toPlainText()
    r0 = rendered.index(sub)
    return r0, r0 + len(sub)


def _select(ed, sub):
    r0, r1 = _rspan(ed, sub)
    cur = ed._rendered.textCursor()
    cur.setPosition(r0)
    cur.setPosition(r1, QTextCursor.MoveMode.KeepAnchor)
    ed._rendered.setTextCursor(cur)
    return r0, r1


# ── visual mode ──

def test_v_enters_visual_and_motions_extend_selection():
    ed = _reading_editor()
    r0, _ = _rspan(ed, "quick")
    cur = ed._rendered.textCursor()
    cur.setPosition(r0)
    ed._rendered.setTextCursor(cur)
    assert _key(ed, Qt.Key.Key_V, text="v") is True
    assert ed._visual is True
    _key(ed, Qt.Key.Key_W)            # extend by a word
    _key(ed, Qt.Key.Key_W)
    sel = ed._rendered.textCursor()
    assert sel.hasSelection()
    assert sel.selectionStart() == r0


def test_esc_leaves_visual_without_closing():
    ed = _reading_editor()
    ed._set_visual(True)
    assert _key(ed, Qt.Key.Key_Escape) is True
    assert ed._visual is False
    assert not ed._rendered.textCursor().hasSelection()


def test_c_comments_the_visual_selection():
    ed = _reading_editor()
    _select(ed, "quick brown")
    ed._visual = True
    assert _key(ed, Qt.Key.Key_C, text="c") is True
    assert ed._visual is False             # leaving visual on comment
    assert ed._authoring_span is not None
    ed._comment_field.setPlainText("why quick brown?")
    ed._commit_comment_field()
    spans = [(c.span, c.body) for c in md_comments.parse(ed._editor.toPlainText())]
    assert spans == [("quick brown", "why quick brown?")]
    assert ed._active_comment == 0


def test_commit_authoring_stays_in_reading_view():
    # regression: committing a new comment used to validation-fail and toggle
    # back to the source editor ("exit rendering mode") on Esc.
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "quick brown fox")     # multi-word span
    ed._begin_comment_for_span(r0, r1)
    ed._comment_field.setPlainText("note")
    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                      Qt.KeyboardModifier.NoModifier)
    assert ed._handle_comment_field_key(enter) is True   # Enter saves
    assert ed._rendered_mode is True           # stayed in the reading view
    comments = md_comments.parse(ed._editor.toPlainText())
    assert [(c.span, c.body) for c in comments] == [("quick brown fox", "note")]
    assert ed._active_comment == 0


def test_shift_enter_inserts_newline_not_commit():
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "quick")
    ed._begin_comment_for_span(r0, r1)
    ed._comment_field.setPlainText("line one")
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                   Qt.KeyboardModifier.ShiftModifier)
    assert ed._handle_comment_field_key(ev) is True
    assert "\n" in ed._comment_field.toPlainText()        # line break inserted
    assert not ed._comment_field.isHidden()               # still editing
    assert md_comments.parse(ed._editor.toPlainText()) == []  # nothing saved yet


def test_esc_cancels_new_comment():
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "quick")
    ed._begin_comment_for_span(r0, r1)
    ed._comment_field.setPlainText("discard me")
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                   Qt.KeyboardModifier.NoModifier)
    assert ed._handle_comment_field_key(ev) is True
    assert md_comments.parse(ed._editor.toPlainText()) == []   # not created
    assert ed._authoring_span is None
    assert ed._comment_field.isHidden()


def test_c_without_selection_is_noop():
    ed = _reading_editor()
    cur = ed._rendered.textCursor()
    cur.clearSelection()
    ed._rendered.setTextCursor(cur)
    assert _key(ed, Qt.Key.Key_C, text="c") is True
    assert ed._authoring_span is None
    assert md_comments.parse(ed._editor.toPlainText()) == []


# ── span → source mapping (via _begin_comment_for_span) ──

def test_author_wraps_selected_span():
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "quick brown")
    ed._begin_comment_for_span(r0, r1)
    assert ed._authoring_span is not None
    assert ed._comment_field.toPlainText() == ""
    ed._comment_field.setPlainText("why quick brown?")
    ed._commit_comment_field()
    comments = md_comments.parse(ed._editor.toPlainText())
    assert [(c.span, c.body) for c in comments] == [("quick brown", "why quick brown?")]
    assert ed._authoring_span is None
    assert ed._active_comment == 0


def test_caret_lands_on_new_comment_after_commit():
    # After confirming, the caret sits on the new comment (so j/k continue from
    # there), not at the document end or the page top.
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "quick brown")
    ed._begin_comment_for_span(r0, r1)
    ed._comment_field.setPlainText("note")
    ed._commit_comment_field()
    span_start = ed._rendered_comments[ed._active_comment][0]
    assert ed._rendered.textCursor().position() == span_start


def test_author_empty_body_creates_nothing():
    ed = _reading_editor()
    r0, r1 = _rspan(ed, "fox")
    ed._begin_comment_for_span(r0, r1)
    ed._comment_field.setPlainText("   ")
    ed._commit_comment_field()
    assert md_comments.parse(ed._editor.toPlainText()) == []
    assert ed._authoring_span is None


def test_authoring_inside_existing_comment_edits_it():
    ed = _reading_editor("# N\n\nthe {==quick brown==}{>>why?<<} fox\n")
    rendered = ed._rendered.document().toPlainText()
    r0 = rendered.index("quick")
    r1 = r0 + len("quick")              # inside the existing span
    ed._begin_comment_for_span(r0, r1)
    assert ed._authoring_span is None   # did NOT start a new comment
    assert ed._active_comment == 0
    assert ed._comment_field is not None and not ed._comment_field.isHidden()
    assert ed._comment_field.toPlainText() == "why?"


def test_authoring_clear_of_comments_creates_new():
    ed = _reading_editor("# N\n\nthe {==quick==}{>>why?<<} brown fox here\n")
    rendered = ed._rendered.document().toPlainText()
    r0 = rendered.index("brown fox")
    r1 = r0 + len("brown fox")
    ed._begin_comment_for_span(r0, r1)
    assert ed._authoring_span is not None
    ed._comment_field.setPlainText("zoom?")
    ed._commit_comment_field()
    spans = [(c.span, c.body) for c in md_comments.parse(ed._editor.toPlainText())]
    assert ("brown fox", "zoom?") in spans and ("quick", "why?") in spans


def test_comment_starting_inside_inline_code_renders():
    # selecting a span that starts on a word inside `code` snaps the marker out
    # of the code so the comment parses (not rendered as literal {== ).
    ed = _reading_editor("# D\n\n- **`assembly` meeting type added** here\n")
    rt = ed._rendered.document().toPlainText()
    r0 = rt.index("assembly")
    r1 = rt.index("added") + len("added")
    cur = ed._rendered.textCursor()
    cur.setPosition(r0)
    cur.setPosition(r1, QTextCursor.MoveMode.KeepAnchor)
    ed._rendered.setTextCursor(cur)
    ed._visual = True
    ed._comment_selection()
    assert ed._comment_field is not None and not ed._comment_field.isHidden()
    ed._comment_field.setPlainText("why?")
    ed._commit_comment_field()
    src = ed._editor.toPlainText()
    (c,) = md_comments.parse(src)
    assert c.body == "why?" and "assembly" in c.span
    assert "{==" not in ed._rendered.document().toPlainText()   # not literal


def test_comment_across_code_example_is_refused():
    # selecting a span that crosses a `{== ==}` syntax example would wrap nested
    # delimiters and render as literal text — refuse quietly instead.
    ed = _reading_editor("# N\n\nthe `{== ==}{>> <<}` marker shows here in prose\n")
    rt = ed._rendered.document().toPlainText()
    r0 = rt.index("the")
    r1 = rt.index("marker") + len("marker")   # spans across the code example
    ed._begin_comment_for_span(r0, r1)
    assert ed._comment_field is None                       # no field opened
    assert ed._authoring_span is None
    assert md_comments.parse(ed._editor.toPlainText()) == []   # nothing wrapped


def test_unmappable_selection_is_a_quiet_noop():
    # an unmappable selection must NOT yank you to the source view — it simply
    # does nothing and leaves you reading.
    ed = _reading_editor()
    assert ed._rendered_mode is True
    r0, _ = _rspan(ed, "fox")
    ed._begin_comment_for_span(r0, r0)                  # empty span → unmappable
    assert ed._rendered_mode is True                    # stayed in the reading view
    assert ed._authoring_span is None
    assert ed._comment_field is None
