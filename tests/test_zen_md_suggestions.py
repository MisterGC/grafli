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
    ed = ZenMarkdownEditor(parent, text, title="t")
    ed._parent = parent
    ed._suggest_animate = False   # deterministic: apply instantly (no timer)
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


def test_removed_text_has_painted_strike_not_char_strikeout():
    from PySide6.QtGui import QFont
    ed = _reading_editor("the {--very --}quick fox\n")
    fmt = _fmt_of(ed, "very")
    assert fmt is not None
    assert fmt.fontStrikeOut() is False                 # not the thin built-in line
    assert fmt.fontWeight() != QFont.Weight.Bold        # regular weight — no bolding
    # instead the view paints a strong strike over the removed range
    txt = ed._rendered.document().toPlainText()
    i = txt.index("very")
    assert any(s <= i < e for (s, e, _a) in ed._rendered._strikes)


def test_added_text_is_red_body_font():
    ed = _reading_editor("the {++brown ++}fox\n")
    fmt = _fmt_of(ed, "brown")
    assert fmt is not None
    assert fmt.fontStrikeOut() is False
    assert fmt.fontFamilies() != [NOTE_FONT_FAMILY]   # body font, not handwriting
    assert fmt.foreground().color().name() == "#a83e2e"


def test_substitution_paints_strike_over_old_and_reds_new():
    ed = _reading_editor("the {~~quick~>swift~~} fox\n")
    new = _fmt_of(ed, "swift")
    assert new.fontStrikeOut() is False
    assert new.foreground().color().name() == "#a83e2e"
    txt = ed._rendered.document().toPlainText()
    i = txt.index("quick")
    assert any(s <= i < e for (s, e, _a) in ed._rendered._strikes)   # old struck


def test_block_rewrite_is_red_body_font_no_wash():
    long = "x " * 60   # a long, block-sized addition
    ed = _reading_editor(f"intro {{++{long}++}}done\n")
    fmt = _fmt_of(ed, "x x x")
    assert fmt is not None
    assert fmt.fontFamilies() != [NOTE_FONT_FAMILY]     # body font (no handwriting)
    assert fmt.foreground().color().name() == "#a83e2e"  # same red as an inline add
    assert fmt.background().style() == Qt.BrushStyle.NoBrush   # no wash — just red


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


def test_lowercase_accept_advances_to_next_decision():
    # suggestions separated by plain text so the advance is observable
    ed = _reading_editor("a {--x --}b c d {++y ++}e\n")
    _caret_on(ed, "x")
    _key(ed, Qt.Key.Key_A)                 # accept + advance
    assert ed._editor.toPlainText() == "a b c d {++y ++}e\n"
    idx = ed._suggestion_at_position(ed._rendered.textCursor().position())
    assert idx == 0                        # advanced onto the remaining suggestion


def test_accept_all_and_reject_all():
    ed = _reading_editor(SRC)
    _key(ed, Qt.Key.Key_A, shift=True)     # ⇧A — accept all
    assert ed._editor.toPlainText() == "the swift brown fox\n"
    ed2 = _reading_editor(SRC)
    _key(ed2, Qt.Key.Key_X, shift=True)    # ⇧X — reject all
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


def test_substitution_exposes_removed_and_added_subranges():
    ed = _reading_editor("the {~~quick~>swift~~} fox\n")
    (s,) = ed._rendered_suggestions
    assert s.removed is not None and s.added is not None       # both, for the tween


def test_insertion_has_added_only_deletion_removed_only():
    ins = _reading_editor("the {++brown ++}fox\n")._rendered_suggestions[0]
    assert ins.removed is None and ins.added is not None
    dele = _reading_editor("the {--very --}fox\n")._rendered_suggestions[0]
    assert dele.removed is not None and dele.added is None


# ── animated accept/reject (Phase 5) ──

def test_animated_accept_defers_edit_until_finish():
    ed = _reading_editor(SRC)
    ed._suggest_animate = True             # turn the animation back on
    _caret_on(ed, "brown")
    before = ed._editor.toPlainText()
    _key(ed, Qt.Key.Key_A)                 # starts the animation
    assert ed._suggest_animator.busy() is True
    assert ed._editor.toPlainText() == before        # source not mutated yet
    ed._suggest_animator.finish()          # complete it now
    assert "{++brown ++}" not in ed._editor.toPlainText()   # edit landed
    assert ed._suggest_animator.busy() is False


