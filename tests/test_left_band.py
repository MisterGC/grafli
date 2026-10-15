"""`^left` (#212): a container whose title sits top left at full zoom and,
zoomed out, stays a band with a strip of its children's colours and its
title on the left edge. Containers without it collapse exactly as before.
"""

from __future__ import annotations

import inspect
import os
from collections import Counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from grafli import format as fmt
from grafli import theme
from grafli.format import (is_newer, parse, required_version, serialize,
                           supported_version)
from grafli.view import GrafliView, Mode

# Wide enough that `render --lod` (fitted to 1280 px) folds the children.
BAND = ('#!grafli v4\n'
        '@ box ui "UI layer" 0,0 4000x240 %muted ^left ~large !flat\n'
        '@ box app "App window" 40,70 900x140 %secondary >ui\n'
        '@ box side "Side panel" 1020,70 900x140 %secondary >ui\n'
        '@ box style "Style mode" 2000,70 900x140 %plum >ui\n'
        '@ box flows "Flows panel" 2980,70 900x140 %plum >ui\n'
        '@ box core "Core" 0,300 4000x240 %muted ^left ~large !flat\n'
        '@ box view "View" 40,370 900x140 %tertiary >core\n'
        '@ box items "Items" 1020,370 900x140 %tertiary >core\n'
        '@ box lod "Level of detail" 2000,370 900x140 %accent >core\n'
        '@ box layout "Layout" 2980,370 900x140 %accent >core\n')
TOPLEFT = BAND.replace("^left", "^topleft").replace("v4", "v1", 1)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str) -> GrafliView:
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


# ── Format and version gate ───────────────────────────────────────

def test_left_round_trips_and_writes_v4():
    board = parse(BAND)
    assert board.box_by_id("ui").anchor == "left"
    assert required_version(board) == 4
    assert serialize(board) == BAND


def test_left_on_a_v1_board_lifts_it_to_v4():
    board = parse(TOPLEFT)
    assert required_version(board) == 1
    board.box_by_id("ui").anchor = "left"
    assert serialize(board).splitlines()[0] == "#!grafli v4"


def test_a_v3_build_reads_a_left_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items() if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(BAND))


def test_the_box_form_names_left():
    assert "^left" in fmt.BOX_FORM


# ── Full zoom: a top-left heading ─────────────────────────────────

def test_at_full_zoom_the_title_sits_where_topleft_puts_it():
    # Hold the views: a dropped view takes its scene items with it.
    left_view, top_view = _view(BAND), _view(TOPLEFT)
    left = left_view._box_items["ui"]
    top = top_view._box_items["ui"]
    assert left._get_effective_anchor() == "topleft"
    assert left._label.pos() == top._label.pos()
    assert left._lod_tile is None


# ── Zoomed out: the band ──────────────────────────────────────────

def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out), "--lod"]) == 0
    return QImage(str(out))


def _near(a: QColor, b: QColor, tol: int = 6) -> bool:
    return (abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol
            and abs(a.blue() - b.blue()) <= tol)


def _share(img: QImage, color: QColor, x0: float, x1: float,
           y0: float, y1: float, tol: int = 6) -> float:
    """Fraction of pixels near *color* in a region given as fractions."""
    hits = total = 0
    for x in range(int(img.width() * x0), int(img.width() * x1), 3):
        for y in range(int(img.height() * y0), int(img.height() * y1), 3):
            total += 1
            hits += _near(img.pixelColor(x, y), color, tol)
    return hits / max(total, 1)


def test_a_collapsed_left_band_carries_its_children_colours():
    view = _view(BAND)
    view._present_detail = "summary"
    view._refresh_lod()
    ui = view._box_items["ui"]
    assert ui._lod_tile == ("UI layer", 4)
    colours = [QColor.fromRgba(rgba) for _, _, rgba in ui._lod_strip]
    secondary = QColor(theme.resolve_color("%secondary"))
    plum = QColor(theme.resolve_color("%plum"))
    assert [c.name() for c in colours] == [secondary.name()] * 2 + \
        [plum.name()] * 2
    # Each segment sits where its child sits across the band.
    x0, x1, _ = ui._lod_strip[0]
    assert (x0, x1) == (40 / 4000, 940 / 4000)


def test_a_collapsed_topleft_container_has_no_strip():
    view = _view(TOPLEFT)
    view._present_detail = "summary"
    view._refresh_lod()
    assert view._box_items["ui"]._lod_tile == ("UI layer", 4)
    assert view._box_items["ui"]._lod_strip == ()


def test_render_lod_shows_the_band_colours_and_a_left_title(tmp_path: Path):
    _app()
    band = _render(tmp_path, "band", BAND)
    plain = _render(tmp_path, "plain", TOPLEFT)
    secondary = QColor(theme.resolve_color("%secondary"))
    tertiary = QColor(theme.resolve_color("%tertiary"))
    # The plate is the paper surface at 85 % over the tile, whose grey is
    # the commonest colour mid-board in the plain render.
    tile = QColor(Counter(
        plain.pixelColor(x, y).rgb()
        for x in range(plain.width() // 3, 2 * plain.width() // 3, 7)
        for y in range(0, plain.height(), 7)).most_common(1)[0][0])
    surface = QColor(theme.SURFACE)
    plate = QColor(*(round(0.85 * s + 0.15 * t) for s, t in (
        (surface.red(), tile.red()), (surface.green(), tile.green()),
        (surface.blue(), tile.blue()))))
    # The children's colours show in the band, and not in the grey tile.
    assert _share(band, secondary, 0.0, 0.5, 0.0, 0.5) > 0.05
    assert _share(band, tertiary, 0.0, 0.5, 0.5, 1.0) > 0.05
    assert _share(plain, secondary, 0.0, 1.0, 0.0, 1.0) == 0.0
    # The title plate sits on the left, not in the middle as without it.
    assert _share(band, plate, 0.0, 0.15, 0.0, 1.0, 3) > 0.02
    assert _share(band, plate, 0.4, 0.6, 0.0, 1.0, 3) == 0.0
    assert _share(plain, plate, 0.4, 0.6, 0.0, 1.0, 3) > 0.02


# ── Style mode `s` `e` ────────────────────────────────────────────

def test_the_label_row_reaches_left():
    view = _view('#!grafli v1\n@ box l "Domain layer" 0,0 700x110\n')
    view.resize(900, 600)
    view._mode = Mode.SELECT
    view._box_items["l"].setSelected(True)
    view._open_element_overlay()
    row = next(i for i, a in enumerate(view._elem_overlay_axes)
               if a["label"] == "Label")
    assert ("Left", "left") in view._elem_overlay_axes[row]["options"]
    view._elem_overlay_row = row
    for _ in range(3):                          # Center -> ... -> Left
        view._elem_overlay_cycle(1)
    view._commit_element_overlay()
    assert view.board.box_by_id("l").anchor == "left"
    out = serialize(view.board)
    assert out.startswith("#!grafli v4\n")
    assert '@ box l "Domain layer" 0,0 700x110 ^left' in out


def test_the_help_sheet_names_the_band():
    from grafli.view.overlays import OverlaysMixin
    source = inspect.getsource(OverlaysMixin._show_cheatsheet)
    assert "label spot (left: a band zoomed out)" in source
