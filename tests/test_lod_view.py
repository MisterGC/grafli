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


def test_notes_and_images_follow_lod():
    board = parse(
        "@ box grp \"G\" 0,0 500x400 !flat\n"
        "@ box ch \"C\" 40,80 200x80 >grp\n"
        "@ note inside 60,250 \"in the group\" >grp\n"
        "@ note solo 900,0 \"standalone note\"\n"
        "@ image imgin \"x.png\" 60,320 100x60 >grp\n"
        "@ image imgsolo \"y.png\" 900,200 200x120\n"
    )
    view = _view(board)
    _set_zoom(view, 0.2)
    assert "grp" in view._lod_collapsed
    # subsumed into the collapsed container:
    assert not view._note_items["inside"].isVisible()
    assert not view._image_items["imgin"].isVisible()
    # standalone note stays visible but simplifies to a 'text here' marker once
    # illegible (never silently vanishes); standalone image stays a thumbnail:
    assert view._note_items["solo"].isVisible()
    assert view._note_items["solo"]._lod_text_marker
    assert view._image_items["imgsolo"].isVisible()
    # back to detail -> everything visible and no markers:
    _set_zoom(view, 1.0)
    assert all(n.isVisible() for n in view._note_items.values())
    assert not any(n._lod_text_marker for n in view._note_items.values())
    assert all(i.isVisible() for i in view._image_items.values())


def test_same_depth_containers_collapse_together():
    # Two top-level (depth-1) containers with different child sizes. Per-child
    # they'd collapse at different zooms; depth-leveling holds the small one
    # until the larger is ready, so siblings fold together.
    board = parse(
        "@ box small \"Small\" 0,0 260x220 !flat\n"
        "@ box s1 \"S1\" 30,80 100x60 >small\n"
        "@ box s2 \"S2\" 30,150 100x60 >small\n"
        "@ box big \"Big\" 500,0 520x420 !flat\n"
        "@ box b1 \"B1\" 540,90 200x120 >big\n"
        "@ box b2 \"B2\" 540,250 200x120 >big\n"
    )
    view = _view(board)
    # Just above the (shared) collapse point: NEITHER collapses — the small one
    # is held back in step with the big one rather than folding on its own.
    _set_zoom(view, 0.5)
    assert "small" not in view._lod_collapsed
    assert "big" not in view._lod_collapsed
    # Past it: both fold together.
    _set_zoom(view, 0.3)
    assert "small" in view._lod_collapsed
    assert "big" in view._lod_collapsed


def test_arrow_label_hides_when_too_small():
    from grafli.items import LabelItem
    board = parse(
        "@ box a \"A\" 0,0 220x90\n"
        "@ box b \"B\" 520,0 220x90\n"
        "@ arrow a -> b \"sync call\"\n"
    )
    view = _view(board)

    def labels():
        return [it for it in view._arrow_items if isinstance(it, LabelItem)]

    # Full detail: the caption is shown.
    _set_zoom(view, 1.0)
    assert labels() and all(it.isVisible() for it in labels())
    # Zoomed out below the legibility floor: the caption hides (the line is
    # redrawn unbroken, so the label is kept but invisible).
    _set_zoom(view, 0.4)
    assert labels() and not any(it.isVisible() for it in labels())
    assert ("a", "b") in view._lod_arrow_labels_hidden
    # Back to detail: shown again.
    _set_zoom(view, 1.0)
    assert all(it.isVisible() for it in labels())


def test_leaf_shell_paints_skeleton_bars():
    # A shelled leaf keeps its fill and reports as simplified; its paint path
    # (bars) must run without error at a tiny on-screen size.
    from PySide6.QtGui import QPixmap, QPainter
    board = parse("@ box a \"A label\" 0,0 220x90\n")
    view = _view(board)
    _set_zoom(view, 0.1)
    item = view._box_items["a"]
    assert item._lod_simplified and item._lod_tile is None
    pm = QPixmap(64, 64)
    p = QPainter(pm)
    item.paint(p, None)          # exercises _paint_lod_shell_bars
    p.end()


