"""View-level tests for the LoD tiers: leaf shells, container collapse, toggle."""

from __future__ import annotations

import os

from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# group (container) > child; loose is a parent-less leaf, linked to child.
SAMPLE = """\
@ box group "Group" 0,0 400x400 !flat
@ box child "Child" 40,80 200x80 >group
@ box loose "Loose" 700,0 200x80
@ arrow child -> loose "x"
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(board):
    app = _app()
    from grafli.view import GrafliView
    v = GrafliView()
    v.resize(800, 600)
    v.show()
    v.load_board(board)
    app.processEvents()
    return v


def _set_zoom(view, z):
    view.setTransform(QTransform().scale(z, z))
    view._refresh_lod()


def test_full_detail_at_full_zoom():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 1.0)
    assert view._lod_collapsed == set()
    assert view._lod_simplified == set()
    for item in view._box_items.values():
        assert item.isVisible() and item._label.isVisible()
        assert item._lod_tile is None and not item._lod_simplified


def test_container_collapses_to_a_tile_and_hides_children():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.3)                       # children sub-threshold
    assert view._lod_collapsed == {"group"}
    g = view._box_items["group"]
    assert g._lod_tile == ("Group", 1)         # headline + descendant count
    assert not g._label.isVisible()            # tile draws its own headline
    # The child is subsumed into the tile.
    assert not view._box_items["child"].isVisible()
    # The parent-less leaf simplifies to a bare shell, not a tile.
    assert view._lod_simplified == {"loose"}
    assert view._box_items["loose"]._lod_simplified


def test_arrow_reroutes_from_hidden_child_to_the_tile():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.3)
    # child is hidden inside group's tile, so its edge re-routes to group.
    assert view._lod_reroute("child") == "group"
    assert view._lod_reroute("loose") == "loose"   # visible leaf unchanged


def test_zoom_back_in_restores_full_detail():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.3)
    assert view._lod_collapsed
    _set_zoom(view, 1.0)
    assert view._lod_collapsed == set()
    assert view._lod_simplified == set()
    for item in view._box_items.values():
        assert item.isVisible() and item._label.isVisible()
        assert item._lod_tile is None


def test_toggle_off_keeps_full_detail_even_zoomed_out():
    view = _view(parse(SAMPLE))
    view._lod_enabled = False
    _set_zoom(view, 0.3)
    assert view._lod_collapsed == set()
    assert view._lod_simplified == set()
    for item in view._box_items.values():
        assert item.isVisible() and item._label.isVisible()
        assert item._lod_tile is None


MESH = """\
@ box a "A" 0,0 160x70
@ box b "B" 250,0 160x70
@ box c "C" 500,0 160x70
@ arrow a -- b
@ arrow b -- c
"""


def test_compact_cluster_collapses_to_a_concave_hull():
    view = _view(parse(MESH))
    _set_zoom(view, 0.05)
    assert sorted(view._lod_hull_member) == ["a", "b", "c"]
    assert len(view._lod_hulls) == 1
    for m in ("a", "b", "c"):
        assert not view._box_items[m].isVisible()   # members hidden behind hull
    assert view._lod_simplified == set()            # not shelled individually


def test_cluster_clears_when_zoomed_in():
    view = _view(parse(MESH))
    _set_zoom(view, 0.05)
    assert view._lod_hulls
    _set_zoom(view, 1.0)
    assert view._lod_hulls == {}
    assert view._lod_hull_member == {}
    for m in ("a", "b", "c"):
        assert view._box_items[m].isVisible()


def test_non_compact_cluster_falls_back_to_shells():
    # An unrelated box sitting in the gap between members (inside the cluster's
    # bounding box, overlapping nothing) blocks the hull.
    board = parse(MESH + '@ box intruder "X" 185,15 40x40\n')
    view = _view(board)
    _set_zoom(view, 0.05)
    assert view._lod_hulls == {}
    assert {"a", "b", "c"} <= view._lod_simplified   # bare shells instead


def test_collapsed_tile_renders_above_arrows():
    # An arrow crossing a collapsed tile must pass behind it so the tile's
    # headline stays readable.
    from grafli.items import LabelItem
    board = parse(
        "@ box grp \"G\" 0,0 400x300 !flat\n"
        "@ box ch \"C\" 40,80 200x80 >grp\n"
        "@ box other \"O\" 700,0 160x70\n"
        "@ arrow other -> ch \"x\"\n"
    )
    view = _view(board)
    _set_zoom(view, 0.2)
    assert "grp" in view._lod_collapsed
    tile_z = view._box_items["grp"].zValue()
    arrow_z = [it.zValue() for it in view._arrow_items
               if not isinstance(it, LabelItem)]
    assert arrow_z and tile_z > max(arrow_z)


def test_no_connector_label_when_an_endpoint_is_collapsed():
    from grafli.items import LabelItem
    board = parse(
        "@ box grp \"G\" 0,0 400x300 !flat\n"
        "@ box ch \"C\" 40,80 200x80 >grp\n"
        "@ box other \"O\" 700,0 160x70\n"
        "@ arrow other -> ch \"important\"\n"
    )
    view = _view(board)
    _set_zoom(view, 1.0)
    assert any(isinstance(it, LabelItem) for it in view._arrow_items)
    _set_zoom(view, 0.2)                      # ch collapses into grp's tile
    assert "grp" in view._lod_collapsed
    assert not any(isinstance(it, LabelItem) for it in view._arrow_items)


def test_collapsed_tile_is_read_only_and_immovable():
    from PySide6.QtWidgets import QGraphicsItem
    MOVABLE = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    board = parse(
        "@ box grp \"G\" 0,0 400x300 !flat\n"
        "@ box ch \"C\" 40,80 200x80 >grp\n"
    )
    view = _view(board)
    _set_zoom(view, 0.2)
    grp = view._box_items["grp"]
    assert grp._lod_tile is not None
    assert not (grp.flags() & MOVABLE)          # can't drag a tile (no desync)
    grp.setSelected(True)
    assert view._selection_has_locked()         # mutations are refused
    _set_zoom(view, 1.0)                         # full detail -> editable again
    assert grp._lod_tile is None
    assert grp.flags() & MOVABLE
    assert not view._selection_has_locked()


def test_lock_lifts_when_lod_disabled():
    board = parse(
        "@ box grp \"G\" 0,0 400x300 !flat\n"
        "@ box ch \"C\" 40,80 200x80 >grp\n"
    )
    view = _view(board)
    _set_zoom(view, 0.2)
    view._box_items["grp"].setSelected(True)
    assert view._selection_has_locked()
    view._toggle_lod()                          # LoD off -> nothing aggregated
    assert not view._selection_has_locked()


def test_deep_nesting_collapses_innermost_first_with_no_stale_state():
    # GP > P > C > {L1,L2} — three container levels.
    board = parse(
        "@ box gp \"GP\" 0,0 900x700 !flat\n"
        "@ box p \"P\" 40,80 800x560 !flat >gp\n"
        "@ box c \"C\" 80,160 700x400 !flat >p\n"
        "@ box l1 \"L1\" 120,240 200x80 >c\n"
        "@ box l2 \"L2\" 400,240 200x80 >c\n"
    )
    view = _view(board)

    def state():
        tiles = {b for b, it in view._box_items.items()
                 if it._lod_tile is not None}
        hidden = {b for b, it in view._box_items.items() if not it.isVisible()}
        return tiles, hidden

    # Innermost collapses first: open ancestors nest a single tile (C).
    _set_zoom(view, 0.5)
    tiles, hidden = state()
    assert tiles == {"c"} and hidden == {"l1", "l2"}

    # Further out: the middle (P) becomes the one tile; C is subsumed/hidden and
    # must NOT keep a stale tile flag (would linger as a read-only lock).
    _set_zoom(view, 0.1)
    tiles, hidden = state()
    assert tiles == {"p"}
    assert "c" in hidden and not (tiles & hidden)

    # Fully out: a single outer tile, everything inside hidden.
    _set_zoom(view, 0.08)
    tiles, hidden = state()
    assert tiles == {"gp"} and not (tiles & hidden)


def test_toggle_helper_flips_and_reapplies():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.3)
    assert view._lod_collapsed == {"group"}
    view._toggle_lod()                          # -> off
    assert not view._lod_enabled
    assert view._lod_collapsed == set()
    assert view._box_items["child"].isVisible()
    view._toggle_lod()                          # -> on
    assert view._lod_collapsed == {"group"}
