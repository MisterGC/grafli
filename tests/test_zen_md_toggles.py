"""Zen markdown editor: ⌘R toggles a read-only rendered view, ⌘↵ toggles
full-window width."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from grafli.constants import _CTRL_MOD  # noqa: E402
from grafli.zen_md import ZenMarkdownEditor  # noqa: E402

MD = "# Heading\n\nSome **bold** text and a list:\n\n- one\n- two\n"


def _editor() -> ZenMarkdownEditor:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1000, 700)
    ed = ZenMarkdownEditor(parent, MD, title="T")
    ed._parent = parent  # keep a ref alive
    return ed


def test_rendered_toggle_swaps_editor_for_rendered_view():
    # isHidden() (explicit hide state) rather than isVisible() — the parent
    # isn't shown in the test, so isVisible() is False for both regardless.
    ed = _editor()
    assert not ed._editor.isHidden() and ed._rendered.isHidden()
    ed._toggle_rendered()
    assert not ed._rendered.isHidden() and ed._editor.isHidden()
    # The Markdown is actually rendered (heading became an <h1>).
    assert "<h1" in ed._rendered.toHtml().lower()
    ed._toggle_rendered()
    assert not ed._editor.isHidden() and ed._rendered.isHidden()


def test_toggle_keeps_caret_position_both_directions():
    from PySide6.QtGui import QTextCursor
    md = ("# Title\n\n" +
          "\n\n".join(f"Paragraph {i} has word marker{i} inside." for i in range(40)))
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(700, 500)
    ed = ZenMarkdownEditor(parent, md, title="t")
    ed._parent = parent

    def word_at(w, pos):
        c = w.textCursor()
        c.setPosition(pos)
        c.select(QTextCursor.SelectionType.WordUnderCursor)
        return c.selectedText()

    def put_caret(w, pos):
        c = w.textCursor()
        c.setPosition(pos)
        w.setTextCursor(c)

    # caret on marker25 in the source → toggle to read → same word, not the top
    put_caret(ed._editor, ed._editor.toPlainText().index("marker25"))
    ed._toggle_rendered()
    rp = ed._rendered.textCursor().position()
    assert word_at(ed._rendered, rp) == "marker25"
    assert rp > 50                          # not snapped to the document top

    # move to marker10 in read → toggle back to write → same word
    put_caret(ed._rendered, ed._rendered.document().toPlainText().index("marker10"))
    ed._toggle_rendered()
    assert word_at(ed._editor, ed._editor.textCursor().position()) == "marker10"


def test_entering_read_mode_settles_scroll_range():
    # Regression: Qt lays the rendered doc out lazily and reports an
    # over-estimated scroll range until the event loop settles it. Jumping (G)
    # before that landed in the estimated region and scrolling back up stopped
    # short until 'gg' forced a relayout. Entering read mode now settles the
    # layout, so the scrollbar max matches the real document height immediately.
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 600)
    parent.show()
    big = "# Top\n\n" + "\n\n".join(
        f"## Section {i}\n\n" + ("word%d " % i) * 40 for i in range(600))
    ed = ZenMarkdownEditor(parent, big, title="t")
    ed._parent = parent
    ed._toggle_rendered()
    sb = ed._rendered.verticalScrollBar()
    doc_h = ed._rendered.document().documentLayout().documentSize().height()
    # settled: max tracks the real document height (one viewport less), not the
    # inflated pre-layout estimate.
    assert sb.maximum() <= doc_h
    assert sb.maximum() >= doc_h - ed._rendered.viewport().height() - 50


def test_mode_flash_on_toggle():
    ed = _editor()
    ed._toggle_rendered()
    assert ed._mode_flash is not None
    assert ed._mode_flash.text() == "READ"
    assert not ed._mode_flash.isHidden()
    ed._toggle_rendered()
    assert ed._mode_flash.text() == "WRITE"


def test_full_width_toggle_grows_the_card():
    ed = _editor()
    ed._change_width(0)                 # known baseline — content width persists
    column_w = ed._card_rect().width()  # to real QSettings, so reset it first
    ed._toggle_full_width()
    full_w = ed._card_rect().width()
    assert full_w > column_w
    assert full_w >= ed.width() - 81   # ~fills the window
    ed._toggle_full_width()
    assert ed._card_rect().width() == column_w


def test_width_steps_widen_and_narrow_the_column():
    ed = _editor()
    ed._change_width(0)                  # known baseline (default width)
    base = ed._card_rect().width()
    ed._change_width(+1)
    assert ed._card_rect().width() > base
    ed._change_width(-1)
    assert ed._card_rect().width() == base


def test_width_step_reset_returns_to_default():
    from grafli.constants import ZEN_MD_MAX_WIDTH
    ed = _editor()
    ed._change_width(+1)
    ed._change_width(+1)
    assert ed._content_width > ZEN_MD_MAX_WIDTH
    ed._change_width(0)
    assert ed._content_width == ZEN_MD_MAX_WIDTH


def test_width_narrow_clamps_at_minimum():
    from grafli.constants import ZEN_MD_MAX_WIDTH_MIN
    ed = _editor()
    for _ in range(50):
        ed._change_width(-1)
    assert ed._content_width == ZEN_MD_MAX_WIDTH_MIN


def test_width_step_exits_full_width_mode():
    ed = _editor()
    ed._toggle_full_width()
    assert ed._full_width is True
    ed._change_width(+1)
    assert ed._full_width is False


def test_ctrl_shift_arrows_drive_width():
    from grafli.constants import ZEN_MD_MAX_WIDTH
    shift_ctrl = _CTRL_MOD | Qt.KeyboardModifier.ShiftModifier
    ed = _editor()
    ed._change_width(0)                  # known baseline (default width)
    assert _press(ed, Qt.Key.Key_Right, shift_ctrl)
    assert ed._content_width > ZEN_MD_MAX_WIDTH
    assert _press(ed, Qt.Key.Key_Left, shift_ctrl)
    assert ed._content_width == ZEN_MD_MAX_WIDTH
    ed._change_width(+1)
    assert _press(ed, Qt.Key.Key_Down, shift_ctrl)   # reset
    assert ed._content_width == ZEN_MD_MAX_WIDTH


def test_opens_editable_with_focus_dim_off():
    # Consolidated: no read-only source mode; reading is the rendered view.
    ed = _editor()
    assert ed._read_only is False
    assert ed._editor.isReadOnly() is False
    assert ed._focus_enabled is False           # section dim off by default
    assert not hasattr(ed, "_toggle_write_mode")


def test_focus_dim_toggles():
    ed = _editor()
    ed._toggle_focus()
    assert ed._focus_enabled is True
    ed._toggle_focus()
    assert ed._focus_enabled is False


def _press(ed, key, mod=Qt.KeyboardModifier.NoModifier):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mod)
    consumed = ed._handle_key(ev)
    return consumed


def test_rendered_view_supports_vim_navigation():
    # The read view is caret-based: motions move a text caret (visual-mode span
    # selection rides on the same caret). Use document-order motions that don't
    # depend on a laid-out viewport.
    ed = _editor()
    ed._toggle_rendered()

    def caret():
        return ed._rendered.textCursor().position()

    assert caret() == 0
    assert _press(ed, Qt.Key.Key_L) and caret() == 1         # l -> char right
    assert _press(ed, Qt.Key.Key_W) and caret() > 1          # w -> next word
    mid = caret()
    assert _press(ed, Qt.Key.Key_G, Qt.KeyboardModifier.ShiftModifier)
    assert caret() > mid                                      # G -> document end
    _press(ed, Qt.Key.Key_G)
    _press(ed, Qt.Key.Key_G)
    assert caret() == 0                                       # gg -> top


# ── F1 help is owned by the editor (shown in grafli and standalone textli) ──

def test_f1_opens_the_editor_help_dialog():
    ed = _editor()
    assert ed._help_dialog is None
    assert _press(ed, Qt.Key.Key_F1)          # consumed
    assert ed._help_dialog is not None        # its own dialog opened
    ed._help_dialog.close()


def test_f1_works_in_the_reading_view_too():
    ed = _editor()
    ed._toggle_rendered()
    assert _press(ed, Qt.Key.Key_F1)
    assert ed._help_dialog is not None
    ed._help_dialog.close()


def test_editor_help_covers_the_latest_features():
    from grafli.zen_md import editor_help_html
    html = editor_help_html()
    # reading-view review surface must be documented
    for token in ("Suggest a change", "Accept / reject", "Changes overview",
                  "Headings overview", "Clean preview", "CriticMarkup"):
        assert token in html
    # and the keys themselves
    for key in (">gc<", ">gh<", ">p<", ">s<", ">]s / [s<"):
        assert key in html
