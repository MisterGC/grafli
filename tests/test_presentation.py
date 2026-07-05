"""Per-step presentation settings (#112 detail, #113 focus) and the wrapped
playback caption's authoring cap (#111)."""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

from grafli.flows import frame_rect, step_detail, step_focus
from grafli.format import Flow, FlowStep, parse, serialize

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SAMPLE = """\
#!grafli v2
@ box group "Group" 0,0 400x400 !flat
@ box child "Child" 40,80 200x80 >group
@ box loose "Loose" 700,0 200x80
@ note n1 700,200 "A note"
@ arrow child -> loose "x"
@ arrow loose -> n1
@ bookmark bm_in "Inside" @group
@ bookmark bm_all "All" @group,loose,n1
@ flow tour "Tour" bm_in:3:detail=full bm_all:focus=complete ~detail=summary ~focus=none "d"
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


# ── format round-trip ────────────────────────────────────────────────────


def test_flow_detail_focus_round_trip():
    board = parse(SAMPLE)
    flow = board.flow_by_id("tour")
    assert flow.detail == "summary" and flow.focus == "none"
    assert (flow.steps[0].detail, flow.steps[0].focus) == ("full", "")
    assert (flow.steps[1].detail, flow.steps[1].focus) == ("", "complete")
    out = serialize(board)
    assert ("@ flow tour \"Tour\" bm_in:3:detail=full bm_all:focus=complete"
            " ~detail=summary ~focus=none \"d\"") in out
    # And the round-trip is stable.
    assert serialize(parse(out)) == out


def test_legacy_flow_line_round_trips_untouched():
    src = "#!grafli v2\n@ bookmark b \"B\" @x\n@ flow f \"F\" b:3 b \"d\"\n"
    assert serialize(parse(src)) == src


# ── resolution: step ← flow ← global ─────────────────────────────────────


def test_step_setting_resolution():
    flow = Flow(id="f", label="", detail="summary", focus="complete")
    plain = FlowStep(ref="a")
    assert step_detail(flow, plain) == "summary"
    assert step_focus(flow, plain) == "complete"
    # A step overrides the flow — including back to the global/off state.
    assert step_detail(flow, FlowStep(ref="a", detail="auto")) == ""
    assert step_detail(flow, FlowStep(ref="a", detail="full")) == "full"
    assert step_focus(flow, FlowStep(ref="a", focus="none")) == ""
    # Nothing set anywhere -> inherit global ("").
    bare = Flow(id="g", label="")
    assert step_detail(bare, plain) == ""
    assert step_focus(bare, plain) == ""


def test_frame_rect_expands_to_aspect():
    r = frame_rect(QRectF(0, 0, 100, 100), 2.0)
    assert (r.x(), r.y(), r.width(), r.height()) == (-50, 0, 200, 100)
    r = frame_rect(QRectF(0, 0, 100, 100), 0.5)
    assert (r.x(), r.y(), r.width(), r.height()) == (0, -50, 100, 200)


# ── detail override on the view ──────────────────────────────────────────


def test_detail_summary_collapses_at_full_zoom():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 1.0)
    assert view._lod_collapsed == set()
    view._set_presentation_detail("summary")
    assert view._lod_collapsed == {"group"}
    assert not view._box_items["child"].isVisible()
    view._set_presentation_detail(None)
    assert view._lod_collapsed == set()
    assert view._box_items["child"].isVisible()


def test_detail_full_prevents_collapse_when_zoomed_out():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 0.3)
    assert view._lod_collapsed == {"group"}
    view._set_presentation_detail("full")
    assert view._lod_collapsed == set()
    assert view._box_items["child"].isVisible()
    view._set_presentation_detail(None)
    assert view._lod_collapsed == {"group"}


# ── focus fade on the view ───────────────────────────────────────────────


def test_focus_complete_dims_partly_framed_elements():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 1.0)
    # Frame contains the container and its child, clips loose / the note.
    view._set_presentation_focus(QRectF(-20, -20, 460, 460))
    assert view._box_items["group"].opacity() == 1.0
    assert view._box_items["child"].opacity() == 1.0
    assert view._box_items["loose"].opacity() == 0.08
    assert view._note_items["n1"].opacity() == 0.08
    # child -> loose crosses the frame edge: dimmed. loose -> n1: both out.
    for gfx in view._arrow_items:
        assert gfx.opacity() == 0.08
    view._set_presentation_focus(None)
    assert view._box_items["loose"].opacity() == 1.0
    assert all(gfx.opacity() == 1.0 for gfx in view._arrow_items)


def test_focus_connector_fully_inside_stays_opaque():
    view = _view(parse(SAMPLE))
    _set_zoom(view, 1.0)
    view._set_presentation_focus(QRectF(-50, -50, 1200, 800))
    from grafli.format import Arrow
    for gfx in view._arrow_items:
        if isinstance(gfx.data(0), Arrow):
            assert gfx.opacity() == 1.0
    view._set_presentation_focus(None)


# ── playback wiring ──────────────────────────────────────────────────────


def test_player_applies_and_clears_settings():
    view = _view(parse(SAMPLE))
    view.play_flow("tour")
    player = view._flow_player
    assert player is not None
    # Step 1: detail=full override beats the flow's summary; focus off.
    assert view._present_detail is None or view._present_detail == "full"
    assert view._present_detail == "full"
    assert view._present_focus_rect is None
    assert view._flow_overlay["detail"] == "full"
    assert view._flow_overlay["focus"] == ""
    player.next()
    # Step 2: inherits flow detail=summary; step focus=complete on.
    assert view._present_detail == "summary"
    assert view._present_focus_rect is not None
    assert view._flow_overlay["focus"] == "complete"
    player.stop()
    assert view._present_detail is None
    assert view._present_focus_rect is None


# ── slide plan resolution ────────────────────────────────────────────────


def test_slide_plan_carries_step_settings():
    from grafli.slideplan import build_slide_plan
    board = parse(SAMPLE)
    view = _view(board)
    plans = build_slide_plan(view, board.flow_by_id("tour"))
    assert plans[0].kind == "title"
    assert (plans[1].detail, plans[1].focus) == ("full", "")
    assert (plans[2].detail, plans[2].focus) == ("summary", "complete")


# ── caption cap in the flows panel editor ────────────────────────────────


def test_inline_desc_enforces_cap():
    _app()
    from grafli.flowspanel import _InlineDesc
    edit = _InlineDesc("", max_chars=10)
    edit.setPlainText("x" * 25)
    assert edit.toPlainText() == "x" * 10
    uncapped = _InlineDesc("")
    uncapped.setPlainText("y" * 500)
    assert uncapped.toPlainText() == "y" * 500
