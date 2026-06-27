"""Zen markdown editor: ⌘R toggles a read-only rendered view, ⌘↵ toggles
full-window width."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

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


def test_full_width_toggle_grows_the_card():
    ed = _editor()
    column_w = ed._card_rect().width()
    ed._toggle_full_width()
    full_w = ed._card_rect().width()
    assert full_w > column_w
    assert full_w >= ed.width() - 81   # ~fills the window
    ed._toggle_full_width()
    assert ed._card_rect().width() == column_w
