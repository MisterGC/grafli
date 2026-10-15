"""The layered top-board example in the skill's explaining.md (#199): it
passes `diagnose --strict`, and zoomed out it still reads as a stack of
named layers — full-width bands, one under the other, each titled."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.app import _cmd_diagnose, _cmd_render
from grafli.format import parse
from grafli.view import GrafliView

REPO = Path(__file__).resolve().parent.parent
EXPLAINING = REPO / "grafli" / "skills" / "grafli" / "references" / "explaining.md"
LAYERS = ("Exports", "App shell", "Canvas", "Format")


def _example() -> tuple[str, str]:
    """The palette and the board of "Example — the top board of a code map"."""
    text = EXPLAINING.read_text()
    section = text.split("## Example — the top board of a code map", 1)[1]
    section = section.split("\n## ", 1)[0]
    palette, board = re.findall(r"```(?:json)?\n(.*?)```", section, re.S)
    return palette, board


def _write(tmp_path: Path) -> Path:
    """The example as files: its `# source:` pointed at this checkout, so
    its evidence refs resolve, and a stub behind every `&graph`/`&doc`."""
    palette, board = _example()
    board = re.sub(r"^# source: .*$", f"# source: {REPO}", board, flags=re.M)
    res = tmp_path / "map-res"
    res.mkdir()
    (res / "palette.json").write_text(palette)
    for name in re.findall(r"&graph:(\w+)", board):
        (res / f"{name}.grafli").write_text('#!grafli v1\n@ note q 0,0 "stub"\n')
    for name in re.findall(r"&doc:(\w+)", board):
        (res / f"{name}.md").write_text("Stub.\n")
    path = tmp_path / "map.grafli"
    path.write_text(board)
    return path


def test_the_example_passes_diagnose_strict(tmp_path: Path):
    assert _cmd_diagnose([str(_write(tmp_path)), "--strict"]) == 0


def test_zoomed_out_the_example_is_a_stack_of_named_layers(tmp_path: Path):
    path = _write(tmp_path)
    QApplication.instance() or QApplication([])
    assert _cmd_render([str(path), str(tmp_path / "lod.png"), "--lod"]) == 0
    board = parse(path.read_text())
    view = GrafliView()
    view.load_board(board)
    view._present_detail = "summary"
    view._refresh_lod()
    layers = [b for b in board.boxes if not b.parent]
    assert [b.label for b in layers] == list(LAYERS)
    for box in layers:
        item = view._box_items[box.id]
        assert box.anchor == "left"
        assert item._lod_tile is not None and item._lod_tile[0] == box.label
    # Full width and one under the other: the same x and width, rising y.
    assert len({(b.x, b.w) for b in layers}) == 1
    assert [b.y for b in layers] == sorted(b.y for b in layers)
    assert all(a.y + a.h <= b.y for a, b in zip(layers, layers[1:]))


# The slide-grade level (#220): the `Parser` sub-board of the map above.
SLIDE_GRADE = "## Slide-grade boards — a claim, three weights, a path"


def _write_level(tmp_path: Path) -> Path:
    """The slide-grade example as `map-res/parser.grafli`, inside the map
    whose palette it uses, with stubs behind its `&doc`s."""
    _write(tmp_path)
    text = EXPLAINING.read_text()
    section = text.split("## Example — a slide-grade level", 1)[1]
    section = section.split("\n## ", 1)[0]
    (board,) = re.findall(r"```\n(.*?)```", section, re.S)
    board = re.sub(r"^# source: .*$", f"# source: {REPO}", board, flags=re.M)
    res = tmp_path / "map-res" / "parser-res"
    res.mkdir()
    for name in re.findall(r"&doc:(\w+)", board):
        (res / f"{name}.md").write_text("Stub.\n")
    path = tmp_path / "map-res" / "parser.grafli"
    path.write_text(board)
    return path


def test_the_slide_grade_example_passes_diagnose_strict(tmp_path: Path):
    assert _cmd_diagnose([str(_write_level(tmp_path)), "--strict"]) == 0


def test_the_slide_grade_example_uses_each_technique(tmp_path: Path):
    board = parse(_write_level(tmp_path).read_text())
    boxes = {b.id: b for b in board.boxes}
    claim = next(n for n in board.notes if n.id == "claim")
    assert claim.style == "sans" and claim.flat
    # One emphasis: a card in a loud token with ink on its fill.
    assert [b.id for b in board.boxes if b.color == "%primary"] == ["board"]
    assert boxes["board"].style == "card" and boxes["board"].ink
    # A numbered path, filled numbers before the label, in order.
    path = [b for b in board.boxes if b.icon.startswith("solid-")]
    assert [b.icon for b in path] == [f"solid-{n}" for n in range(1, 5)]
    assert {b.icon_placement for b in path} == {"lead"}
    # Category bars: every connector into a column takes its bar's colour.
    bars = {"app": ["canvas"], "out": ["render", "slides", "html"]}
    for bar, members in bars.items():
        assert boxes[bar].ink
        for member in members:
            (arrow,) = [a for a in board.arrows if a.to_id == member]
            assert arrow.color == boxes[bar].color == boxes[member].color
            assert (arrow.from_side, arrow.to_side) == ("right", "left")
    assert all(boxes[m].status for ms in bars.values() for m in ms)


def test_every_slide_grade_technique_names_its_gui_path():
    section = EXPLAINING.read_text().split(SLIDE_GRADE, 1)[1]
    section = section.split("\n## ", 1)[0]
    techniques = section.split("\n* **")[1:]
    assert len(techniques) == 7
    for technique in techniques:
        assert "GUI:" in technique, technique.split("**", 1)[0]
