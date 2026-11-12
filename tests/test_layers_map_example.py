"""The slide-grade worked example (examples/layers-map.grafli, #222): every
board passes `diagnose --strict` and `export --check`, every tour stop has a
headline, the PDF deck's legend comes from the map's palette and no board
draws one by hand, source refs point at their symbols, and the overlay is
keyed by the top board's parts."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from grafli.app import _cmd_diagnose, _cmd_export, _cmd_render, _step_bookmark
from grafli.format import parse, resolve_code_ref
from grafli.map_palette import load_palette
from grafli.overlay_file import load_overlay

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
REPO = EXAMPLES.parent
ROOT = EXAMPLES / "layers-map.grafli"
RES = EXAMPLES / "layers-map-res"
BOARDS = (ROOT, RES / "parse.grafli", RES / "exports.grafli")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _board(path: Path):
    return parse(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.name)
def test_every_board_passes_diagnose_strict(path: Path):
    _app()
    assert _cmd_diagnose(["--strict", str(path)]) == 0


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.name)
def test_every_board_passes_the_slide_check(path: Path, capsys):
    _app()
    assert _cmd_export([str(path), "--check", "--all-flows"]) == 0
    assert "No findings." in capsys.readouterr().out


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.name)
def test_every_stop_has_a_one_line_headline(path: Path):
    board = _board(path)
    assert board.flows, path.name
    for flow in board.flows:
        for step in flow.steps:
            bm = _step_bookmark(path, board, step.ref)
            assert bm is not None, step.ref
            assert bm.label.strip(), (path.name, step.ref)
            assert len(bm.label) <= 35, (path.name, step.ref, bm.label)


def test_the_entry_tour_enters_both_levels():
    board = _board(ROOT)
    homes = {step.ref.rpartition("#")[0] or "root"
             for step in board.flow_by_id("entry").steps}
    assert homes == {"root", "parse", "exports"}


def test_the_pdf_deck_draws_the_palette_legend_on_every_diagram_slide(
        tmp_path: Path, monkeypatch):
    from grafli import pdfexport
    _app()
    drawn: list = []
    original = pdfexport.draw_legend

    def spy(painter, rect, entries, px, ink=None):
        drawn.append([e.label for e in entries])
        original(painter, rect, entries, px, ink)

    monkeypatch.setattr(pdfexport, "draw_legend", spy)
    out = tmp_path / "deck.pdf"
    assert _cmd_export([str(ROOT), str(out), "--legend"]) == 0
    assert out.read_bytes().startswith(b"%PDF")
    stops = len(_board(ROOT).flow_by_id("entry").steps)
    assert len(drawn) == stops
    labels = {e.label for e in load_palette(ROOT)}
    assert all(set(d) <= labels and d for d in drawn), drawn


@pytest.mark.parametrize("path", BOARDS, ids=lambda p: p.name)
def test_no_board_draws_a_legend_by_hand(path: Path):
    """No element names a legend, and no note lists two layer names: the
    key is the palette's, drawn by the app and the exports."""
    labels = {e.label for e in load_palette(path)}
    board = _board(path)
    for el in (*board.boxes, *board.notes):
        assert "legend" not in el.id.lower(), el.id
    for box in board.boxes:
        assert "legend" not in box.label.lower(), box.id
    for note in board.notes:
        named = {lb for lb in labels if re.search(rf"\b{lb}\b", note.text)}
        assert len(named) < 2, (path.name, note.id, named)


def test_every_box_names_a_palette_entry_or_sits_in_a_layer():
    for path in BOARDS:
        names = {e.name for e in load_palette(path)}
        board = _board(path)
        for box in board.boxes:
            colour = box.color.removeprefix("%")
            if box.parent:
                continue
            assert colour in names or colour == "primary" or not colour, (
                path.name, box.id)


_IDENT = re.compile(r"[A-Za-z_][\w.]*(?:\(\))?")
_NOTE_REF = re.compile(r"@(\S+?):(\d+)(?:\s+(\S+))?")
_DOC_REF = re.compile(r"`([\w./-]+\.py):(\d+)`")


def _refs() -> list[tuple[str, Path, int, str]]:
    """(where, file, line, symbol) of every ref in the boards' notes (the
    symbol written after it) and in their docs (the last backticked
    identifier before it in its paragraph)."""
    refs = []
    for path in BOARDS:
        board = _board(path)
        for note in board.notes:
            for m in _NOTE_REF.finditer(note.text):
                file, _ = resolve_code_ref(board, path.parent, m.group(1))
                refs.append((f"{path.name} {note.id}", file,
                             int(m.group(2)), m.group(3) or ""))
    for doc in sorted(RES.rglob("*.md")):
        for para in re.split(r"\n\s*\n", doc.read_text(encoding="utf-8")):
            for m in _DOC_REF.finditer(para):
                symbol = ""
                for t in re.finditer(r"`([^`]+)`", para[:m.start()]):
                    if _IDENT.fullmatch(t.group(1)):
                        symbol = t.group(1)
                refs.append((f"{doc.relative_to(RES)}: {m.group(0)}",
                             REPO / m.group(1), int(m.group(2)), symbol))
    return refs


def test_every_source_ref_points_at_its_symbol():
    refs = _refs()
    assert len(refs) >= 30, len(refs)
    problems = []
    for where, path, line, symbol in refs:
        if len(symbol) < 4:
            problems.append(f"{where}: no symbol to check the ref against")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        window = "\n".join(lines[max(line - 3, 0):line + 2])
        if symbol.removesuffix("()") not in window:
            problems.append(f"{where}: {symbol} not within 2 lines of "
                            f"{path.name}:{line}")
    assert not problems, "\n".join(problems)


def test_the_overlay_colours_every_part_of_the_top_board(tmp_path: Path):
    overlay = load_overlay(RES / "tests.overlay.json")
    board = _board(ROOT)
    containers = {b.parent for b in board.boxes if b.parent}
    parts = {b.id for b in board.boxes if b.id not in containers}
    assert set(overlay.entries) == parts
    assert overlay.producer and overlay.revision
    _app()
    out = tmp_path / "overlay.png"
    assert _cmd_render([str(ROOT), str(out), "--overlay", "tests"]) == 0
    assert out.stat().st_size > 0
