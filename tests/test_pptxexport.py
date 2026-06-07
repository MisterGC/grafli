"""Tests for grafli.pptxexport — flow → editable PowerPoint.

These reopen the generated .pptx with python-pptx and assert structure (slide
count, native title/caption/footer text, embedded diagram pictures, theme colour
and font references, markdown run formatting). Because a .pptx is inspectable
XML, this verifies the real output rather than just that export ran.
"""

from __future__ import annotations

import os

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.pptxexport import export_flow_to_pptx

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Three content stops: a normal diagram stop with a caption, a second diagram
# stop, and a text slide (single-note focus, no description). Plus a footer.
SAMPLE = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ box b "B" 300,0 120x60
@ arrow a -> b "talks"
@ note ntxt 600,0 "md:\\n# Heading\\n\\n**bold** and a [link](https://example.com)\\n\\n- one\\n- two"
@ bookmark bm1 "Overview" @a,b "Both parts."
@ bookmark bm2 "Just A" @a "The left one."
@ bookmark bmtext "Notes" @ntxt
@ flow tour "Tour" bm1 bm2:5 bmtext "Wide then in."
@ footer "(c) Team"
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(board):
    _app()
    from grafli.view import GrafliView
    v = GrafliView()
    v.load_board(board)
    return v


def _texts(slide):
    return [sh.text_frame.text for sh in slide.shapes
            if sh.has_text_frame and sh.text_frame.text.strip()]


def _has_picture(slide):
    return any(sh.shape_type == MSO_SHAPE_TYPE.PICTURE for sh in slide.shapes)


def _theme_root(prs):
    part = prs.slide_masters[0].part.part_related_by(RT.THEME)
    return etree.fromstring(part.blob)


def _scheme_color(prs, slot):
    clr = _theme_root(prs).find(".//" + qn("a:clrScheme"))
    el = clr.find(qn("a:" + slot))[0]
    return el.get("val") or el.get("lastClr")


