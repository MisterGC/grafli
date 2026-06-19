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
        '@ box idea "Spawn idea" 0,0 120x120 !flat *bulb\n'
        '@ box risk "Risk" 200,0 80x80 %accent *warning >idea\n'
        '@ note m 0,200 *flag\n'
        '@ note cap 200,200 "needs review" *star\n'
    )
    b = parse(src)
    assert b.boxes[0].icon == "bulb"
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
    assert len(iconset.ICON_NAMES) == 16
    assert iconset.has_icon("bulb") and not iconset.has_icon("nope")
    pm = iconset.icon_pixmap("bulb", QColor("#2F3437"), 64, 2.0)
    assert pm is not None and not pm.isNull()
    assert pm.devicePixelRatio() == 2.0
    assert iconset.icon_pixmap("nope", QColor("#000"), 64) is None


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


def test_picker_none_cell_clears_icon():
    view = _view('@ box a "A" 0,0 100x100 *star\n')
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    # opens on the current icon; move back to index 0 ("none") and commit
    view._icon_picker_index = 0
    view._apply_icon_picker_live()
    view._commit_icon_picker()
    assert view.board.box_by_id("a").icon == ""
