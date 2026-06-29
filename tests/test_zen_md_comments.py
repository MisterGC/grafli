"""Zen reading view: inline CriticMarkup comments are stripped from the prose,
their span highlighted, and the comment body kept out of the render."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from grafli import md_comments  # noqa: E402
from grafli.constants import ZEN_MD_COMMENT_HL  # noqa: E402
from grafli.zen_md import ZenMarkdownEditor  # noqa: E402

MD = (
    "# Notes\n\n"
    "The {==quarterly numbers==}{>>are these pre-audit?<<} look off here.\n"
)


def _editor(text: str) -> ZenMarkdownEditor:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1000, 700)
    ed = ZenMarkdownEditor(parent, text, title="T")
    ed._parent = parent  # keep a ref alive
    return ed


def test_comment_body_and_markers_absent_from_render():
    ed = _editor(MD)
    ed._toggle_rendered()
    shown = ed._rendered.toPlainText()
    # span text survives, untouched
    assert "quarterly numbers" in shown
    # comment body, CriticMarkup markers, and sentinels are all gone
    assert "are these pre-audit?" not in shown
    assert "{==" not in shown and "{>>" not in shown
    assert md_comments.SENTINEL_START not in shown
    assert md_comments.SENTINEL_END not in shown


def test_span_is_highlighted():
    ed = _editor(MD)
    ed._toggle_rendered()
    doc = ed._rendered.document()
    cur = doc.find("quarterly numbers")
    assert not cur.isNull()
    # every char of the span carries the comment highlight background
    start, end = cur.selectionStart(), cur.selectionEnd()
    for pos in range(start + 1, end + 1):
        cur.setPosition(pos)
        assert cur.charFormat().background().color() == ZEN_MD_COMMENT_HL


def test_uncommented_text_is_not_highlighted():
    ed = _editor(MD)
    ed._toggle_rendered()
    doc = ed._rendered.document()
    cur = doc.find("look off here")
    assert not cur.isNull()
    cur.setPosition(cur.selectionStart() + 1)
    assert cur.charFormat().background().color() != ZEN_MD_COMMENT_HL


def test_plain_markdown_renders_unchanged():
    ed = _editor("# Heading\n\nplain text only\n")
    ed._toggle_rendered()
    assert "<h1" in ed._rendered.toHtml().lower()
    assert "plain text only" in ed._rendered.toPlainText()
