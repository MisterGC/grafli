"""Regression: a note with an explicit (wrapping) width stays fully clickable.

QGraphicsSimpleTextItem's C++ hit-test is keyed on the base, *unwrapped*
single-line text geometry. Once the width handle wraps the note, that geometry
diverges from what we paint, so scene.itemAt() (and the Alt-drag connector that
relies on it) only fired on the first line — the hit area collapsed to the top.
NoteItem.contains() overrides the test to use the real painted shape.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from grafli.format import parse  # noqa: E402
from grafli.view import GrafliView  # noqa: E402


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(1000, 800)
    return view


def test_wrapped_note_is_hittable_below_the_first_line():
    view = _view(
        '#!grafli v1\n@ note n1 0,0 "A reasonably long single line note that '
        'will wrap once its width is narrowed down with the handle."\n'
    )
    note = next(iter(view._note_items.values()))
    note.setSelected(True)

    # Simulate setting an explicit (narrow) width via the resize handle.
    note.note.wrap_chars_explicit = True
    note.note.wrap_chars = 26
    note.prepareGeometryChange()

    br = note.boundingRect()
    # The note must have actually wrapped to multiple lines for this to bite.
    assert br.height() > 40

    # Every point down the visible note (not just the first line) resolves to
    # the note — this is the surface the Alt-drag connector hit-tests against.
    for fy in (0.1, 0.3, 0.5, 0.7, 0.9):
        scene_pt = note.mapToScene(
            QPointF(br.x() + 0.5 * br.width(), br.y() + fy * br.height()))
        hit = view._scene.itemAt(scene_pt, view.transform())
        assert hit is note, f"miss at fy={fy} (hit area collapsed to top)"


def test_note_contains_matches_painted_shape():
    view = _view('#!grafli v1\n@ note n1 0,0 "Some note text that wraps nicely '
                 'across several lines when narrowed."\n')
    note = next(iter(view._note_items.values()))
    note.note.wrap_chars_explicit = True
    note.note.wrap_chars = 22
    note.prepareGeometryChange()

    br = note.boundingRect()
    inside = QPointF(br.center())
    outside = QPointF(br.right() + 50, br.bottom() + 50)
    assert note.contains(inside)
    assert not note.contains(outside)
