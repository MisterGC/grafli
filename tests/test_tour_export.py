"""Exporting a tour whose stops lie in other boards: each such stop renders
from its own board, in the PDF and PPTX export and in `grafli render
--step` (#165)."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write(path: Path, *lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def _system(tmp_path: Path) -> Path:
    """A three-stop tour on System: one stop on it, one in its sub-board,
    one in the sub-board's sub-board (named by a relative path)."""
    root = _write(
        tmp_path / "System.grafli",
        "#!grafli v2",
        '@ box player "Player" 0,0 120x60',
        '@ box combat "Combat" 400,0 120x60 &graph:combat',
        '@ bookmark r1 "The player" @player',
        '@ flow tour "A blow lands" r1 combat#c1 '
        'System-res/combat-res/impact.grafli#i1')
    _write(tmp_path / "System-res" / "combat.grafli",
           "#!grafli v2",
           '@ box blow "blow()" 0,0 120x60',
           '@ box impact "impact()" 400,0 120x60 &graph:impact',
           '@ bookmark c1 "The blow" @blow "Where it starts."')
    _write(tmp_path / "System-res" / "combat-res" / "impact.grafli",
           "#!grafli v2",
           '@ box hit "hit test" 0,0 120x60',
           '@ box shake "camera shake" 300,0 120x60',
           '@ bookmark i1 "The hit test" @hit,shake')
    return root


def _view(board):
    _app()
    from grafli.view import GrafliView
    view = GrafliView()
    view.load_board(board)
    return view


def _page_count(pdf_bytes: bytes) -> int:
    pages = pdf_bytes.count(b"/Type /Page") + pdf_bytes.count(b"/Type/Page")
    trees = pdf_bytes.count(b"/Type /Pages") + pdf_bytes.count(b"/Type/Pages")
    return pages - trees


def test_the_tour_board_is_written_as_v3(tmp_path: Path):
    root = _system(tmp_path)
    assert serialize(parse(root.read_text())).splitlines()[0] == "#!grafli v3"


def test_each_stop_is_planned_from_the_board_it_lies_in(tmp_path: Path):
    from grafli.slideplan import build_slide_plan
    root = _system(tmp_path)
    board = parse(root.read_text())
    view = _view(board)
    plans = build_slide_plan(view, board.flow_by_id("tour"), root)
    stops = plans[1:]
    assert [p.title for p in stops] == ["The player", "The blow",
                                        "The hit test"]
    assert [p.caption for p in stops] == ["", "Where it starts.", ""]
    assert all(p.source is not None for p in stops)
    assert stops[0].view is view
    assert stops[1].view.board.box_by_id("blow") is not None
    assert stops[2].view.board.box_by_id("shake") is not None
    # Its framing is the one that board's own bookmark gives.
    hit = stops[2].view._box_items["hit"].sceneBoundingRect()
    assert stops[2].source.contains(hit)


def test_the_pdf_has_a_page_per_stop_after_the_title(tmp_path: Path):
    from grafli.pdfexport import export_flow_to_pdf
    root = _system(tmp_path)
    board = parse(root.read_text())
    out = tmp_path / "tour.pdf"
    slides, overloaded = export_flow_to_pdf(
        _view(board), board.flow_by_id("tour"), out, root)
    assert (slides, overloaded) == (4, [])
    assert _page_count(out.read_bytes()) == 4     # title + 3 stops


def test_without_its_board_path_a_stop_elsewhere_is_missing(tmp_path: Path):
    from grafli.slideplan import build_slide_plan
    root = _system(tmp_path)
    board = parse(root.read_text())
    plans = build_slide_plan(_view(board), board.flow_by_id("tour"))
    assert [p.title for p in plans[2:]] == ["(missing bookmark)"] * 2


def test_the_pptx_has_a_slide_per_stop_after_the_title(tmp_path: Path):
    from pptx import Presentation
    from grafli.pptxexport import export_flow_to_pptx
    root = _system(tmp_path)
    board = parse(root.read_text())
    out = tmp_path / "tour.pptx"
    slides, _ = export_flow_to_pptx(_view(board), board.flow_by_id("tour"),
                                    out, board_path=root)
    assert slides == 4
    assert len(Presentation(str(out)).slides) == 4


def test_export_cli_writes_the_pdf_and_checks_clean(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    root = _system(tmp_path)
    out = tmp_path / "cli.pdf"
    assert _cmd_export([str(root), str(out)]) == 0
    assert _page_count(out.read_bytes()) == 4
    capsys.readouterr()
    assert _cmd_export([str(root), "--check", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["slides"] == 4
    assert report["dangling"] == []


def test_export_check_flags_a_stop_in_a_missing_board(tmp_path: Path,
                                                      capsys):
    from grafli.app import _cmd_export
    root = _system(tmp_path)
    root.write_text(root.read_text().replace("combat#c1", "combat#gone"))
    assert _cmd_export([str(root), "--check", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["dangling"] == [
        "flow 'tour' step references missing bookmark 'combat#gone'"]


def test_render_step_renders_a_stop_from_its_board(tmp_path: Path):
    from grafli.app import _cmd_render
    root = _system(tmp_path)
    out = tmp_path / "stop3.svg"
    assert _cmd_render([str(root), str(out), "--step", "tour:3"]) == 0
    # The same picture as rendering that board's bookmark directly.
    impact = tmp_path / "System-res" / "combat-res" / "impact.grafli"
    direct = tmp_path / "direct.svg"
    assert _cmd_render([str(impact), str(direct), "--bookmark", "i1"]) == 0
    assert out.read_text() == direct.read_text()
