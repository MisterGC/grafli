"""Pasting text: an active editor receives the clipboard text, and the most
recently copied thing always wins over a stale internal element copy.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    return QApplication.instance() or QApplication([])


def _view(src: str) -> GrafliView:
    _app()
    view = GrafliView()
    view._grid_mode = "off"
    view.load_board(parse(src))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    return view


def _set_clip(text: str):
    QApplication.clipboard().setText(text)


_SRC = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ note n1 40,200 "first note"
"""


def test_paste_into_note_editor_inserts_text_not_element():
    view = _view(_SRC)
    note = view._note_items["n1"]
    # Copy the note internally (the would-be shadowing element).
    note.setSelected(True)
    view._copy_selected()
    notes_before = len(view.board.notes)

    # Now an external link is copied and the user edits a note to paste it.
    _set_clip("https://example.com/link")
    view._start_editing(note)
    assert view._note_widget is not None
    view._paste()

    assert "https://example.com/link" in view._note_widget.toPlainText()
    # No new element was created — it went into the text.
    assert len(view.board.notes) == notes_before


def test_paste_into_box_label_editor_inserts_text():
    view = _view(_SRC)
    box = view._box_items["a"]
    box.setSelected(True)
    view._copy_selected()
    _set_clip("PASTED")
    view._start_editing(box)
    assert view._editor is not None
    view._paste()
    assert "PASTED" in view._editor.toPlainText()


def test_latest_external_text_wins_over_internal_copy():
    # Copy a note internally, then copy a link externally afterwards: pasting in
    # select mode drops the link as a new note, not a duplicate of the element.
    view = _view(_SRC)
    _set_clip("old-clip")            # whatever was there before the yank
    view._note_items["n1"].setSelected(True)
    view._copy_selected()
    _set_clip("https://newer.link")  # external copy AFTER the internal yank

    view._scene.clearSelection()
    view._paste()

    texts = [n.text for n in view.board.notes]
    assert "https://newer.link" in texts
    # The internal note was NOT duplicated.
    assert texts.count("first note") == 1


def test_internal_copy_still_pastes_when_clipboard_unchanged():
    # No external copy after the yank → the internal element wins as before.
    view = _view(_SRC)
    _set_clip("baseline")
    view._note_items["n1"].setSelected(True)
    view._copy_selected()
    # clipboard left unchanged (still "baseline")
    view._scene.clearSelection()
    before = len(view.board.notes)
    view._paste()
    after = len(view.board.notes)
    assert after == before + 1                       # duplicated the note
    assert [n.text for n in view.board.notes].count("first note") == 2
