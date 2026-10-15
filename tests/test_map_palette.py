"""One palette per map (#213): ``<stem>-res/palette.json`` names colours, a
box uses ``%name``, and every board of the map resolves it against the same
file. A board that uses no palette name renders as before.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from grafli import format as fmt
from grafli import theme
from grafli.format import (is_newer, parse, required_version, serialize,
                           supported_version)
from grafli.map_palette import (candidate_paths, load_palette, palette_path,
                                parse_palette)
from grafli.view import GrafliView

ROOT = ('#!grafli v4\n'
        '@ box view "View" 0,0 200x100 %storage &graph:detail\n'
        '@ box items "Items" 300,0 200x100 %primary\n')
DETAIL = ('#!grafli v4\n'
          '@ box store "Store" 0,0 200x100 %storage\n')
HOT = "#C0392B"
COLD = "#2471A3"


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _palette(entries: dict) -> str:
    return json.dumps({"entries": entries}, indent=2)


def _map(tmp_path: Path, color: str = "%teal") -> tuple[Path, Path]:
    """A map: ``map.grafli`` with a sub-board ``detail`` in its vault, both
    colouring a box ``%storage``, and the palette that names it."""
    root = tmp_path / "map.grafli"
    root.write_text(ROOT)
    vault = tmp_path / "map-res"
    vault.mkdir()
    detail = vault / "detail.grafli"
    detail.write_text(DETAIL)
    _write_palette(tmp_path, color)
    return root, detail


def _write_palette(tmp_path: Path, color: str) -> None:
    (tmp_path / "map-res" / "palette.json").write_text(
        _palette({"storage": {"color": color, "label": "Persistence"}}))


def _view_of(path: Path) -> GrafliView:
    _app()
    view = GrafliView()
    view.render_headless(path)
    view.load_board(parse(path.read_text()))
    return view


def _fill(view: GrafliView, box_id: str) -> QColor:
    return view._box_items[box_id].brush().color()


def _share(img: QImage, color: QColor) -> float:
    """Fraction of *img*'s pixels within a few levels of *color*."""
    hits = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            p = img.pixelColor(x, y)
            if (abs(p.red() - color.red()) <= 6
                    and abs(p.green() - color.green()) <= 6
                    and abs(p.blue() - color.blue()) <= 6):
                hits += 1
    return hits / max(1, (img.width() // 2) * (img.height() // 2))


# ── The file and where it lives ───────────────────────────────────

def test_both_boards_of_a_map_find_the_same_palette(tmp_path: Path):
    root, detail = _map(tmp_path)
    assert palette_path(root) == palette_path(detail)
    assert palette_path(root) == (tmp_path / "map-res" / "palette.json").resolve()


def test_the_outermost_palette_of_a_map_wins(tmp_path: Path):
    root, detail = _map(tmp_path)
    own = tmp_path / "map-res" / "detail-res"
    own.mkdir()
    (own / "palette.json").write_text(_palette({"storage": {"color": HOT}}))
    assert palette_path(detail) == palette_path(root)
    assert candidate_paths(detail)[-1] == (own / "palette.json").resolve()


def test_a_board_without_a_palette_has_none(tmp_path: Path):
    board = tmp_path / "plain.grafli"
    board.write_text(ROOT)
    assert palette_path(board) is None
    assert load_palette(board) == []
    assert load_palette(None) == []


def test_an_entry_names_a_theme_token_or_a_hex_and_a_label():
    entries, problems = parse_palette(_palette({
        "storage": {"color": "%teal", "label": "Persistence"},
        "hot": {"color": HOT},
    }))
    assert problems == []
    assert [(e.name, e.color, e.label) for e in entries] == [
        ("storage", "%teal", "Persistence"), ("hot", HOT, "Hot")]


def test_a_name_that_shadows_a_theme_token_is_left_out():
    entries, problems = parse_palette(_palette({
        "teal": {"color": HOT}, "hot": {"color": HOT}}))
    assert [e.name for e in entries] == ["hot"]
    assert [(p.name, p.shadows) for p in problems] == [("teal", True)]


def test_malformed_entries_are_reported_and_left_out():
    entries, problems = parse_palette(_palette({
        "Bad-Name": {"color": HOT},
        "nocolor": {"label": "x"},
        "loop": {"color": "%storage"},
        "fine": {"color": "%plum"},
    }))
    assert [e.name for e in entries] == ["fine"]
    assert [p.name for p in problems] == ["Bad-Name", "nocolor", "loop"]
    assert parse_palette("{")[1][0].message.startswith("not JSON")
    assert parse_palette("[]")[1][0].message == "needs an 'entries' object"


def test_the_theme_token_names_match_the_themes():
    assert set(theme.LIGHT.COLOR_TOKENS) == fmt.THEME_COLOR_TOKENS
    assert set(theme.DARK.COLOR_TOKENS) == fmt.THEME_COLOR_TOKENS


# ── Resolving %name ───────────────────────────────────────────────

def test_a_palette_name_resolves_through_its_entry():
    theme.set_map_palette({"storage": "%teal", "hot": HOT})
    assert theme.resolve_color("%storage") == theme.resolve_color("%teal")
    assert theme.resolve_color("%hot") == HOT
    assert theme.resolve_color("%nosuch") == ""


def test_a_token_entry_follows_the_theme():
    theme.set_map_palette({"storage": "%teal"})
    light = theme.resolve_color("%storage")
    theme.set_theme("dark")
    assert theme.resolve_color("%storage") == theme.DARK.COLOR_TOKENS["teal"]
    assert theme.resolve_color("%storage") != light


def test_both_boards_of_a_map_colour_a_box_from_the_palette(tmp_path: Path):
    root, detail = _map(tmp_path, HOT)
    assert _fill(_view_of(root), "view") == QColor(HOT)
    assert _fill(_view_of(detail), "store") == QColor(HOT)


def test_changing_an_entry_recolours_both_boards(tmp_path: Path):
    root, detail = _map(tmp_path, HOT)
    _write_palette(tmp_path, COLD)
    assert _fill(_view_of(root), "view") == QColor(COLD)
    assert _fill(_view_of(detail), "store") == QColor(COLD)


def test_a_board_without_a_palette_name_renders_the_same(tmp_path: Path):
    """The palette changes nothing on a board that does not use it."""
    _app()
    plain = ('#!grafli v1\n@ box a "A" 0,0 200x100 %primary\n'
             '@ box b "B" 300,0 200x100\n')
    board = tmp_path / "map.grafli"
    board.write_text(plain)
    without = _view_of(board)._render_png_image(scale=1)
    (tmp_path / "map-res").mkdir()
    _write_palette(tmp_path, HOT)
    with_palette = _view_of(board)._render_png_image(scale=1)
    assert with_palette == without


def test_a_miniature_renderer_leaves_the_palette_alone(tmp_path: Path):
    root, _ = _map(tmp_path, HOT)
    _view_of(root)
    _app()
    GrafliView().load_board(parse(ROOT))
    assert theme.resolve_color("%storage") == HOT


# ── App, render and exports ───────────────────────────────────────

def _render(board: Path, out: Path) -> QImage:
    from grafli.app import _cmd_render
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_both_boards_in_the_entry_colour(tmp_path: Path):
    root, detail = _map(tmp_path, HOT)
    for board in (root, detail):
        img = _render(board, tmp_path / f"{board.stem}-hot.png")
        assert _share(img, QColor(HOT)) > 0.05
    _write_palette(tmp_path, COLD)
    for board in (root, detail):
        img = _render(board, tmp_path / f"{board.stem}-cold.png")
        assert _share(img, QColor(HOT)) == 0
        assert _share(img, QColor(COLD)) > 0.05


def _pdf_raster(board: Path, out: Path) -> QImage:
    """The board raster the PDF export paints for the flow's one stop."""
    from grafli.pdfexport import export_flow_to_pdf
    view = _view_of(board)
    shots: list[QImage] = []
    scene = view._scene
    original = scene.render

    def capture(painter, target, source, *args):
        original(painter, target, source, *args)
        shots.append(QImage(painter.device()))

    scene.render = capture
    try:
        export_flow_to_pdf(view, view._board.flow_by_id("tour"), out)
    finally:
        del scene.render
    assert out.read_bytes().startswith(b"%PDF")
    assert len(shots) == 1
    return shots[0]


def test_the_pdf_export_draws_the_entry_colour(tmp_path: Path):
    root, detail = _map(tmp_path, HOT)
    detail.write_text(DETAIL + '@ bookmark bm "Store" @store\n'
                      '@ flow tour "Tour" bm\n')
    hot = _pdf_raster(detail, tmp_path / "hot.pdf")
    assert _share(hot, QColor(HOT)) > 0.01
    _write_palette(tmp_path, COLD)
    cold = _pdf_raster(detail, tmp_path / "cold.pdf")
    assert _share(cold, QColor(HOT)) == 0
    assert _share(cold, QColor(COLD)) > 0.01


def test_the_app_recolours_when_the_palette_file_changes(tmp_path: Path):
    _app()
    root, _ = _map(tmp_path, HOT)
    from grafli.app import MainWindow
    w = MainWindow(str(root))
    assert w._palette_watcher is not None
    assert _fill(w._view, "view") == QColor(HOT)
    _write_palette(tmp_path, COLD)
    w._on_palette_changed([str(tmp_path / "map-res" / "palette.json")])
    assert _fill(w._view, "view") == QColor(COLD)


# ── Version gate ──────────────────────────────────────────────────

def _with_palette(text: str) -> fmt.Board:
    board = parse(text)
    board.palette_names = frozenset({"storage"})
    return board


def test_a_palette_name_writes_v4():
    board = _with_palette(ROOT)
    assert required_version(board) == 4
    assert serialize(board) == ROOT


def test_theme_tokens_alone_stay_below_v4():
    board = _with_palette(ROOT.replace("%storage", "%teal").replace("v4", "v1"))
    assert required_version(board) == 1
    board.box_by_id("items").status = "open"
    board.box_by_id("items").status_color = "%storage"
    assert required_version(board) == 4


def test_an_unknown_name_outside_the_palette_stays_below_v4():
    """A typo is no palette entry: an existing board keeps its header."""
    board = _with_palette(ROOT.replace("%storage", "%red").replace("v4", "v1"))
    assert required_version(board) == 1


def test_the_view_tells_the_board_its_palette_names(tmp_path: Path):
    root, _ = _map(tmp_path)
    assert _view_of(root)._board.palette_names == {"storage"}


def test_fmt_keeps_a_palette_board_on_v4(tmp_path: Path):
    from grafli.app import _cmd_fmt
    root, detail = _map(tmp_path)
    assert _cmd_fmt([str(root), str(detail)]) == 0
    assert root.read_text() == ROOT
    assert detail.read_text() == DETAIL


def test_a_v3_build_reads_a_palette_board_as_newer(monkeypatch):
    features = {k: v for k, v in fmt.VERSION_FEATURES.items() if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    assert supported_version() == 3
    assert is_newer(parse(ROOT))


# ── diagnose ──────────────────────────────────────────────────────

def _diagnose(path: Path) -> tuple[int, list[dict]]:
    import contextlib
    import io
    from grafli.app import _cmd_diagnose
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = _cmd_diagnose([str(path), "--json"])
    return code, json.loads(out.getvalue())


def test_diagnose_knows_the_palette_names(tmp_path: Path):
    root, detail = _map(tmp_path)
    for board in (root, detail):
        code, findings = _diagnose(board)
        assert code == 0
        assert [f for f in findings if f["code"] == "unknown-color"] == []


def test_diagnose_flags_a_name_outside_the_palette(tmp_path: Path):
    root, _ = _map(tmp_path)
    root.write_text(ROOT.replace("%storage", "%storag"))
    code, findings = _diagnose(root)
    unknown = [f for f in findings if f["code"] == "unknown-color"]
    assert len(unknown) == 1
    assert "did you mean %storage?" in unknown[0]["message"]


def test_diagnose_reports_a_name_that_shadows_a_theme_token(tmp_path: Path):
    root, _ = _map(tmp_path)
    (tmp_path / "map-res" / "palette.json").write_text(_palette({
        "storage": {"color": HOT}, "teal": {"color": COLD}}))
    code, findings = _diagnose(root)
    assert code == 1
    shadow = [f for f in findings if f["code"] == "palette-shadows-token"]
    assert len(shadow) == 1
    assert shadow[0]["severity"] == "error"
    assert shadow[0]["item_ids"] == ["teal"]
    assert "%teal shadows the theme token %teal" in shadow[0]["message"]


def test_diagnose_warns_about_a_palette_it_cannot_read(tmp_path: Path):
    root, _ = _map(tmp_path)
    (tmp_path / "map-res" / "palette.json").write_text("{ nope")
    code, findings = _diagnose(root)
    bad = [f for f in findings if f["code"] == "bad-palette"]
    assert len(bad) == 1 and bad[0]["severity"] == "warning"
    assert bad[0]["message"].startswith("map-res/palette.json: not JSON")
