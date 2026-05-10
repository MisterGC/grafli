"""Tests for grafli.minimap helpers (Qt-free portion)."""

from grafli.format import Box
from grafli.minimap import _box_depth_order


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
