"""Visual-vocabulary glyphs on boxes and notes (the `*name` sigil), the
icon set, and the style-mode icon picker (open/navigate/commit/cancel)."""

from __future__ import annotations

import os

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QGraphicsTextItem

from grafli import iconset
from grafli.format import parse, serialize
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    return QApplication.instance() or QApplication([])


def _view(src: str) -> GrafliView:
    _app()
    view = GrafliView()
    view.load_board(parse("#!grafli v1\n" + src))
    view.resize(900, 600)
    view._mode = Mode.SELECT
    return view


# ── format ──────────────────────────────────────────────────────

def test_box_and_note_icon_roundtrip():
    src = (
        "#!grafli v1\n"
        '@ box idea "Spawn idea" 0,0 120x120 !flat *lightbulb\n'
        '@ box risk "Risk" 200,0 80x80 %accent *warning >idea\n'
        '@ note m 0,200 *flag\n'
        '@ note cap 200,200 "needs review" *star\n'
    )
    b = parse(src)
    assert b.boxes[0].icon == "lightbulb"
    assert b.boxes[1].icon == "warning"
    assert b.notes[0].icon == "flag" and b.notes[0].text == ""
    assert b.notes[1].icon == "star" and b.notes[1].text == "needs review"
    assert serialize(b) == src   # byte-stable, incl. the slot-less marker note


def test_icon_only_note_has_no_text_slot():
    b = parse("#!grafli v1\n@ note m 10,20 *flag\n")
    assert "@ note m 10,20 *flag" in serialize(b)
    assert '""' not in serialize(b)


def test_lead_placement_roundtrip():
    src = (
        "#!grafli v1\n"
        '@ box auth "Auth" 0,0 160x60 *lead:lock\n'
        '@ note n 0,100 "review" *lead:flag\n'
    )
    b = parse(src)
    assert (b.boxes[0].icon, b.boxes[0].icon_placement) == ("lock", "lead")
    assert (b.notes[0].icon, b.notes[0].icon_placement) == ("flag", "lead")
    assert serialize(b) == src   # bare *name (fill) vs *lead:name byte-stable


# ── icon set ────────────────────────────────────────────────────

def test_iconset_names_and_render():
    _app()
    # 20 semantic + 9 emphasis (sheet) + 2 legacy painters (money, link)
    assert len(iconset.ICON_NAMES) == 31
    assert iconset.has_icon("lightbulb") and not iconset.has_icon("nope")
    assert iconset.has_icon("bulb")          # legacy alias
    assert iconset.has_icon("3") and iconset.has_icon("42")   # number badges
    assert not iconset.has_icon("0") and not iconset.has_icon("100")
    pm = iconset.icon_pixmap("bulb", QColor("#2F3437"), 64, 2.0)
    assert pm is not None and not pm.isNull()
    assert pm.devicePixelRatio() == 2.0
    assert iconset.icon_pixmap("nope", QColor("#000"), 64) is None
    # every advertised name must render to a non-empty pixmap
    for name in iconset.ICON_NAMES:
        pm = iconset.icon_pixmap(name, QColor("#2F3437"), 32)
        assert pm is not None and not pm.isNull(), name


def test_iconset_tint_and_aspect():
    _app()
    pm = iconset.icon_pixmap("gear", QColor("#C93D3D"), 32)
    assert pm is not None and not pm.isNull()
    assert 0.2 < iconset.icon_aspect("flame") < 1.0    # tall symbol
    assert iconset.icon_aspect("exercise") > 1.5       # wide symbol
    assert iconset.icon_aspect("7") == 1.0             # digits are square


def test_badge_placement_roundtrip():
    src = (
        "#!grafli v1\n"
        '@ box hot "Incident" 0,0 200x80 *badge:flame\n'
        '@ note n 0,100 "review order" *badge:2\n'
    )
    b = parse(src)
    assert (b.boxes[0].icon, b.boxes[0].icon_placement) == ("flame", "badge")
    assert (b.notes[0].icon, b.notes[0].icon_placement) == ("2", "badge")
    assert serialize(b) == src


def test_badge_note_keeps_text_body():
    # A badge note is a normal text note with a corner overlay — not a
    # floating marker; its bounding rect must track the text, not the glyph.
    view = _view('@ note n 0,0 "a rather long line of prose" *badge:star\n')
    n = view._note_items["n"]
    assert not n._is_marker_icon() and n._has_badge_icon()
    marker = _view('@ note m 0,0 "hi" *star\n')._note_items["m"]
    assert marker._is_marker_icon()


def test_unknown_icon_diagnostic():
    from grafli.diagnostics import check_unknown_icon
    b = parse('#!grafli v1\n@ box a "A" 0,0 100x100 *gaer\n'
              '@ note n 0,200 "x" *star\n')
    diags = check_unknown_icon(b)
    assert [d.item_ids for d in diags] == [["a"]]
    assert diags[0].code == "unknown-icon"


def test_alias_and_digit_normalization_roundtrip():
    src = (
        "#!grafli v1\n"
        '@ box idea "Idea" 0,0 120x120 *bulb\n'
        '@ box spec "Spec" 200,0 120x120 *lead:doc\n'
        '@ note step 0,200 "first" *03\n'
    )
    b = parse(src)
    assert b.boxes[0].icon == "lightbulb"
    assert (b.boxes[1].icon, b.boxes[1].icon_placement) == ("document", "lead")
    assert b.notes[0].icon == "3"
    out = serialize(b)
    assert "*lightbulb" in out and "*lead:document" in out and "*3" in out


