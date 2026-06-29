"""Clickable GFM task lists in markdown notes: the pure source toggle
(`md_note.toggle_task`), checkbox hit-testing, and the persist+undo path."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF
from PySide6.QtGui import QTextBlockFormat
from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize
from grafli.md_note import toggle_task
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    return QApplication.instance() or QApplication([])


def _view(src: str) -> GrafliView:
    _app()
    view = GrafliView()
    view.load_board(parse("#!grafli v1\n" + src))
    view.resize(900, 600)
    view._mode = Mode.SELECT
    return view


# ── pure toggle ─────────────────────────────────────────────────

def test_toggle_flips_unchecked_to_checked():
    out, changed = toggle_task("- [ ] one\n- [x] two", 0)
    assert changed and out == "- [x] one\n- [x] two"


def test_toggle_flips_checked_to_unchecked():
    out, changed = toggle_task("- [ ] one\n- [x] two", 1)
    assert changed and out == "- [ ] one\n- [ ] two"


def test_toggle_uppercase_x_is_done():
    out, changed = toggle_task("- [X] done", 0)
    assert changed and out == "- [ ] done"


def test_toggle_index_picks_nth_task_only():
    # Non-task lines (heading, blank, prose) are skipped by the index.
    text = "# Plan\n\nsome prose\n- [ ] a\n- [ ] b\n- [ ] c"
    out, changed = toggle_task(text, 2)
    assert changed and out.splitlines()[-1] == "- [x] c"
    assert out.splitlines()[3] == "- [ ] a"   # others untouched


def test_toggle_ordered_and_nested_markers():
    text = "1. [ ] first\n  - [x] nested"
    out, changed = toggle_task(text, 1)
    assert changed and out == "1. [ ] first\n  - [ ] nested"


def test_toggle_out_of_range_is_noop():
    out, changed = toggle_task("- [ ] only", 5)
    assert not changed and out == "- [ ] only"


def test_toggle_is_byte_minimal():
    # Trailing text, indentation and surrounding lines stay byte-identical.
    text = "intro\n- [ ] task one (keep me)\nclose"
    out, _ = toggle_task(text, 0)
    assert out == "intro\n- [x] task one (keep me)\nclose"


# ── hit-test + persist ──────────────────────────────────────────

_MD_SRC = (
    '@ note t 0,0 """\n'
    'md:\n'
    '- [ ] one\n'
    '- [x] two\n'
    '- [ ] three\n'
    '"""\n'
)


def _task_rects(item):
    doc = item._md_document()
    layout = doc.documentLayout()
    rects = []
    block = doc.begin()
    while block.isValid():
        if block.blockFormat().marker() in (
            QTextBlockFormat.MarkerType.Checked,
            QTextBlockFormat.MarkerType.Unchecked,
        ):
            rects.append(layout.blockBoundingRect(block))
        block = block.next()
    return rects


def test_hit_test_maps_click_to_task_index():
    view = _view(_MD_SRC)
    item = view._note_items["t"]
    rects = _task_rects(item)
    assert len(rects) == 3            # three checkboxes rendered
    pad = item._PAD
    for i, r in enumerate(rects):
        pos = QPointF(pad + 4, r.center().y() + pad)
        assert item._md_task_index_at(pos) == i


def test_click_outside_any_task_line_returns_none():
    view = _view(_MD_SRC)
    item = view._note_items["t"]
    # Far below the last task line — no checkbox there.
    assert item._md_task_index_at(QPointF(4, 10_000)) is None


def test_toggle_md_task_persists_and_is_undoable():
    view = _view(_MD_SRC)
    item = view._note_items["t"]
    undo_before = len(view._undo_stack)
    view._toggle_md_task(item, 0)          # flip "one" on
    assert "- [x] one" in view.board.notes[0].text
    assert "- [x] two" in view.board.notes[0].text   # untouched
    assert len(view._undo_stack) == undo_before + 1
    view._undo()
    assert "- [ ] one" in view.board.notes[0].text


def test_toggle_md_task_roundtrips_through_serialize():
    view = _view(_MD_SRC)
    item = view._note_items["t"]
    view._toggle_md_task(item, 2)          # flip "three" on
    assert "- [x] three" in serialize(view.board)
