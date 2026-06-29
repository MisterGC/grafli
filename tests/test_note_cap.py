"""An over-long note is capped to a readable height on the canvas, with a
clear 'open to read the rest' affordance — the full text stays reachable by
opening the note (its boundingRect is the *displayed* footprint)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontMetricsF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from grafli.format import Note  # noqa: E402
from grafli.items import NoteItem  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _note(text: str) -> NoteItem:
    _app()
    return NoteItem(Note(id="n", x=0, y=0, text=text))


def test_long_note_is_capped_and_reports_hidden_lines():
    item = _note("\n".join(f"line {i}" for i in range(1, 31)))
    full = item.boundingRect().height()
    assert item._display_truncated is True
    assert item._display_hidden_lines > 0
    # Capped to the line budget (computed from the real font), well under the
    # natural 30-line height.
    line_h = QFontMetricsF(item._note_font()).height()
    cap = item._PAD + item._DISPLAY_CAP_LINES * line_h + item._DISPLAY_FOOTER_H
    assert abs(full - cap) < 1
    assert full < item._PAD + 30 * line_h


def test_short_note_is_not_capped():
    item = _note("just\nthree\nlines")
    assert item._display_truncated is False
    assert item._display_hidden_lines == 0


def test_cap_survives_the_boundingrect_cache():
    item = _note("\n".join(f"line {i}" for i in range(1, 31)))
    item.boundingRect()                      # populate cache
    item._display_truncated = None           # clobber, then read from cache
    item.boundingRect()
    assert item._display_truncated is True