# ── picker ──────────────────────────────────────────────────────

def test_picker_open_navigate_live_preview():
    view = _view('@ box a "A" 0,0 100x100\n')
    a = view._box_items["a"]
    a.setSelected(True)
    view._open_icon_picker()
    assert view._icon_picker_active and view._icon_picker_index == 0  # "none"
    view._icon_picker_move(1, 0)                 # -> first real icon
    assert view._icon_picker_index == 1
    assert a.box.icon == iconset.ICON_NAMES[0]   # applied live


def test_picker_commit_is_undoable():
    view = _view('@ box a "A" 0,0 100x100\n')
    view._box_items["a"].setSelected(True)
    undo_before = len(view._undo_stack)
    view._open_icon_picker()
    view._icon_picker_move(1, 0)
    chosen = iconset.ICON_NAMES[0]
    view._commit_icon_picker()
    assert not view._icon_picker_active
    assert view.board.box_by_id("a").icon == chosen
    assert len(view._undo_stack) == undo_before + 1
    view._undo()
    assert view.board.box_by_id("a").icon == ""


def test_picker_cancel_reverts():
    view = _view('@ box a "A" 0,0 100x100 *gear\n')
    a = view._box_items["a"]
    a.setSelected(True)
    view._open_icon_picker()
    view._icon_picker_move(1, 0)
    assert a.box.icon != "gear"
    view._cancel_icon_picker()
    assert view._box_items["a"].box.icon == "gear"


def test_picker_applies_to_note_too():
    view = _view('@ note n 0,0 "hi"\n')
    n = view._note_items["n"]
    n.setSelected(True)
    view._open_icon_picker()
    view._icon_picker_move(1, 0)
    chosen = iconset.ICON_NAMES[0]
    view._commit_icon_picker()
    assert view.board.notes[0].icon == chosen


def test_lead_box_label_reserves_icon_gutter():
    # A lead glyph must not push the label past the box edge.
    view = _view('@ box t "Really long heading that would overflow a lead box"'
                 ' 0,0 320x120 *lead:star\n')
    it = view._box_items["t"]
    # Wrap width leaves room for the icon gutter (vs the plain 16px inset).
    assert it._label_width_for(it.box.w) < it.box.w - it._lead_icon_side()
    # And the rendered label stays within the box bounds.
    assert it._label.sceneBoundingRect().right() <= it.sceneBoundingRect().right() + 1.0


def test_picker_tab_toggles_placement_and_commits():
    view = _view('@ box a "A" 0,0 140x70\n')
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    view._icon_picker_move(1, 0)                 # pick first icon
    assert view._icon_picker_placement == ""     # fill by default
    view._toggle_icon_placement()                # Tab -> lead
    assert view._icon_picker_placement == "lead"
    assert view._box_items["a"].box.icon_placement == "lead"   # live preview
    view._commit_icon_picker()
    assert view.board.box_by_id("a").icon_placement == "lead"


def test_picker_cancel_restores_placement():
    view = _view('@ box a "A" 0,0 140x70 *lead:gear\n')
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    assert view._icon_picker_placement == "lead"
    view._toggle_icon_placement()                # flip to fill
    view._cancel_icon_picker()
    assert view._box_items["a"].box.icon == "gear"
    assert view._box_items["a"].box.icon_placement == "lead"


def _commit_empty(view, item):
    """Drive _commit_editor with an empty edit on ``item``."""
    ed = QGraphicsTextItem("")
    view._scene.addItem(ed)
    view._editor = ed
    view._edit_target = item
    view._commit_editor()


def test_glyph_box_label_can_be_cleared():
    # A glyph box should be clearable to no caption so the icon fills it.
    view = _view('@ box p "Postgres" 0,0 160x160 *bulb\n')
    _commit_empty(view, view._box_items["p"])
    assert view.board.box_by_id("p").label == ""


def test_plain_box_empty_commit_is_ignored():
    # Without an icon, an empty commit must NOT wipe the label (the guard).
    view = _view('@ box k "Keep" 0,0 120x60\n')
    _commit_empty(view, view._box_items["k"])
    assert view.board.box_by_id("k").label == "Keep"


def test_picker_placement_cycle_includes_badge():
    view = _view('@ box a "A" 0,0 140x70\n')
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    view._icon_picker_move(1, 0)
    view._toggle_icon_placement()                # fill -> lead
    view._toggle_icon_placement()                # lead -> badge
    assert view._icon_picker_placement == "badge"
    assert view._box_items["a"].box.icon_placement == "badge"
    view._toggle_icon_placement()                # badge -> fill
    assert view._icon_picker_placement == ""
    view._cancel_icon_picker()


def test_picker_digit_entry_sets_number_badge():
    view = _view('@ box a "A" 0,0 140x70\n')
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    view._icon_picker_digit = "4"
    view._apply_icon_picker_live()
    assert view._box_items["a"].box.icon == "4"
    view._commit_icon_picker()
    assert view.board.box_by_id("a").icon == "4"
    # moving in the grid clears the typed digit again
    view._open_icon_picker()
    assert view._icon_picker_digit == "4"
    view._icon_picker_move(1, 0)
    assert view._icon_picker_digit == ""
    view._cancel_icon_picker()


def test_picker_none_cell_clears_icon():
    view = _view('@ box a "A" 0,0 100x100 *star\n')
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    # opens on the current icon; move back to index 0 ("none") and commit
    view._icon_picker_index = 0
    view._apply_icon_picker_live()
    view._commit_icon_picker()
    assert view.board.box_by_id("a").icon == ""