def test_new_review_settles_previous_animation_first():
    ed = _reading_editor(SRC)
    ed._suggest_animate = True
    _caret_on(ed, "brown")
    _key(ed, Qt.Key.Key_A)                 # animation in flight (insertion)
    _caret_on(ed, "very")
    _key(ed, Qt.Key.Key_A)                 # should settle the first, then start next
    # first edit (insertion) has been applied by the settle
    assert "{++brown ++}" not in ed._editor.toPlainText()


# ── authoring: mark text and suggest an alternative (Phase 4) ──

def _select(ed, word):
    """Select the first occurrence of ``word`` in the read view."""
    txt = ed._rendered.document().toPlainText()
    i = txt.index(word)
    cur = ed._rendered.textCursor()
    cur.setPosition(i)
    cur.setPosition(i + len(word), cur.MoveMode.KeepAnchor)
    ed._rendered.setTextCursor(cur)


def _commit_field(ed, text):
    ed._comment_field.setPlainText(text)
    ed._commit_comment_field()


def test_author_substitution_wraps_the_selection():
    ed = _reading_editor("the quick fox\n")
    _select(ed, "quick")
    _key(ed, Qt.Key.Key_S)                 # s -> open the field
    assert ed._authoring_suggestion is True
    _commit_field(ed, "swift")
    assert ed._editor.toPlainText() == "the {~~quick~>swift~~} fox\n"


def test_author_deletion_on_empty_body():
    ed = _reading_editor("the very quick fox\n")
    _select(ed, "very")
    _key(ed, Qt.Key.Key_S)
    _commit_field(ed, "")                   # empty body on a selection = delete
    assert ed._editor.toPlainText() == "the {--very--} quick fox\n"


def test_author_insertion_at_caret():
    ed = _reading_editor("the fox\n")
    _caret_on(ed, "fox")
    _key(ed, Qt.Key.Key_S)                  # no selection -> insertion
    _commit_field(ed, "quick ")
    assert "{++quick ++}" in ed._editor.toPlainText()


def test_author_insertion_empty_is_abandoned():
    ed = _reading_editor("the fox\n")
    _caret_on(ed, "fox")
    _key(ed, Qt.Key.Key_S)
    _commit_field(ed, "")                   # inserting nothing -> no change
    assert ed._editor.toPlainText() == "the fox\n"


def test_author_cancel_leaves_source_untouched():
    ed = _reading_editor("the quick fox\n")
    _select(ed, "quick")
    _key(ed, Qt.Key.Key_S)
    ed._cancel_comment_field()              # Esc
    assert ed._editor.toPlainText() == "the quick fox\n"
    assert ed._authoring_suggestion is False


def test_author_refuses_overlap_with_existing_mark():
    ed = _reading_editor("the {~~quick~>swift~~} fox\n")
    _select(ed, "swift")                    # the added side of a substitution
    _key(ed, Qt.Key.Key_S)
    assert ed._authoring_suggestion is False   # refused — field never opened
    assert ed._editor.toPlainText() == "the {~~quick~>swift~~} fox\n"


def test_authored_suggestion_is_reviewable_and_undoable():
    ed = _reading_editor("the quick fox\n")
    _select(ed, "quick")
    _key(ed, Qt.Key.Key_S)
    _commit_field(ed, "swift")
    assert len(ed._rendered_suggestions) == 1   # it renders as a track-change
    ed._editor.undo()
    assert ed._editor.toPlainText() == "the quick fox\n"   # one undo step


# ── clean preview (`p`) and changes overview (`gc`) — Phase 6 ──

def test_preview_shows_accepted_prose_then_restores():
    ed = _reading_editor("the {~~quick~>swift~~} {++brown ++}fox\n")
    _key(ed, Qt.Key.Key_P)
    txt = ed._rendered.document().toPlainText()
    assert "swift" in txt and "brown" in txt and "quick" not in txt
    assert ed._preview is True
    assert ed._rendered_suggestions == [] and ed._rendered._strikes == []
    _key(ed, Qt.Key.Key_P)                 # back to track-changes
    assert ed._preview is False
    assert len(ed._rendered_suggestions) == 2


