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
    slides = export_flow_to_pdf(view, board.flow_by_id("tour"), out)
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
    slides = export_flow_to_pdf(view, board.flow_by_id("tour"), out)
    assert slides == 4
    assert out.read_bytes().startswith(b"%PDF")


def test_export_restores_selection(tmp_path):
    from grafli.pdfexport import export_flow_to_pdf
    board = parse(SAMPLE)
    view = _view(board)
    view._box_items["a"].setSelected(True)
    export_flow_to_pdf(view, board.flow_by_id("tour"), tmp_path / "t.pdf")
    assert view._box_items["a"].isSelected()   # selection restored after render
