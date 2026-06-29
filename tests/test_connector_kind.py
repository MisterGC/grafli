"""Connector kind: notes as first-class graph nodes (annotation vs graph edge)."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SRC = """\
#!grafli v2
@ box box1 "Start" 0,0 100x60
@ note n1 300,0 "Step"
@ note n2 600,0 "End"
@ note ann 0,200 "explains"
@ arrow box1 -> n1 "" ~kind=graph
@ arrow n1 -> n2 "" ~kind=graph
@ arrow box1 -> ann ""
"""


def _view(src: str = _SRC) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    return view


def test_resolver_explicit_and_derived():
    view = _view()
    graph_edge, _, annotation = view.board.arrows
    assert view._is_graph_edge(graph_edge)            # explicit ~kind=graph
    assert not view._is_annotation_link(graph_edge)
    assert view._is_annotation_link(annotation)       # derived: note endpoint


def test_auto_flow_traverses_note_graph_edges():
    view = _view()
    path, reason = view._auto_flow_path("box1")
    assert path == ["box1", "n1", "n2"]               # follows graph edges to notes
    assert reason == "end"


def test_note_step_is_labelless_textslide_box_is_titled():
    view = _view()
    flow = view.create_auto_flow("box1", "Notes")
    labels = [view.board.bookmark_by_id(s.ref).label for s in flow.steps]
    assert labels == ["Start", "", ""]                # box titled, notes blank


def test_toggle_flips_kind_and_sets_sticky():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 100x60
@ note n1 300,0 "note"
@ arrow box1 -> n1 ""
""")
    arrow = view.board.arrows[0]
    assert view._is_annotation_link(arrow)            # derived annotation
    view._select_arrow(arrow)
    view._set_arrow_mode("style")
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                                 Qt.KeyboardModifier.NoModifier, "a"))
    assert arrow.kind == "graph"
    assert view._last_connector_kind == "graph"
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                                 Qt.KeyboardModifier.NoModifier, "a"))
    assert arrow.kind == "annotation"


def test_sticky_applies_to_new_note_connector_only():
    view = _view()
    view._last_connector_kind = "graph"
    assert view._make_connector("n1", "n2").kind == "graph"   # note involved
    assert view._make_connector("box1", "box1").kind == ""    # box↔box: derive


def test_graph_node_note_has_no_dimming_spotlight():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 100x60
@ note n1 300,0 "node"
@ arrow box1 -> n1 "" ~kind=graph
""")
    view._note_items["n1"].setSelected(True)
    view._update_note_selection_highlight()
    # A pure graph-node note annotates nothing → no spotlight engaged.
    assert not view._note_highlight_active


def test_annotation_note_still_dims():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 100x60
@ note n1 300,0 "annotation"
@ arrow box1 -> n1 ""
""")
    view._note_items["n1"].setSelected(True)
    view._update_note_selection_highlight()
    assert view._note_highlight_active                # derived annotation → spotlight


def test_style_badge_works_on_note_connector():
    # A note↔note connector must resolve a midpoint so the STYLE badge shows.
    view = _view("""\
#!grafli v2
@ note n1 0,0 "A"
@ note n2 300,0 "B"
@ arrow n1 -> n2 ""
""")
    arrow = view.board.arrows[0]
    view._select_arrow(arrow)
    assert view._arrow_label_midpoint() is not None
    view._set_arrow_mode("style")
    assert view._mode_badge is not None


def test_mixed_note_is_a_node_no_spotlight():
    # A note with an annotation link AND a graph edge is a node → no spotlight.
    view = _view("""\
#!grafli v2
@ box box1 "X" 0,0 100x60
@ note mid 300,0 "mixed"
@ note y 600,0 "Y"
@ arrow box1 -> mid ""
@ arrow mid -> y "" ~kind=graph
""")
    view._note_items["mid"].setSelected(True)
    view._update_note_selection_highlight()
    assert not view._note_highlight_active


def test_auto_flow_from_note_start_via_selection():
    view = _view("""\
#!grafli v2
@ note n1 0,0 "First"
@ note n2 300,0 "Second"
@ note n3 600,0 "Third"
@ arrow n1 -> n2 "" ~kind=graph
@ arrow n2 -> n3 "" ~kind=graph
""")
    view._note_items["n1"].setSelected(True)
    flow = view.new_auto_flow_from_selection()
    assert flow is not None
    assert flow.auto_start == "n1"
    assert len(flow.steps) == 3
    view.regenerate_auto_flow(flow)
    assert len(flow.steps) == 3


def test_back_compat_note_arrow_derives_annotation():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 100x60
@ note n1 300,0 "n"
@ arrow box1 -> n1 "old file"
""")
    arrow = view.board.arrows[0]
    assert arrow.kind == ""
    assert view._is_annotation_link(arrow)
    assert "~kind" not in serialize(view.board)
