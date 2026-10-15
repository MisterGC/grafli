"""The map palette's legend (#214): a swatch and a label per palette entry
the board uses, toggled with Shift+M on the canvas, drawn below the board by
``render --legend`` and the SVG/PNG exports, and in a band at the bottom of a
PDF diagram slide. Off, or on a board that uses no palette entry, nothing
changes.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.legend import legend_height, used_entries
from grafli.map_palette import Entry
from grafli.view import GrafliView

BOARD = ('#!grafli v4\n'
         '@ box app "App" 0,0 200x100 %ui\n'
         '@ box fmt "Format" 300,0 200x100 %core ~status=new:%hot\n'
         '@ note n 0,200 "a note" %primary\n'
         '@ arrow app -> fmt\n'
         '@ bookmark all "All" @app,fmt\n'
         '@ flow tour "Tour" all\n')
UI, CORE, HOT, SPARE = "#2471A3", "#1E8449", "#C0392B", "#7D3C98"
ENTRIES = {"spare": {"color": SPARE, "label": "Not on the board"},
           "ui": {"color": UI, "label": "User interface"},
           "core": {"color": CORE, "label": "Core model"},
           "hot": {"color": HOT, "label": "Hot path"}}


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _map(tmp_path: Path, text: str = BOARD) -> Path:
    board = tmp_path / "map.grafli"
    board.write_text(text)
    (tmp_path / "map-res").mkdir()
    (tmp_path / "map-res" / "palette.json").write_text(
        json.dumps({"entries": ENTRIES}))
    return board


def _view_of(path: Path) -> GrafliView:
    _app()
    view = GrafliView()
    view.render_headless(path)
    view.load_board(parse(path.read_text()))
    return view


def _count(img: QImage, color: QColor) -> int:
    """Pixels of *img* within a few levels of *color*, every other one."""
    hits = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            p = img.pixelColor(x, y)
            if (abs(p.red() - color.red()) <= 6
                    and abs(p.green() - color.green()) <= 6
                    and abs(p.blue() - color.blue()) <= 6):
                hits += 1
    return hits


# ── Which entries ─────────────────────────────────────────────────

def test_the_legend_lists_the_entries_the_board_uses_in_palette_order():
    entries = [Entry("spare", SPARE, "Spare"), Entry("hot", HOT, "Hot"),
               Entry("ui", UI, "UI"), Entry("core", CORE, "Core")]
    board = parse(BOARD)
    assert [e.name for e in used_entries(board, entries)] == [
        "hot", "ui", "core"]


def test_notes_and_connectors_count_as_using_an_entry():
    entries = [Entry("ui", UI, "UI"), Entry("core", CORE, "Core")]
    board = parse('@ box a "A" 0,0 100x50\n@ box b "B" 200,0 100x50\n'
                  '@ note n 0,100 "x" %ui\n@ arrow a -> b %core\n')
    assert [e.name for e in used_entries(board, entries)] == ["ui", "core"]


def test_no_entries_no_legend():
    assert used_entries(parse(BOARD), []) == []
    assert used_entries(None, [Entry("ui", UI, "UI")]) == []
    assert legend_height([], 14, 500) == 0


def test_a_narrow_legend_wraps_onto_more_rows():
    _app()
    entries = [Entry(n, UI, f"Label {n}") for n in ("a", "b", "c", "d")]
    one_row = legend_height(entries, 14, 10_000)
    assert legend_height(entries, 14, 120) >= 4 * one_row * 0.99


# ── Canvas ────────────────────────────────────────────────────────

def _press_shift_m(view: GrafliView) -> None:
    from PySide6.QtTest import QTest
    QTest.keyClick(view, Qt.Key.Key_M, Qt.KeyboardModifier.ShiftModifier)


def test_shift_m_toggles_the_legend_card_on_the_canvas(tmp_path: Path):
    view = _view_of(_map(tmp_path))
    view.resize(900, 600)
    off = view.viewport().grab().toImage()
    assert not view._legend_visible
    assert _count(off, QColor(SPARE)) == 0
    _press_shift_m(view)
    assert view._legend_visible
    on = view.viewport().grab().toImage()
    # The card sits bottom left and holds a swatch per used entry only.
    corner = on.copy(0, on.height() // 2, on.width() // 2, on.height() // 2)
    assert _count(corner, QColor(HOT)) > 5
    assert _count(on, QColor(SPARE)) == 0
    _press_shift_m(view)
    assert not view._legend_visible
    assert view.viewport().grab().toImage() == off


def test_shift_m_on_a_board_without_palette_colours_says_so(tmp_path: Path):
    view = _view_of(_map(tmp_path, '@ box a "A" 0,0 100x50 %teal\n'))
    view.resize(900, 600)
    off = view.viewport().grab().toImage()
    _press_shift_m(view)
    assert view._toast_text == "No palette colours on this board"
    view._toast_text = ""
    assert view.viewport().grab().toImage() == off


def test_the_side_panel_and_help_sheet_name_the_key():
    from grafli.sidepanel import SidePanel
    from grafli.view.overlays import OverlaysMixin
    assert '("legend",' in inspect.getsource(SidePanel._build_view_section)
    assert ('("\\u21e7M", "Toggle the legend of the map\'s palette'
            in inspect.getsource(OverlaysMixin._show_cheatsheet))


def test_the_side_panel_button_toggles_the_legend(tmp_path: Path):
    _app()
    from grafli.app import MainWindow
    w = MainWindow(str(_map(tmp_path)))
    w._on_tool_activated("legend")
    assert w._view._legend_visible


# ── render and the SVG/PNG exports ────────────────────────────────

def _render(board: Path, out: Path, *flags: str) -> QImage:
    from grafli.app import _cmd_render
    assert _cmd_render([str(board), str(out), *flags]) == 0
    return QImage(str(out))


def test_render_legend_adds_a_band_below_the_board(tmp_path: Path):
    board = _map(tmp_path)
    plain = _render(board, tmp_path / "plain.png")
    with_legend = _render(board, tmp_path / "legend.png", "--legend")
    assert with_legend.width() == plain.width()
    assert with_legend.height() > plain.height()
    board_part = with_legend.copy(0, 0, plain.width(), plain.height())
    band = with_legend.copy(0, plain.height(), with_legend.width(),
                            with_legend.height() - plain.height())
    assert _count(band, QColor(UI)) > 5
    assert _count(band, QColor(CORE)) > 5
    assert _count(band, QColor(HOT)) > 5
    assert _count(band, QColor(SPARE)) == 0
    # The board above the band is the board without the legend.
    assert _count(board_part, QColor(UI)) == _count(plain, QColor(UI))


def test_render_without_the_flag_or_palette_colours_is_unchanged(
        tmp_path: Path):
    board = _map(tmp_path, '#!grafli v4\n@ box a "A" 0,0 200x100 %teal\n')
    plain = _render(board, tmp_path / "plain.png")
    flagged = _render(board, tmp_path / "flagged.png", "--legend")
    assert flagged == plain


def test_render_legend_to_svg_names_the_labels(tmp_path: Path):
    from grafli.app import _cmd_render
    board = _map(tmp_path)
    for name, flags in (("plain", ()), ("legend", ("--legend",))):
        assert _cmd_render([str(board), str(tmp_path / f"{name}.svg"),
                            *flags]) == 0
    plain = (tmp_path / "plain.svg").read_text()
    legend = (tmp_path / "legend.svg").read_text()
    assert "User interface" not in plain
    for label in ("User interface", "Core model", "Hot path"):
        assert label in legend
    assert "Not on the board" not in legend


def test_the_app_png_export_follows_the_toggle(tmp_path: Path):
    view = _view_of(_map(tmp_path))
    plain = view._render_png_image(scale=1)
    view._legend_visible = True
    shown = view._render_png_image(scale=1)
    assert shown.height() > plain.height()
    view._legend_visible = False
    assert view._render_png_image(scale=1) == plain


# ── PDF ───────────────────────────────────────────────────────────

def _export(board: Path, out: Path, *flags: str, monkeypatch) -> list:
    """The legends the PDF export draws, as (rect, labels)."""
    from grafli import pdfexport
    from grafli.app import _cmd_export
    drawn: list = []
    original = pdfexport.draw_legend

    def spy(painter, rect, entries, px, ink=None):
        drawn.append((rect, [e.label for e in entries]))
        original(painter, rect, entries, px, ink)

    monkeypatch.setattr(pdfexport, "draw_legend", spy)
    assert _cmd_export([str(board), str(out), *flags]) == 0
    assert out.read_bytes().startswith(b"%PDF")
    return drawn


def test_export_legend_draws_a_band_on_each_diagram_slide(
        tmp_path: Path, monkeypatch):
    board = _map(tmp_path)
    drawn = _export(board, tmp_path / "deck.pdf", "--legend",
                    monkeypatch=monkeypatch)
    assert [labels for _, labels in drawn] == [
        ["User interface", "Core model", "Hot path"]]
    rect, _ = drawn[0]
    from grafli.pdfexport import _PAGE_PT, _RESOLUTION
    page_h = _PAGE_PT.height() / 72 * _RESOLUTION
    assert rect.top() > page_h * 0.8


def test_export_without_the_flag_draws_no_legend(tmp_path: Path, monkeypatch):
    assert _export(_map(tmp_path), tmp_path / "deck.pdf",
                   monkeypatch=monkeypatch) == []


def test_a_text_slide_has_no_legend(tmp_path: Path, monkeypatch):
    board = _map(tmp_path, BOARD.replace(
        '@ bookmark all "All" @app,fmt\n',
        '@ bookmark all "All" @app,fmt\n@ bookmark txt "" @n\n').replace(
        '@ flow tour "Tour" all\n', '@ flow tour "Tour" all txt\n'))
    drawn = _export(board, tmp_path / "deck.pdf", "--legend",
                    monkeypatch=monkeypatch)
    assert len(drawn) == 1


def test_the_legend_shrinks_the_slide_diagram(tmp_path: Path, monkeypatch):
    """The band is reserved, not drawn over the board: the fitted diagram is
    smaller with the legend on."""
    from PySide6.QtGui import QPainter
    # A tall frame, so the slide fits it by height.
    board = _map(tmp_path, BOARD.replace('@app,fmt', '@app,n'))
    sizes: list = []
    original = QPainter.drawImage

    def spy(self, *args):
        if len(args) == 2 and hasattr(args[0], "height"):
            sizes.append(args[0].height())
        return original(self, *args)

    monkeypatch.setattr(QPainter, "drawImage", spy)
    _export(board, tmp_path / "plain.pdf", monkeypatch=monkeypatch)
    plain = sizes[-1]
    _export(board, tmp_path / "legend.pdf", "--legend",
            monkeypatch=monkeypatch)
    assert sizes[-1] < plain
