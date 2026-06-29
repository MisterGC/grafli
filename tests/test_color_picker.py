"""Style-mode colour grid picker (s -> c): grid navigation, live preview,
commit (one undoable step) and cancel (revert, no undo)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.constants import COLOR_PALETTE
from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse("#!grafli v1\n" + src))
    view.resize(900, 600)
    view._mode = Mode.SELECT
    return view


def test_open_without_selection_is_noop():
    view = _view('@ box a "A" 0,0 100x50\n')
    view._open_color_picker()
    assert not view._color_picker_active


def test_open_starts_on_current_color():
    view = _view('@ box a "A" 0,0 100x50 %accent\n')
    view._box_items["a"].setSelected(True)
    view._open_color_picker()
    assert view._color_picker_active
    assert COLOR_PALETTE[view._color_picker_index][1] == "%accent"


def test_navigation_live_previews_and_clamps():
    view = _view('@ box a "A" 0,0 100x50\n')   # Default colour ""
    a = view._box_items["a"]
    a.setSelected(True)
    view._open_color_picker()
    assert view._color_picker_index == 0

    view._color_picker_move(1, 0)              # l -> next in row
    assert view._color_picker_index == 1
    assert a.box.color == COLOR_PALETTE[1][1]  # applied live

    view._color_picker_move(-1, 0)
    view._color_picker_move(-1, 0)             # clamps at left edge
    assert view._color_picker_index == 0

    cols = view._COLOR_GRID_COLS
    rows = (len(COLOR_PALETTE) + cols - 1) // cols
    view._color_picker_move(0, 1)              # j -> second row
    assert view._color_picker_index == cols
    for _ in range(rows + 1):                  # drive past the bottom
        view._color_picker_move(0, 1)
    assert view._color_picker_index == (rows - 1) * cols   # clamped, col 0


def test_commit_applies_and_is_undoable():
    view = _view('@ box a "A" 0,0 100x50\n')
    view._box_items["a"].setSelected(True)
    undo_before = len(view._undo_stack)
    view._open_color_picker()
    view._color_picker_move(1, 0)
    chosen = COLOR_PALETTE[1][1]
    view._commit_color_picker()
    assert not view._color_picker_active
    assert view.board.box_by_id("a").color == chosen
    assert view._last_box_color == chosen
    assert len(view._undo_stack) == undo_before + 1
    view._undo()
    assert view.board.box_by_id("a").color == ""   # back to Default


def test_cancel_reverts_without_undo():
    view = _view('@ box a "A" 0,0 100x50 %primary\n')
    a = view._box_items["a"]
    a.setSelected(True)
    undo_before = len(view._undo_stack)
    view._open_color_picker()
    view._color_picker_move(1, 0)
    assert a.box.color != "%primary"           # previewing something else
    view._cancel_color_picker()
    assert not view._color_picker_active
    assert view._box_items["a"].box.color == "%primary"
    assert len(view._undo_stack) == undo_before


def test_commit_recolors_whole_selection():
    view = _view('@ box a "A" 0,0 100x50\n@ box b "B" 200,0 100x50\n')
    view._box_items["a"].setSelected(True)
    view._box_items["b"].setSelected(True)
    view._open_color_picker()
    view._color_picker_move(0, 1)              # pick a row-2 colour
    chosen = COLOR_PALETTE[view._color_picker_index][1]
    view._commit_color_picker()
    assert view.board.box_by_id("a").color == chosen
    assert view.board.box_by_id("b").color == chosen