def test_preview_suppresses_authoring():
    ed = _reading_editor("the quick fox\n")
    _key(ed, Qt.Key.Key_P)                 # enter preview
    _select(ed, "quick")
    _key(ed, Qt.Key.Key_S)                 # s should do nothing in preview
    assert ed._authoring_suggestion is False
    assert ed._editor.toPlainText() == "the quick fox\n"


def test_gc_opens_overview_listing_every_mark():
    ed = _reading_editor(
        "a {--very --}{~~quick~>swift~~} {++brown ++}fox {==x==}{>>c<<} y\n")
    _key(ed, Qt.Key.Key_G)                 # pending g
    _key(ed, Qt.Key.Key_C)                 # gc
    assert ed._overview_overlay is not None
    kinds = {k for (_s, _e, k, _l) in ed._build_changes_list()}
    assert kinds == {"delete", "substitute", "insert", "comment"}


def test_gc_no_op_when_no_marks():
    ed = _reading_editor("plain prose, nothing to review\n")
    _key(ed, Qt.Key.Key_G)
    _key(ed, Qt.Key.Key_C)
    assert ed._overview_overlay is None


def test_overview_jump_selects_range_and_closes():
    ed = _reading_editor("a {--x --}b {++y ++}c\n")
    _key(ed, Qt.Key.Key_G)
    _key(ed, Qt.Key.Key_C)
    assert len(ed._overview_rows) == 2
    _key(ed, Qt.Key.Key_J)                 # move selection to the 2nd
    assert ed._overview_sel == 1
    _key(ed, Qt.Key.Key_Return)            # jump
    assert ed._overview_overlay is None
    assert ed._rendered.textCursor().hasSelection()


def test_overview_escape_closes():
    ed = _reading_editor("a {--x --}b\n")
    _key(ed, Qt.Key.Key_G)
    _key(ed, Qt.Key.Key_C)
    assert ed._overview_overlay is not None
    _key(ed, Qt.Key.Key_Escape)
    assert ed._overview_overlay is None


def test_overview_digit_jumps_directly():
    ed = _reading_editor("a {--x --}b {++y ++}c\n")
    _key(ed, Qt.Key.Key_G)
    _key(ed, Qt.Key.Key_C)
    _key(ed, Qt.Key.Key_2)                 # jump straight to the 2nd change
    assert ed._overview_overlay is None
    assert ed._rendered.textCursor().hasSelection()


def test_gh_opens_headings_overview():
    ed = _reading_editor("# First\n\nbody text\n\n## Second\n\nmore\n")
    _key(ed, Qt.Key.Key_G)
    _key(ed, Qt.Key.Key_H)                 # gh
    assert ed._overview_overlay is not None
    rows = ed._build_headings_list()
    assert [level for (_s, _e, level, _t) in rows] == [1, 2]
    assert [t for (_s, _e, _l, t) in rows] == ["First", "Second"]


def test_gh_no_op_without_headings():
    ed = _reading_editor("just a paragraph, no headings here\n")
    _key(ed, Qt.Key.Key_G)
    _key(ed, Qt.Key.Key_H)
    assert ed._overview_overlay is None


def test_gh_headings_refresh_after_accepting_a_change():
    # Accepting the deletion above the 2nd heading shifts its rendered position;
    # the list must be rebuilt (not cached) so `gh` stays correct next time.
    ed = _reading_editor("# First\n\nbody {--extra words --}here\n\n## Second\n")
    before = {t: s for (s, _e, _l, t) in ed._build_headings_list()}
    _caret_on(ed, "extra")
    _key(ed, Qt.Key.Key_A)                 # accept the deletion (removes the text)
    after = {t: s for (s, _e, _l, t) in ed._build_headings_list()}
    assert after["Second"] < before["Second"]   # heading moved up, list refreshed


def test_color_helpers():
    from PySide6.QtGui import QColor

    from grafli.zen_md_suggest import _lerp, _scaled_alpha
    faded = _scaled_alpha(QColor(255, 0, 0, 200), 0.0)
    assert faded.alpha() == 0
    mid = _lerp(QColor(0, 0, 0), QColor(10, 20, 40), 0.5)
    assert (mid.red(), mid.green(), mid.blue()) == (5, 10, 20)
