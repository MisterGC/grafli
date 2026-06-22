"""Tests for grafli.minimap helpers (Qt-free portion) and the selection
glow ring (Qt, offscreen)."""

import os

from grafli.format import Box
from grafli.minimap import _box_depth_order

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _b(bid: str, parent: str = "") -> Box:
    return Box(id=bid, label=bid, x=0, y=0, w=10, h=10, parent=parent)


def test_top_level_only_keeps_input_order_stable():
    a, b, c = _b("a"), _b("b"), _b("c")
    assert _box_depth_order([a, b, c]) == [a, b, c]


def test_parent_drawn_before_children_regardless_of_input_order():
    """Parent declared AFTER children in the file (typical grafli) must
    still be drawn first so the minimap doesn't paint over them."""
    child1 = _b("c1", parent="p")
    child2 = _b("c2", parent="p")
    parent = _b("p")
    ordered = _box_depth_order([child1, child2, parent])
    assert ordered[0].id == "p"
    assert {b.id for b in ordered[1:]} == {"c1", "c2"}


def test_nested_parents_ordered_by_depth():
    grandparent = _b("g")
    parent = _b("p", parent="g")
    leaf = _b("l", parent="p")
    ordered = _box_depth_order([leaf, parent, grandparent])
    assert [b.id for b in ordered] == ["g", "p", "l"]


def test_cyclic_parent_refs_do_not_loop_forever():
    a = _b("a", parent="b")
    b = _b("b", parent="a")
    # Should return some order, not hang.
    ordered = _box_depth_order([a, b])
    assert {x.id for x in ordered} == {"a", "b"}


def test_dangling_parent_ref_treated_as_top_level():
    """A box pointing at a non-existent parent should be at depth 0."""
    a = _b("a", parent="ghost")
    b = _b("b")
    ordered = _box_depth_order([a, b])
    # Both depth 0 — order preserved.
    assert ordered == [a, b]


# ── Selection glow ring on the minimap (Qt, offscreen) ──────────────

def _view(src: str):
    from PySide6.QtWidgets import QApplication
    from grafli.format import parse
    from grafli.view import GrafliView
    QApplication.instance() or QApplication([])
    v = GrafliView()
    v.load_board(parse("#!grafli v1\n" + src))
    v.resize(800, 600)
    return v


def test_minimap_selected_ids_spans_boxes_and_notes():
    v = _view('@ box a "A" 0,0 200x100\n@ box b "B" 400,0 200x100\n'
              '@ note n 0,300 "T: task"\n')
    assert v._minimap_selected_ids() == set()
    v._box_items["a"].setSelected(True)
    v._note_items["n"].setSelected(True)
    assert v._minimap_selected_ids() == {"a", "n"}


def _minimap_amber(view) -> int:
    """Render only the minimap HUD (not the canvas) and count selection-glow
    (amber) pixels — isolated so on-canvas selection chrome can't confound it."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(view.viewport().width(), view.viewport().height(),
                 QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    view._draw_minimap(p)
    p.end()
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            if (c.red() > 200 and 150 < c.green() < 230
                    and c.blue() < 140 and c.red() - c.blue() > 90):
                n += 1
    return n


def test_selection_ring_renders_only_when_selected():
    v = _view('@ box a "A" 0,0 200x100\n@ box b "B" 400,0 200x100\n')
    assert _minimap_amber(v) == 0              # nothing selected -> no ring
    v._box_items["a"].setSelected(True)
    assert _minimap_amber(v) > 0               # selection -> glow ring drawn


def test_selection_ring_gone_when_minimap_hidden():
    v = _view('@ box a "A" 0,0 200x100\n')
    v._box_items["a"].setSelected(True)
    assert _minimap_amber(v) > 0
    v._toggle_minimap()                        # hide the whole minimap
    assert _minimap_amber(v) == 0
