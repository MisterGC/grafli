"""`grafli export --check` names what overloads a slide — each note under
the readable floor, its size in pt at that slide's frame and the floor —
and with `--all-flows` checks every flow of a board in one run (#193)."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.format import parse

_LONG = "every word of this paragraph matters to the reader " * 3

# A substantial note inside a wide frame: at the frame's scale it maps far
# below the 11 pt floor. The second stop frames the note alone, legibly.
WIDE = f"""\
#!grafli v2
@ box frame "Frame" 0,0 4200x2400
@ box huge "Huge" 50,50 4000x2200 >frame
@ note evidence 80,80 "md:\\n{_LONG}" ~width=20 >huge
@ box side "Side" 0,3000 300x120
@ bookmark wide "Overview" @frame,huge,evidence ~iso
@ bookmark side "Side" @side
@ flow f "F" side wide
@ flow g "G" side
"""


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(board):
    _app()
    from grafli.view import GrafliView
    view = GrafliView()
    view.load_board(board)
    return view


def _board_file(tmp_path: Path) -> Path:
    path = tmp_path / "wide.grafli"
    path.write_text(WIDE)
    return path


def _check(finding: dict) -> None:
    assert finding["element"] == "evidence"
    assert finding["reason"] == "below-floor"
    assert finding["floor"] == 11.0
    assert 0 < finding["pt"] < 11.0


def test_pdf_export_names_the_note_under_the_floor(tmp_path: Path):
    from grafli.pdfexport import export_flow_to_pdf
    board = parse(WIDE)
    _, overloaded = export_flow_to_pdf(_view(board), board.flow_by_id("f"),
                                       tmp_path / "wide.pdf")
    [(index, label, findings)] = overloaded
    assert (index, label) == (1, "Overview")
    [finding] = findings
    _check(finding)


def test_pptx_export_names_the_note_under_the_floor(tmp_path: Path):
    from grafli.pptxexport import export_flow_to_pptx
    board = parse(WIDE)
    _, overloaded = export_flow_to_pptx(_view(board), board.flow_by_id("f"),
                                        tmp_path / "wide.pptx")
    [(index, label, findings)] = overloaded
    assert (index, label) == (1, "Overview")
    [finding] = findings
    _check(finding)


def test_check_json_names_element_size_and_floor(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    path = _board_file(tmp_path)
    assert _cmd_export([str(path), "--flow", "f", "--check", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    [entry] = report["overloaded"]
    assert (entry["slide"], entry["label"]) == (2, "Overview")
    [finding] = entry["elements"]
    _check(finding)


def test_check_text_names_element_size_and_floor(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    from grafli.slideplan import describe_overload
    path = _board_file(tmp_path)
    assert _cmd_export([str(path), "--flow", "f", "--check"]) == 1
    lines = capsys.readouterr().out.splitlines()
    [line] = [ln for ln in lines if ln.startswith("[overloaded]")]
    assert line.startswith("[overloaded] slide #2 Overview: note 'evidence' at ")
    assert line.endswith(" pt (floor 11 pt) — trim the text or split the slide")
    assert describe_overload({"element": "n", "pt": 7.25, "floor": 11.0,
                              "reason": "below-floor"}) \
        == "note 'n' at 7.25 pt (floor 11 pt)"


def test_export_warning_names_the_note(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    path = _board_file(tmp_path)
    assert _cmd_export([str(path), str(tmp_path / "out.pdf"),
                        "--flow", "f"]) == 0
    err = capsys.readouterr().err
    assert ("Warning: 1 slide(s) overloaded — trim or split: "
            "#2 Overview: note 'evidence' at ") in err


def test_export_toast_names_the_first_note():
    from grafli.app import _overload_toast
    finding = {"element": "evidence", "pt": 2.2, "floor": 11.0,
               "reason": "below-floor"}
    assert _overload_toast([]) == ""
    assert _overload_toast([(1, "Overview", [finding])]) == (
        " · 1 overloaded: #2 'evidence' 2.2 pt < 11 pt")


def test_all_flows_checks_every_flow_in_one_run(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    path = _board_file(tmp_path)
    assert _cmd_export([str(path), "--check", "--all-flows", "--json"]) == 1
    reports = json.loads(capsys.readouterr().out)
    assert [(r["flow"], r["slides"]) for r in reports] == [("f", 3), ("g", 2)]
    assert [len(r["overloaded"]) for r in reports] == [1, 0]
    _check(reports[0]["overloaded"][0]["elements"][0])


def test_all_flows_text_reports_each_flow(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    path = _board_file(tmp_path)
    assert _cmd_export([str(path), "--check", "--all-flows"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "flow 'f': 3 slides"
    assert lines[1].startswith("[overloaded] slide #2 Overview: ")
    assert lines[2:] == ["flow 'g': 2 slides", "No findings."]


def test_all_flows_is_clean_when_every_flow_is(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    path = _board_file(tmp_path)
    path.write_text(WIDE.replace('@ flow f "F" side wide\n', ""))
    assert _cmd_export([str(path), "--check", "--all-flows"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "flow 'g': 2 slides", "No findings."]


def test_all_flows_needs_check_and_excludes_flow(tmp_path: Path, capsys):
    from grafli.app import _cmd_export
    path = _board_file(tmp_path)
    assert _cmd_export([str(path), str(tmp_path / "o.pdf"),
                        "--all-flows"]) == 2
    assert _cmd_export([str(path), "--check", "--all-flows",
                        "--flow", "f"]) == 2
    assert not (tmp_path / "o.pdf").exists()