def test_export_produces_title_plus_one_slide_per_stop(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "tour.pptx"
    slides, _ = export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    assert slides == 4                       # title + 3 stops
    prs = Presentation(out)
    assert len(prs.slides._sldIdLst) == 4


def test_slide_size_is_16x9(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    # 960x540 pt in EMU (12700 EMU per pt).
    assert prs.slide_width == 960 * 12700
    assert prs.slide_height == 540 * 12700


def test_title_progress_and_caption_are_native_text(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    first = list(prs.slides)[1]              # first content stop (bm1)
    texts = _texts(first)
    assert "Overview" in texts
    assert "1 / 3" in texts
    assert any("Both parts." in t for t in texts)   # caption


def test_diagram_is_an_embedded_picture(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    assert _has_picture(list(prs.slides)[1])


def test_text_slide_is_native_text_without_picture(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    text_slide = list(prs.slides)[3]         # bmtext, single-note focus
    assert not _has_picture(text_slide)
    body = " ".join(_texts(text_slide))
    assert "bold" in body and "Heading" in body


def test_footer_present_on_content_slides(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    assert any("(c) Team" in t for t in _texts(list(prs.slides)[1]))


def test_markdown_bold_and_link_become_runs(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    text_slide = list(prs.slides)[3]
    runs = [r for sh in text_slide.shapes if sh.has_text_frame
            for p in sh.text_frame.paragraphs for r in p.runs]
    assert any(r.font.bold for r in runs)                       # **bold**
    assert any(r.hyperlink.address for r in runs)               # [link](...)
    assert any(r.hyperlink.address == "https://example.com" for r in runs)


def test_runs_use_theme_font_and_colour_refs(tmp_path):
    # Theme-friendly: a global theme/font swap must cascade, so runs reference
    # the theme font (+mj-lt/+mn-lt) and a scheme colour rather than literals.
    from pptx.enum.dml import MSO_COLOR_TYPE
    board = parse(SAMPLE)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    title_run = None
    for sh in list(prs.slides)[1].shapes:
        if sh.has_text_frame and sh.text_frame.text.strip() == "Overview":
            title_run = sh.text_frame.paragraphs[0].runs[0]
    assert title_run is not None
    assert title_run.font.name in ("+mj-lt", "+mn-lt")
    assert title_run.font.color.type == MSO_COLOR_TYPE.SCHEME


def test_grafli_theme_injects_palette_and_font(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "g.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out,
                        theme="grafli")
    prs = Presentation(out)
    assert _scheme_color(prs, "accent1").upper() == "D4804E"   # grafli accent
    assert _scheme_color(prs, "lt1").upper() == "E8E4DD"       # paper bg
    major = _theme_root(prs).find(
        ".//" + qn("a:majorFont") + "/" + qn("a:latin")).get("typeface")
    assert "JetBrains" in major


def test_blank_theme_keeps_default_office_theme(tmp_path):
    board = parse(SAMPLE)
    out = tmp_path / "b.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out,
                        theme="blank")
    prs = Presentation(out)
    assert _scheme_color(prs, "accent1").upper() != "D4804E"   # untouched


def test_graph_only_stop_has_picture_and_no_title(tmp_path):
    # Drop the footer so the graph-only stop is truly chrome-free (the footer is
    # board-global and shows on every content slide, including this one).
    src = SAMPLE.replace('@ footer "(c) Team"\n', '')
    src = src.replace('@ flow tour "Tour" bm1 bm2:5 bmtext',
                      '@ bookmark bm0 "" @a,b\n@ flow tour "Tour" bm0 bm1 bm2:5 bmtext')
    board = parse(src)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), out)
    prs = Presentation(out)
    graph_only = list(prs.slides)[1]         # bm0: no label, no description
    assert _has_picture(graph_only)
    assert _texts(graph_only) == []          # no title/progress/caption chrome


def test_container_box_label_titles_the_slide(tmp_path):
    src = """\
#!grafli v2
@ box frame "Frame" 0,0 400x200
@ box c1 "C" 200,40 120x60 >frame
@ note n1 20,20 "md:\\nhi" ~width=20 >frame
@ bookmark bmc "" @frame,n1,c1 ~iso
@ flow fc "FC" bmc
"""
    board = parse(src)
    out = tmp_path / "t.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("fc"), out)
    prs = Presentation(out)
    assert any(t == "Frame" for t in _texts(list(prs.slides)[1]))


def test_overload_reported_when_inplace_note_too_small(tmp_path):
    wide = """\
#!grafli v2
@ box frame "Frame" 0,0 4200x2400
@ box huge "Huge" 50,50 4000x2200 >frame
@ note cap 80,80 "md:\\nsmall caption text here" ~width=20 >huge
@ bookmark bmO "" @frame,huge,cap ~iso
@ flow f "F" bmO
"""
    board = parse(wide)
    out = tmp_path / "wide.pptx"
    _, overloaded = export_flow_to_pptx(_view(board), board.flow_by_id("f"), out)
    assert overloaded and overloaded[0][0] == 0


def test_export_restores_selection(tmp_path):
    board = parse(SAMPLE)
    view = _view(board)
    view._box_items["a"].setSelected(True)
    export_flow_to_pptx(view, board.flow_by_id("tour"), tmp_path / "t.pptx")
    assert view._box_items["a"].isSelected()


def test_blank_theme_omits_title_accent_rule(tmp_path):
    # The decorative accent rule on the cover is grafli-only chrome; the blank
    # preset drops it (cleaner base for corporate templates), so its title slide
    # carries fewer shapes than grafli's for the same flow.
    board = parse(SAMPLE)
    g = tmp_path / "g.pptx"
    b = tmp_path / "b.pptx"
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), g, theme="grafli")
    export_flow_to_pptx(_view(board), board.flow_by_id("tour"), b, theme="blank")
    g_cover = len(list(Presentation(g).slides)[0].shapes)
    b_cover = len(list(Presentation(b).slides)[0].shapes)
    assert g_cover > b_cover
