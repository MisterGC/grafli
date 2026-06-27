"""Zen markdown editor: ⌘R toggles a read-only rendered view, ⌘↵ toggles
full-window width."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
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
    ed = _editor()
    ed._toggle_rendered()
    sb = ed._rendered.verticalScrollBar()
    # Drive the scrollbar via a fixed range (no real window layout in the test).
    sb.setRange(0, 1000)
    sb.setValue(0)
    assert _press(ed, Qt.Key.Key_J) and sb.value() > 0      # j scrolls down
    assert _press(ed, Qt.Key.Key_K) and sb.value() == 0     # k scrolls up
    assert _press(ed, Qt.Key.Key_G, Qt.KeyboardModifier.ShiftModifier)
    assert sb.value() == sb.maximum()                        # G -> bottom
    _press(ed, Qt.Key.Key_G)
    _press(ed, Qt.Key.Key_G)
    assert sb.value() == 0                                    # gg -> top
