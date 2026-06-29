"""Tests for grafli.pdfexport — flow → slide PDF."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SAMPLE = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ box b "B" 300,0 120x60
@ arrow a -> b "talks"
@ bookmark bm1 "Overview" @a,b "Both parts."
@ bookmark bm2 "Just A" @a "The left one."
@ flow tour "Tour" bm1 bm2:5 "Wide then in."
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(board):
    _app()
    from grafli.view import GrafliView
    v = GrafliView()
    v.load_board(board)
    return v


def _page_count(pdf_bytes: bytes) -> int:
    # /Type /Page objects minus the single /Pages tree node.
    pages = pdf_bytes.count(b"/Type /Page") + pdf_bytes.count(b"/Type/Page")
    trees = pdf_bytes.count(b"/Type /Pages") + pdf_bytes.count(b"/Type/Pages")
    return pages - trees


def test_export_produces_title_plus_one_slide_per_stop(tmp_path):
    from grafli.pdfexport import export_flow_to_pdf
    board = parse(SAMPLE)
    view = _view(board)
    out = tmp_path / "tour.pdf"
    slides, _ = export_flow_to_pdf(view, board.flow_by_id("tour"), out)
    assert slides == 3                       # title + 2 stops
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert _page_count(data) == 3


def test_export_handles_viewport_only_bookmark(tmp_path):
    from grafli.pdfexport import export_flow_to_pdf
    src = SAMPLE + '@ bookmark bm3 "Exact" ~view=0,0,400,200\n'
    src = src.replace('bm1 bm2:5', 'bm1 bm2:5 bm3')
    board = parse(src)
    view = _view(board)
    out = tmp_path / "tour2.pdf"
    slides, _ = export_flow_to_pdf(view, board.flow_by_id("tour"), out)
    assert slides == 4
    assert out.read_bytes().startswith(b"%PDF")


def test_export_graph_only_stop(tmp_path):
    # A label-less, description-less bookmark exports as a clean diagram-only
    # slide (no chrome) without error, and the scene background is restored.
    from grafli.pdfexport import export_flow_to_pdf
    src = SAMPLE.replace('@ flow tour "Tour" bm1 bm2:5',
                         '@ bookmark bm0 "" @a,b\n@ flow tour "Tour" bm0 bm1 bm2:5')
    board = parse(src)
    view = _view(board)
    bg_before = view._scene.backgroundBrush().color().name()
    out = tmp_path / "graphonly.pdf"
    slides, _ = export_flow_to_pdf(view, board.flow_by_id("tour"), out)
    assert slides == 4
    assert out.read_bytes().startswith(b"%PDF")
    assert view._scene.backgroundBrush().color().name() == bg_before


def test_overload_reported_when_inplace_note_too_small(tmp_path):
    # A slide whose framed area is dominated by a large sibling maps its small
    # in-place note below the readable floor, so the step is reported overloaded.
    from grafli.pdfexport import export_flow_to_pdf
    wide = """\
#!grafli v2
@ box frame "Frame" 0,0 4200x2400
@ box huge "Huge" 50,50 4000x2200 >frame
@ note cap 80,80 "md:\\nsmall caption text here" ~width=20 >huge
@ bookmark bmO "" @frame,huge,cap ~iso
@ flow f "F" bmO
"""
    board = parse(wide)
    view = _view(board)
    _, overloaded = export_flow_to_pdf(view, board.flow_by_id("f"),
                                       tmp_path / "wide.pdf")
    assert overloaded and overloaded[0][0] == 0


def test_container_slide_frames_contents_not_the_box():
    # A container slide frames the union of the container's *contents*, not the
    # container box — its label/border/padding are chrome, so the content fills
    # the page instead of becoming a small centered island.
    from grafli.pdfexport import _container_box, _slide_source
    src = """\
#!grafli v2
@ box frame "Frame" 0,0 395x200
@ note n1 20,20 "md:\\nhello" ~width=20 >frame
@ box c1 "C" 200,40 120x60 >frame
@ bookmark bm "" @frame,n1,c1 ~iso
@ flow f "F" bm
"""
    board = parse(src)
    view = _view(board)
    bm = board.bookmark_by_id("bm")
    container = _container_box(board, bm)
    assert container is not None and container.id == "frame"
    source = _slide_source(view, bm, container)
    n1r = view._note_items["n1"].sceneBoundingRect()
    c1r = view._box_items["c1"].sceneBoundingRect()
    framer = view._box_items["frame"].sceneBoundingRect()
    assert source.contains(n1r) and source.contains(c1r)  # frames the contents
    assert source.width() < framer.width()                # tighter than the box


def test_normal_flow_not_overloaded(tmp_path):
    from grafli.pdfexport import export_flow_to_pdf
    board = parse(SAMPLE)
    view = _view(board)
    _, overloaded = export_flow_to_pdf(view, board.flow_by_id("tour"),
                                       tmp_path / "t.pdf")
    assert overloaded == []


def test_export_restores_selection(tmp_path):
    from grafli.pdfexport import export_flow_to_pdf
    board = parse(SAMPLE)
    view = _view(board)
    view._box_items["a"].setSelected(True)
    export_flow_to_pdf(view, board.flow_by_id("tour"), tmp_path / "t.pdf")
    assert view._box_items["a"].isSelected()   # selection restored after render
