"""The `s` `e` element-appearance overlay (#144).

One panel, one key, whatever is selected. The assertions are about *reach* —
that attributes the format has always carried are now settable from the
keyboard and survive a round-trip — rather than about pixels, so retuning a
preview cell doesn't rewrite them.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse("#!grafli v1\n" + src))
    view.resize(900, 600)
    view._mode = Mode.SELECT
    return view


def _axis(view, label: str):
    return next(a for a in view._elem_overlay_axes if a["label"] == label)


def _row_of(view, label: str) -> int:
    return next(i for i, a in enumerate(view._elem_overlay_axes)
                if a["label"] == label)


# ── Boxes: the attributes that had no key ──────────────────────────

def test_box_overlay_offers_background_and_label():
    view = _view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    view._open_element_overlay()
    assert view._elem_overlay_target == "box"
    assert [a["label"] for a in view._elem_overlay_axes] == ["Background", "Label"]


def test_box_background_reaches_flat():
    """`!flat` has always parsed; until now nothing could set it on a box."""
    view = _view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    view._open_element_overlay()
    view._elem_overlay_row = _row_of(view, "Background")
    view._elem_overlay_cycle(1)                 # Plate -> Flat
    view._commit_element_overlay()
    assert view.board.box_by_id("a").style == "flat"
    assert "!flat" in serialize(view.board)


def test_box_label_reaches_the_anchor():
    """`BoxItem.set_anchor` existed but was never called by anything."""
    view = _view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    view._open_element_overlay()
    view._elem_overlay_row = _row_of(view, "Label")
    view._elem_overlay_cycle(1)                 # Center -> Top left
    view._commit_element_overlay()
    assert view.board.box_by_id("a").anchor == "topleft"
    assert "^topleft" in serialize(view.board)


def test_the_layer_recipe_round_trips():
    """The use case that motivated #144: a layer band with no children.

    `!flat` gives the borderless, sharp-cornered, translucent body a container
    gets for free; `^topleft` puts the caption where a container's sits. Both
    together are the look, and both have to survive serialization.
    """
    view = _view('@ box l "Domain layer" 0,0 700x110\n')
    view._box_items["l"].setSelected(True)
    view._open_element_overlay()
    view._elem_overlay_row = _row_of(view, "Background")
    view._elem_overlay_cycle(1)
    view._elem_overlay_row = _row_of(view, "Label")
    view._elem_overlay_cycle(1)
    view._commit_element_overlay()
    line = next(ln for ln in serialize(view.board).splitlines()
                if ln.startswith("@ box l "))
    assert "^topleft" in line and "!flat" in line
    assert parse(serialize(view.board)).box_by_id("l").style == "flat"


def test_box_overlay_commit_is_undoable():
    view = _view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    before = len(view._undo_stack)
    view._open_element_overlay()
    view._elem_overlay_cycle(1)
    view._commit_element_overlay()
    assert len(view._undo_stack) == before + 1
    view._undo()
    assert view.board.box_by_id("a").style == ""


def test_box_overlay_cancel_reverts_the_preview():
    view = _view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    view._open_element_overlay()
    view._elem_overlay_cycle(1)                 # live preview -> Flat
    assert view._box_items["a"].box.style == "flat"
    view._cancel_element_overlay()
    assert view._box_items["a"].box.style == ""


def test_box_overlay_applies_to_the_whole_selection():
    view = _view('@ box a "A" 0,0 160x60\n@ box b "B" 200,0 160x60\n')
    view._box_items["a"].setSelected(True)
    view._box_items["b"].setSelected(True)
    view._open_element_overlay()
    view._elem_overlay_cycle(1)
    view._commit_element_overlay()
    assert view.board.box_by_id("a").style == "flat"
    assert view.board.box_by_id("b").style == "flat"


# ── Where the panel sits ───────────────────────────────────────────

def test_the_panel_anchors_on_what_it_edits():
    """The panel anchored on the connector items alone, so a box selection hit
    an empty list and fell through to a whole-viewport fallback — which parked
    it against the left edge of the window instead of beside the box. Every
    behavioural test still passed, because nothing about the values was wrong.
    """
    view = _view('@ box a "A" 300,200 160x60\n')
    view._box_items["a"].setSelected(True)
    view._open_element_overlay()
    assert view._elem_overlay_anchor_rect() == \
        view._box_items["a"].sceneBoundingRect()


def test_the_panel_anchors_on_a_note_too():
    view = _view('@ note n 300,200 "aside"\n')
    view._note_items["n"].setSelected(True)
    view._open_element_overlay()
    assert view._elem_overlay_anchor_rect() == \
        view._note_items["n"].sceneBoundingRect()


def test_the_panel_anchors_on_a_connector():
    view = _view('@ box a "A" 0,0 160x60\n@ box b "B" 400,0 160x60\n'
                 '@ arrow a -> b "x"\n')
    view._select_arrow(view.board.arrows[0])
    view._open_element_overlay("appearance")
    rect = view._elem_overlay_anchor_rect()
    assert rect is not None
    # Between the two boxes, not the viewport — the connector's own run.
    assert 100 < rect.center().x() < 460


# ── The icon conflict ──────────────────────────────────────────────

def test_label_axis_is_dead_when_an_icon_owns_the_caption():
    """`_position_label` returns early for fill and lead placements.

    The anchor is genuinely ignored for those boxes, so the row has to say so
    rather than accept a keystroke and do nothing.
    """
    view = _view('@ box a "A" 0,0 160x60 *person\n')
    view._box_items["a"].setSelected(True)
    view._open_element_overlay()
    axis = _axis(view, "Label")
    assert axis.get("enabled") is False
    view._elem_overlay_row = _row_of(view, "Label")
    view._elem_overlay_cycle(1)
    assert view._box_items["a"].box.anchor == ""      # keystroke refused


def test_label_axis_stays_live_for_a_badge_icon():
    # A badge overlays a corner and leaves the caption's layout alone.
    view = _view('@ box a "A" 0,0 160x60 *badge:person\n')
    assert view.board.box_by_id("a").icon_placement == "badge"   # not vacuous
    view._box_items["a"].setSelected(True)
    view._open_element_overlay()
    assert _axis(view, "Label")["enabled"] is True


# ── Connectors keep working, under the new key ─────────────────────

def test_connector_overlay_moved_to_e_unchanged():
    view = _view('@ box a "A" 0,0 160x60\n@ box b "B" 400,0 160x60\n'
                 '@ arrow a -> b "x"\n')
    view._select_arrow(view.board.arrows[0])
    view._open_element_overlay("appearance")
    assert view._elem_overlay_target == "arrow"
    assert [a["label"] for a in view._elem_overlay_axes] == [
        "Heads", "Line", "Thickness", "Routing", "Colour"]


def test_connector_colour_key_now_opens_the_palette():
    """The breaking half of #144: `s c` is colour for every element type."""
    view = _view('@ box a "A" 0,0 160x60\n@ box b "B" 400,0 160x60\n'
                 '@ arrow a -> b "x"\n')
    view._select_arrow(view.board.arrows[0])
    view._open_color_picker()
    assert view._color_picker_mode == "arrow"


