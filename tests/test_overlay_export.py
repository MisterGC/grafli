"""Overlays outside the app: `render --overlay` and the exports (#215)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.format import parse
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_BOARD = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ box b "B" 300,0 120x60
@ box c "C" 600,0 120x60
@ arrow a -> b ""
@ arrow b -> c ""
"""

TESTS = {
    "title": "Test results",
    "producer": "overlay_tests.py",
    "kind": "category",
    "categories": [
        {"id": "pass", "label": "Passing", "color": "#00ff00"},
        {"id": "fail", "label": "Failing", "color": "#ff0000"},
    ],
    "entries": {"a": {"category": "fail"}, "b": {"category": "pass"}},
}


def _map(tmp_path: Path, src: str = _BOARD, **overlays) -> Path:
    board = tmp_path / "map.grafli"
    board.write_text(src)
    res = tmp_path / "map-res"
    res.mkdir(exist_ok=True)
    for name, data in overlays.items():
        (res / f"{name}.overlay.json").write_text(
            data if isinstance(data, str) else json.dumps(data))
    return board


def _render(board: Path, out: Path, *flags: str) -> int:
    from grafli.app import _cmd_render
    return _cmd_render([str(board), str(out), *flags])


def _view_of(board: Path) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view._file_path = board      # the view is its own window here
    view.load_board(parse(board.read_text()))
    return view


# ── render --overlay ────────────────────────────────────────────────

def test_render_overlay_colours_the_board_and_adds_its_legend(tmp_path):
    board = _map(tmp_path, tests=TESTS)
    assert _render(board, tmp_path / "plain.png") == 0
    assert _render(board, tmp_path / "tests.png", "--overlay", "tests") == 0
    plain = QImage(str(tmp_path / "plain.png"))
    shown = QImage(str(tmp_path / "tests.png"))
    assert shown.width() >= plain.width()
    assert shown.height() > plain.height()
    # The page takes the overlay's darkened canvas, the legend band too.
    heat_bg = theme.HEATMAP_BG.name()
    assert QColor(shown.pixel(2, 2)).name() == heat_bg
    assert QColor(shown.pixel(2, shown.height() - 3)).name() == heat_bg
    assert QColor(plain.pixel(2, 2)).name() == theme.SCENE_BG.name()


def test_render_overlay_to_svg_names_the_legend(tmp_path):
    board = _map(tmp_path, tests=TESTS)
    assert _render(board, tmp_path / "plain.svg") == 0
    assert _render(board, tmp_path / "tests.svg", "--overlay", "tests") == 0
    plain = (tmp_path / "plain.svg").read_text()
    shown = (tmp_path / "tests.svg").read_text()
    for text in ("Test results", "overlay_tests.py", "Passing", "Failing",
                 "no data"):
        assert text not in plain
        assert text in shown


def test_render_overlay_with_the_palette_legend_draws_both(tmp_path):
    src = (_BOARD.replace("v2", "v4")
           .replace('"A" 0,0 120x60', '"A" 0,0 120x60 %core'))
    board = _map(tmp_path, src, tests=TESTS)
    (tmp_path / "map-res" / "palette.json").write_text(json.dumps(
        {"entries": {"core": {"color": "#3366cc", "label": "Core model"}}}))
    assert _render(board, tmp_path / "both.svg", "--overlay", "tests",
                   "--legend") == 0
    svg = (tmp_path / "both.svg").read_text()
    assert "Core model" in svg
    assert "Test results" in svg


def test_render_overlay_names_the_available_ones_when_unknown(tmp_path,
                                                               capsys):
    board = _map(tmp_path, tests=TESTS)
    assert _render(board, tmp_path / "x.png", "--overlay", "churn") == 2
    err = capsys.readouterr().err
    assert "no overlay 'churn'" in err
    assert "available: tests" in err
    assert not (tmp_path / "x.png").exists()


def test_render_overlay_reports_a_broken_file(tmp_path, capsys):
    board = _map(tmp_path, tests="{ not json")
    assert _render(board, tmp_path / "x.png", "--overlay", "tests") == 2
    assert "--overlay" in capsys.readouterr().err


def test_render_without_overlay_is_unchanged_by_overlay_files(tmp_path):
    board = _map(tmp_path)
    assert _render(board, tmp_path / "before.png") == 0
    _map(tmp_path, tests=TESTS)
    assert _render(board, tmp_path / "after.png") == 0
    assert (QImage(str(tmp_path / "before.png"))
            == QImage(str(tmp_path / "after.png")))


def test_the_app_svg_export_carries_the_shown_overlay(tmp_path):
    view = _view_of(_map(tmp_path, tests=TESTS))
    assert b"Test results" not in bytes(view._render_svg_bytes())
    view.show_overlay("tests")
    assert b"Test results" in bytes(view._render_svg_bytes())
    view._clear_complexity_heatmap()
    assert b"Test results" not in bytes(view._render_svg_bytes())
