"""Tests for the Flows editor panel logic (grafli.flowspanel + view API)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SAMPLE = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ box b "B" 300,0 120x60
@ box c "C" 600,0 120x60
@ bookmark bmA "A" @a
@ bookmark bmB "B" @b
@ bookmark bmC "C" @c
@ flow tour "Tour" bmA bmB:5 bmC "desc"
"""


def _app():
    return QApplication.instance() or QApplication([])


def _panel(board):
    _app()
    from grafli.view import GrafliView
    from grafli.flowspanel import FlowsPanel
    view = GrafliView()
    view.load_board(board)
    panel = FlowsPanel()
    panel.attach(view)
    return view, panel


def test_flows_collapsed_by_default():
    board = parse(SAMPLE)
    view, panel = _panel(board)
    assert panel._expanded_flows == set()
    assert panel._bookmarks_expanded is False
    panel._toggle_flow("tour")
    assert "tour" in panel._expanded_flows


def test_add_after_selected_step():
    board = parse(SAMPLE)
    view, panel = _panel(board)
    flow = board.flow_by_id("tour")
    panel._select_step(flow, 0)            # select bmA
    panel._add_to_flow(flow, "bmC")        # insert after index 0
    assert [s.ref for s in flow.steps] == ["bmA", "bmC", "bmB", "bmC"]
    assert view._active_step_index == 1


def test_move_and_remove_step():
    board = parse(SAMPLE)
    view, panel = _panel(board)
    flow = board.flow_by_id("tour")
    panel._move_step(flow, 0, 1)           # A <-> B
    assert [s.ref for s in flow.steps] == ["bmB", "bmA", "bmC"]
    panel._remove_step(flow, 1)            # drop A
    assert [s.ref for s in flow.steps] == ["bmB", "bmC"]


def test_set_dwell_parses_and_clears():
    board = parse(SAMPLE)
    view, panel = _panel(board)
    flow = board.flow_by_id("tour")
    panel._set_dwell(flow.steps[0], "3.5")
    assert flow.steps[0].dwell == 3.5
    panel._set_dwell(flow.steps[0], "")     # blank clears to default
    assert flow.steps[0].dwell is None


def test_delete_bookmark_prunes_flow_steps():
    board = parse(SAMPLE)
    view, panel = _panel(board)
    view.delete_bookmark(board.bookmark_by_id("bmB"))
    assert board.bookmark_by_id("bmB") is None
    assert "bmB" not in [s.ref for s in board.flow_by_id("tour").steps]


def test_capture_inserts_after_selected_step():
    from PySide6.QtWidgets import QInputDialog
    board = parse(SAMPLE)
    view, panel = _panel(board)
    flow = board.flow_by_id("tour")
    panel._select_step(flow, 1)             # select bmB
    QInputDialog.getText = staticmethod(lambda *a, **k: ("New", True))
    QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("", True))
    view._box_items["c"].setSelected(True)
    view.capture_bookmark("logical")
    refs = [s.ref for s in flow.steps]
    assert len(refs) == 4
    assert board.bookmark_by_id(refs[2]).label == "New"  # inserted after idx 1
    assert view._active_step_index == 2


def test_inline_label_and_description_edit():
    board = parse(SAMPLE)
    view, panel = _panel(board)
    bm = board.bookmark_by_id("bmA")
    panel._set_label(bm, "  Renamed  ")
    assert bm.label == "Renamed"
    panel._set_description(bm, "now with detail")
    assert bm.description == "now with detail"
    # empty label is ignored (keeps previous)
    panel._set_label(bm, "   ")
    assert bm.label == "Renamed"


def test_play_mode_cycles_and_loops():
    from grafli.flows import FlowPlayer
    board = parse(SAMPLE)
    view, panel = _panel(board)
    p = FlowPlayer(view, board.flow_by_id("tour"))
    p.start()
    assert p.mode == "paused"
    p.cycle_play_mode(); assert p.mode == "playing"
    p.cycle_play_mode(); assert p.mode == "loop"
    p.cycle_play_mode(); assert p.mode == "paused"
    # loop wraps at the end; plain playing stops
    p.mode = "loop"; p.index = len(p.flow.steps) - 1; p.next()
    assert p.index == 0
    p.mode = "playing"; p.index = len(p.flow.steps) - 1; p.next()
    assert p.mode == "paused"
    p.stop()


def test_present_mode_enters_and_exits():
    app = _app()
    from grafli.app import MainWindow
    import tempfile, os
    path = os.path.join(tempfile.gettempdir(), "present_test.grafli")
    with open(path, "w") as f:
        f.write(SAMPLE)
    w = MainWindow(path)
    w.resize(900, 600)
    w.show()
    w._side_panel.setVisible(True)        # make chrome visible to test restore
    app.processEvents()
    assert w._side_panel.isVisible()

    w._present_current()
    app.processEvents()
    assert w._presenting
    assert not w._side_panel.isVisible()  # chrome hidden while presenting
    assert w._view._flow_player is not None

    # Esc ends playback, which leaves present mode and restores chrome.
    w._view._flow_player.stop()
    app.processEvents()
    assert not w._presenting
    assert w._side_panel.isVisible()      # restored to its prior state
    w.close()


def test_new_and_delete_flow():
    board = parse(SAMPLE)
    view, panel = _panel(board)
    f = view.create_flow("Second")
    assert f.id in [fl.id for fl in board.flows]
    view.delete_flow(f)
    assert f.id not in [fl.id for fl in board.flows]
