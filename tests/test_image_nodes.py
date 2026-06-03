"""Images as first-class graph nodes: connector kind, auto-flow, spotlight."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _item(view, iid):
    return (view._box_items.get(iid) or view._note_items.get(iid)
            or view._image_items.get(iid))


def _evt(view, etype, scene_pt, button, buttons, mods):
    pos = QPointF(view.mapFromScene(scene_pt))
    g = view.viewport().mapToGlobal(pos.toPoint())
    return QMouseEvent(etype, pos, g, button, buttons, mods)


def _alt_drag(view, src_id, tgt_id):
    """Alt-drag a connector from one node to another (SELECT mode)."""
    alt = Qt.KeyboardModifier.AltModifier
    s = _item(view, src_id).sceneBoundingRect().center()
    t = _item(view, tgt_id).sceneBoundingRect().center()
    view.mousePressEvent(_evt(view, QEvent.Type.MouseButtonPress, s,
                              Qt.MouseButton.LeftButton,
                              Qt.MouseButton.LeftButton, alt))
    for f in (0.3, 0.6, 1.0):
        p = QPointF(s.x() + (t.x() - s.x()) * f, s.y() + (t.y() - s.y()) * f)
        view.mouseMoveEvent(_evt(view, QEvent.Type.MouseMove, p,
                                 Qt.MouseButton.NoButton,
                                 Qt.MouseButton.LeftButton, alt))
    view.mouseReleaseEvent(_evt(view, QEvent.Type.MouseButtonRelease, t,
                                Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton, alt))

_SRC = """\
#!grafli v2
@ box box1 "Start" 0,0 100x60
@ image img1 "shots/first.png" 300,0 120x80
@ image img2 "shots/second.png" 600,0 120x80
@ image ann "shots/aside.png" 0,200 120x80
@ arrow box1 -> img1 "" ~kind=graph
@ arrow img1 -> img2 "" ~kind=graph
@ arrow box1 -> ann ""
"""


def _view(src: str = _SRC) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    return view


def test_image_arrow_derives_annotation_explicit_overrides():
    view = _view()
    graph_edge, _, annotation = view.board.arrows
    assert view._is_graph_edge(graph_edge)            # explicit ~kind=graph
    assert view._is_annotation_link(annotation)       # derived: image endpoint
    assert "~kind" not in serialize(view.board).split("box1 -> ann")[1][:20]


def test_auto_flow_traverses_image_graph_edges():
    view = _view()
    path, reason = view._auto_flow_path("box1")
    assert path == ["box1", "img1", "img2"]           # follows graph edges
    assert reason == "end"


def test_sticky_kind_applies_to_image_connector():
    view = _view()
    view._last_connector_kind = "graph"
    assert view._make_connector("img1", "img2").kind == "graph"   # image involved
    assert view._make_connector("box1", "box1").kind == ""        # box↔box derives


def test_auto_flow_from_image_start_names_flow_after_file():
    view = _view()
    view._image_items["img1"].setSelected(True)
    flow = view.new_auto_flow_from_selection()
    assert flow is not None
    assert flow.auto_start == "img1"
    assert flow.label == "first"                      # filename stem
    assert len(flow.steps) == 2                        # img1 -> img2


def test_graph_node_image_has_no_dimming_spotlight():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 100x60
@ image img1 "shots/node.png" 300,0 120x80
@ arrow box1 -> img1 "" ~kind=graph
""")
    view._image_items["img1"].setSelected(True)
    view._update_note_selection_highlight()
    assert not view._note_highlight_active            # real node → no spotlight


def test_annotation_image_dims_like_a_note():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 100x60
@ image img1 "shots/aside.png" 300,0 120x80
@ arrow box1 -> img1 ""
""")
    view._image_items["img1"].setSelected(True)
    view._update_note_selection_highlight()
    assert view._note_highlight_active                # derived annotation → spotlight


def test_alt_drag_connects_box_to_image():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 120x60
@ image img1 "shots/x.png" 400,0 160x100
""")
    assert len(view.board.arrows) == 0
    _alt_drag(view, "box1", "img1")
    assert len(view.board.arrows) == 1
    arrow = view.board.arrows[0]
    assert {arrow.from_id, arrow.to_id} == {"box1", "img1"}
    assert view._is_annotation_link(arrow)            # image endpoint → annotation


def test_alt_drag_image_to_image_uses_sticky_kind():
    view = _view("""\
#!grafli v2
@ image i1 "shots/a.png" 0,0 160x100
@ image i2 "shots/b.png" 400,0 160x100
""")
    view._last_connector_kind = "graph"
    _alt_drag(view, "i1", "i2")
    assert len(view.board.arrows) == 1
    assert view.board.arrows[0].kind == "graph"       # sticky applied to image


def test_back_compat_image_arrow_serializes_without_kind():
    view = _view("""\
#!grafli v2
@ box box1 "A" 0,0 100x60
@ image img1 "shots/x.png" 300,0 120x80
@ arrow box1 -> img1 ""
""")
    arrow = view.board.arrows[0]
    assert arrow.kind == ""
    assert view._is_annotation_link(arrow)
    assert "~kind" not in serialize(view.board)
