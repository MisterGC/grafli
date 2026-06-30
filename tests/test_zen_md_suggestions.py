"""Reading view renders CriticMarkup suggestions as track-changes: removed text
struck in the body mono, added text in the handwriting note font (long rewrites
fall back to the body font on a faint wash). Comments still highlight as before."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from grafli.constants import NOTE_FONT_FAMILY  # noqa: E402
from grafli.zen_md import ZenMarkdownEditor  # noqa: E402


def _reading_editor(text: str) -> ZenMarkdownEditor:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 600)
    parent.show()
    ed = ZenMarkdownEditor(parent, text, title="t")
    ed._parent = parent
    ed._toggle_rendered()
    return ed


def _fmt_of(ed, word):
    """Char format of the first fragment containing ``word`` in the read view."""
    doc = ed._rendered.document()
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if word in frag.text():
                return frag.charFormat()
            it += 1
        block = block.next()
    return None


def test_no_raw_markup_in_rendered_text():
    ed = _reading_editor("the {--very --}{~~quick~>swift~~} {++brown ++}fox\n")
    txt = ed._rendered.document().toPlainText()
    for marker in ("{++", "{--", "{~~", "~>", "==}", "<<}"):
        assert marker not in txt


def test_removed_text_is_struck_and_red():
    ed = _reading_editor("the {--very --}quick fox\n")
    fmt = _fmt_of(ed, "very")
    assert fmt is not None
    assert fmt.fontStrikeOut() is True
    assert fmt.foreground().color().name() == "#c53030"


def test_added_text_is_handwritten_and_blue():
    ed = _reading_editor("the {++brown ++}fox\n")
    fmt = _fmt_of(ed, "brown")
    assert fmt is not None
    assert fmt.fontStrikeOut() is False
    assert fmt.fontFamilies() == [NOTE_FONT_FAMILY]
    assert fmt.foreground().color().name() == "#2b6cb0"


def test_substitution_shows_struck_old_and_handwritten_new():
    ed = _reading_editor("the {~~quick~>swift~~} fox\n")
    old = _fmt_of(ed, "quick")
    new = _fmt_of(ed, "swift")
    assert old.fontStrikeOut() is True
    assert new.fontFamilies() == [NOTE_FONT_FAMILY] and new.fontStrikeOut() is False


def test_long_rewrite_uses_wash_not_handwriting():
    long = "x " * 60   # > ZEN_MD_SUGGEST_LONG chars
    ed = _reading_editor(f"intro {{++{long}++}}done\n")
    fmt = _fmt_of(ed, "x x x")
    assert fmt is not None
    assert fmt.fontFamilies() != [NOTE_FONT_FAMILY]   # body font, not handwriting
    assert fmt.background().color().alpha() > 0        # a faint wash is present


def test_comments_still_highlight_alongside_suggestions():
    ed = _reading_editor("a {==span==}{>>why?<<} and {++added++} here\n")
    # comment span still tracked for reveal/navigation
    assert len(ed._rendered_comments) == 1
    _s, _e, comment = ed._rendered_comments[0]
    assert comment.span == "span" and comment.body == "why?"


# ── review: navigate + accept / reject ──

SRC = "the {--very --}{~~quick~>swift~~} {++brown ++}fox\n"


def _key(ed, key, shift=False):
    mods = (Qt.KeyboardModifier.ShiftModifier if shift
            else Qt.KeyboardModifier.NoModifier)
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, "", False, 1)
    return ed._handle_rendered_key(ev)


def _caret_on(ed, word):
    txt = ed._rendered.document().toPlainText()
    cur = ed._rendered.textCursor()
    cur.setPosition(txt.index(word))
    ed._rendered.setTextCursor(cur)


def test_three_suggestions_one_unit_per_substitution():
    ed = _reading_editor(SRC)
    # delete + substitute + insert = 3 reviewable units (substitution is ONE)
    assert len(ed._rendered_suggestions) == 3


def test_bracket_s_navigates_suggestions():
    ed = _reading_editor(SRC)
    _key(ed, Qt.Key.Key_BracketRight)      # ]
    _key(ed, Qt.Key.Key_S)                 # s -> first suggestion
    assert ed._rendered.textCursor().hasSelection()
    first = ed._suggestion_at_position(ed._rendered.textCursor().selectionStart())
    assert first == 0


def test_accept_substitution_under_caret():
    ed = _reading_editor(SRC)
    _caret_on(ed, "swift")
    _key(ed, Qt.Key.Key_A)
    assert ed._editor.toPlainText() == "the {--very --}swift {++brown ++}fox\n"


def test_reject_deletion_keeps_original():
    ed = _reading_editor(SRC)
    _caret_on(ed, "very")
    _key(ed, Qt.Key.Key_X)
    assert ed._editor.toPlainText() == "the very {~~quick~>swift~~} {++brown ++}fox\n"


def test_accept_all_and_reject_all():
    ed = _reading_editor(SRC)
    _key(ed, Qt.Key.Key_A, shift=True)
    assert ed._editor.toPlainText() == "the swift brown fox\n"
    ed2 = _reading_editor(SRC)
    _key(ed2, Qt.Key.Key_X, shift=True)
    assert ed2._editor.toPlainText() == "the very quick fox\n"


def test_accept_is_undoable():
    ed = _reading_editor(SRC)
    _caret_on(ed, "brown")
    _key(ed, Qt.Key.Key_A)                 # accept the insertion
    assert "{++brown ++}" not in ed._editor.toPlainText()
    ed._editor.undo()
    assert "{++brown ++}" in ed._editor.toPlainText()   # markup restored


def test_accept_advances_caret_to_next_suggestion():
    ed = _reading_editor(SRC)
    _caret_on(ed, "very")                  # first suggestion (deletion)
    _key(ed, Qt.Key.Key_A)                 # accept -> caret should land on next
    idx = ed._suggestion_at_position(ed._rendered.textCursor().position())
    assert idx == 0 and len(ed._rendered_suggestions) == 2
