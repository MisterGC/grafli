"""Inline code in a Markdown note renders in the bundled mono face headless,
whatever the note's own face (#219)."""

from __future__ import annotations

import os

import pytest
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication

from grafli.constants import FONT_FAMILY
from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    from grafli.fonts import register_bundled_fonts
    register_bundled_fonts()
    return app


def _code_fragments(doc):
    """The fixed-pitch fragments of a laid-out note document."""
    frags = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().fontFixedPitch():
                frags.append(frag)
            it += 1
        block = block.next()
    return frags


@pytest.mark.parametrize("face", ["", " !sans", " !mono"])
def test_inline_code_in_a_markdown_note_resolves_to_jetbrains_mono(face):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(
        '#!grafli v1\n@ note n 0,0 "md: run `grep -n` here"' + face + '\n'))
    doc = view._note_items["n"]._md_document()
    frags = _code_fragments(doc)
    assert [f.text() for f in frags] == ["grep -n"]
    assert QFontInfo(frags[0].charFormat().font()).family() == FONT_FAMILY