def test_loose_cluster_hull_syncs_to_depth1_collapse():
    # A compact 3-node loose mesh next to a flat depth-1 container with large
    # children. The mesh is illegible (shells) before the container collapses,
    # but the hull must wait for the depth-1 trigger, then form with it.
    board = parse(
        "@ box host \"Host\" 0,0 560x320 !flat\n"
        "@ box h1 \"H1\" 40,90 240x150 >host\n"
        "@ box m1 \"M1\" 900,0 120x40\n"
        "@ box m2 \"M2\" 1080,0 120x40\n"
        "@ box m3 \"M3\" 990,180 120x40\n"
        "@ arrow m1 -- m2\n"
        "@ arrow m2 -- m3\n"
        "@ arrow m3 -- m1\n"
    )
    view = _view(board)
    # Mesh text is illegible here, but the depth-1 container hasn't collapsed
    # yet -> no hull (the loose group peels with depth-1, not on its own).
    _set_zoom(view, 0.45)
    assert "host" not in view._lod_collapsed
    assert not view._lod_hulls
    assert view._box_items["m1"]._lod_simplified   # shown as a bar shell instead
    # Zoom past the depth-1 trigger: container tiles AND the mesh hulls together.
    _set_zoom(view, 0.25)
    assert "host" in view._lod_collapsed
    assert len(view._lod_hulls) == 1


def test_long_tile_headline_wraps_without_error():
    from PySide6.QtGui import QPixmap, QPainter
    board = parse(
        "@ box grp \"A Very Long Collapsed Container Headline (modified)\" "
        "0,0 360x300 !flat\n"
        "@ box c1 \"child one\" 30,80 200x80 >grp\n"
        "@ box c2 \"child two\" 30,180 200x80 >grp\n"
    )
    view = _view(board)
    _set_zoom(view, 0.2)
    item = view._box_items["grp"]
    assert item._lod_tile is not None
    pm = QPixmap(200, 200)
    p = QPainter(pm)
    item.paint(p, None)          # exercises the wrapping headline path
    p.end()


def test_notes_only_container_collapses_to_tile():
    # A legend-style container holding only notes must aggregate into a tile
    # like any box container — not just have its notes vanish.
    board = parse(
        "@ box legend \"Legend\" 0,0 360x300 !flat\n"
        "@ note l1 30,60 \"blue = service\" >legend\n"
        "@ note l2 30,120 \"red = task\" >legend\n"
        "@ note l3 30,180 \"purple = question\" >legend\n"
    )
    view = _view(board)
    _set_zoom(view, 0.1)
    assert "legend" in view._lod_collapsed
    assert view._box_items["legend"]._lod_tile is not None
    # its notes are subsumed by the tile, not left floating:
    assert not view._note_items["l1"].isVisible()
    assert not view._note_items["l3"].isVisible()
    _set_zoom(view, 1.0)
    assert "legend" not in view._lod_collapsed
    assert all(view._note_items[n].isVisible() for n in ("l1", "l2", "l3"))


def test_hull_color_is_neutral_when_members_disagree():
    uniform = parse(
        "@ box a \"A\" 0,0 160x70 #2C7A7B\n"
        "@ box b \"B\" 250,0 160x70 #2C7A7B\n"
        "@ box c \"C\" 500,0 160x70 #2C7A7B\n"
        "@ arrow a -- b\n@ arrow b -- c\n"
    )
    v = _view(uniform)
    assert v._cluster_color(["a", "b", "c"]) != v.LOD_NEUTRAL   # shared colour

    mixed = parse(
        "@ box a \"A\" 0,0 160x70 #2C7A7B\n"
        "@ box b \"B\" 250,0 160x70 #B83280\n"
        "@ box c \"C\" 500,0 160x70 #2C7A7B\n"
        "@ arrow a -- b\n@ arrow b -- c\n"
    )
    v2 = _view(mixed)
    assert v2._cluster_color(["a", "b", "c"]) == v2.LOD_NEUTRAL  # mixed -> neutral


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
