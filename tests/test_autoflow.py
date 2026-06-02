"""Auto-generated flows: walk forward arrows from a start node."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SRC = """\
#!grafli v2
@ box box1 "Start" 0,0 100x60
@ box box2 "Mid" 200,0 100x60
@ box box3 "Fork" 400,0 100x60
@ box box4 "BranchA" 600,0 100x60
@ box box5 "BranchB" 600,200 100x60
@ box p1 "Parent" 0,400 300x200
@ box c1 "Child" 40,460 100x60 >p1
@ arrow box1 -> box2 ""
@ arrow box2 -> box3 ""
@ arrow box3 -> box4 ""
@ arrow box3 -> box5 ""
@ arrow box4 <-> box5 ""
@ arrow box1 -- p1 ""
"""


def _view(src: str = _SRC) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    return view


def test_path_stops_at_branch():
    view = _view()
    path, reason = view._auto_flow_path("box1")
    assert path == ["box1", "box2", "box3"]
    assert reason == "branch"


def test_strict_forward_excludes_bidirectional_and_headless():
    view = _view()
    assert view._forward_targets("box4") == []        # <-> is not strict
    assert view._forward_targets("box1") == ["box2"]  # -- p1 ignored


def test_cycle_stops():
    view = _view("""\
#!grafli v2
@ box a "A" 0,0 80x50
@ box b "B" 200,0 80x50
@ arrow a -> b ""
@ arrow b -> a ""
""")
    path, reason = view._auto_flow_path("a")
    assert path == ["a", "b"]
    assert reason == "cycle"


def test_create_auto_flow_makes_isolated_titled_steps():
    view = _view()
    flow = view.create_auto_flow("box1", "Demo")
    assert flow.auto_start == "box1"
    assert len(flow.steps) == 3
    board = view.board
    bms = [board.bookmark_by_id(s.ref) for s in flow.steps]
    assert all(bm.isolate for bm in bms)
    assert [bm.label for bm in bms] == ["Start", "Mid", "Fork"]
    assert bms[0].focus == ["box1"]


def test_parent_step_expands_to_subtree():
    view = _view()
    flow = view.create_auto_flow("p1", "Parent flow")
    bm = view.board.bookmark_by_id(flow.steps[0].ref)
    assert bm.focus == ["p1", "c1"]


def test_regenerate_keeps_title_and_reclaims_bookmarks():
    view = _view()
    flow = view.create_auto_flow("box1", "Demo")
    n_bm = len(view.board.bookmarks)
    view.regenerate_auto_flow(flow)
    assert flow.label == "Demo"             # title page preserved
    assert len(flow.steps) == 3
    assert len(view.board.bookmarks) == n_bm  # no orphan accumulation


def test_auto_start_round_trips():
    view = _view()
    view.create_auto_flow("box1", "Demo")
    out = serialize(view.board)
    assert "~auto=box1" in out
    assert parse(out).flows[-1].auto_start == "box1"


def test_manual_scope_of_parent_includes_descendants():
    view = _view()
    view._box_items["p1"].setSelected(True)
    focus = view._expand_focus_to_subtrees(["p1"])
    assert focus == ["p1", "c1"]