def _press(view, key: str):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress,
                                 getattr(Qt.Key, f"Key_{key.upper()}"),
                                 Qt.KeyboardModifier.NoModifier, key))


def _arrow_view():
    view = _view('@ box a "A" 0,0 160x60\n@ box b "B" 400,0 160x60\n'
                 '@ arrow a -> b "x"\n')
    view._select_arrow(view.board.arrows[0])
    return view


def test_e_on_a_connector_edits_the_label():
    """Bare `e` keeps its old job — the overlay only claims it inside `s`."""
    view = _arrow_view()
    _press(view, "e")
    assert not view._elem_overlay_active
    assert view._editor is not None          # label editor opened


def test_s_then_e_on_a_connector_opens_the_overlay():
    """The label editor is handled before the style branch in the arrow path,
    so without an explicit stand-down it swallowed `s` `e` entirely."""
    view = _arrow_view()
    _press(view, "s")
    assert view._arrow_mode == "style"
    _press(view, "e")
    assert view._elem_overlay_active
    assert view._elem_overlay_target == "arrow"
    assert view._editor is None              # label editor stayed shut


def test_s_then_e_on_a_box_opens_the_overlay():
    view = _view('@ box a "A" 0,0 160x60\n')
    view._box_items["a"].setSelected(True)
    _press(view, "s")
    _press(view, "e")
    assert view._elem_overlay_active
    assert view._elem_overlay_target == "box"


def test_overlay_without_a_selection_says_so():
    view = _view('@ box a "A" 0,0 160x60\n')
    view._open_element_overlay()
    assert not view._elem_overlay_active


# ── Images: the frame toggle (#147) ────────────────────────────────

def test_image_overlay_offers_the_frame_axis():
    view = _view('@ image i1 "x.png" 0,0 320x240\n')
    view._image_items["i1"].setSelected(True)
    view._open_element_overlay()
    assert view._elem_overlay_target == "image"
    assert [a["label"] for a in view._elem_overlay_axes] == ["Frame"]


def test_image_frame_reaches_noframe():
    view = _view('@ image i1 "x.png" 0,0 320x240\n')
    view._image_items["i1"].setSelected(True)
    view._open_element_overlay()
    view._elem_overlay_cycle(1)                 # Auto -> Frame
    view._elem_overlay_cycle(1)                 # Frame -> None
    view._commit_element_overlay()
    assert view.board.image_by_id("i1").frame == "off"
    assert "!noframe" in serialize(view.board)
    assert parse(serialize(view.board)).image_by_id("i1").frame == "off"


def test_image_overlay_cancel_reverts_the_preview():
    view = _view('@ image i1 "x.png" 0,0 320x240 !frame\n')
    view._image_items["i1"].setSelected(True)
    view._open_element_overlay()
    view._elem_overlay_cycle(1)                 # Frame -> None
    view._cancel_element_overlay()
    assert view.board.image_by_id("i1").frame == "on"
