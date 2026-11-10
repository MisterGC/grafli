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


# ── Kinds: an entry carries icon, outline, weight and size (#301) ──

PLUGIN = {"color": "%teal", "label": "Plugin", "icon": "lead:puzzle",
          "outline": "dashed", "bold": True, "size": "small"}


def test_an_entry_may_carry_a_kind():
    entries, problems = parse_palette(_palette({
        "plugin": PLUGIN, "tool": {"color": "%primary", "size": 18},
        "plain": {"color": HOT}}))
    assert problems == []
    plugin, tool, plain = entries
    assert (plugin.icon, plugin.outline, plugin.bold, plugin.size) == (
        "lead:puzzle", "dashed", True, "small")
    assert plugin.is_kind and tool.is_kind and tool.size == "18"
    assert not plain.is_kind


def test_a_malformed_kind_is_reported_and_left_out():
    entries, problems = parse_palette(_palette({
        "noicon": {"color": HOT, "icon": "nosuch"},
        "noplace": {"color": HOT, "icon": "side:gear"},
        "wavy": {"color": HOT, "outline": "wavy"},
        "loud": {"color": HOT, "bold": "yes"},
        "huge": {"color": HOT, "size": "huge"},
        "fine": {"color": HOT, "icon": "badge:star", "outline": "dotted"},
    }))
    assert [e.name for e in entries] == ["fine"]
    assert [p.name for p in problems] == [
        "noicon", "noplace", "wavy", "loud", "huge"]
    assert "'nosuch' is not an icon" in problems[0].message


def _kinded(*entries_json) -> None:
    from grafli.map_palette import set_kinds
    set_kinds(parse_palette(_palette(dict(entries_json)))[0])


def test_a_box_of_a_kind_takes_its_icon_outline_weight_and_size():
    from grafli.map_palette import look
    _kinded(("plugin", PLUGIN))
    box = parse('@ box a "A" 0,0 200x100 %plugin\n').boxes[0]
    drawn = look(box)
    assert (drawn.icon, drawn.icon_placement, drawn.border, drawn.emphasis,
            drawn.textsize) == ("puzzle", "lead", "dashed", "bold", "small")
    assert (box.icon, box.border, box.emphasis, box.textsize) == ("", "", "", "")


def test_a_token_on_the_box_wins_over_its_kind():
    from grafli.map_palette import look
    _kinded(("plugin", PLUGIN))
    box = parse('@ box a "A" 0,0 200x100 %plugin ~large !dotted !italic '
                '*badge:star\n').boxes[0]
    drawn = look(box)
    assert (drawn.icon, drawn.icon_placement, drawn.border, drawn.textsize) == (
        "star", "badge", "dotted", "large")
    assert drawn.emphasis == "bold italic"


def test_a_box_without_a_kind_draws_as_written():
    from grafli.map_palette import look
    _kinded(("plugin", PLUGIN), ("plain", {"color": HOT}))
    for line in ('@ box a "A" 0,0 200x100 %plain\n',
                 '@ box a "A" 0,0 200x100 %teal\n',
                 '@ box a "A" 0,0 200x100\n'):
        box = parse(line).boxes[0]
        assert look(box) is box


def test_a_kind_is_not_written_into_the_board():
    _kinded(("plugin", PLUGIN))
    text = '#!grafli v4\n@ box a "A" 0,0 200x100 %plugin\n'
    board = parse(text)
    board.palette_names = frozenset({"plugin"})
    assert serialize(board) == text


def _kind_map(tmp_path: Path, board_text: str, entries: dict) -> Path:
    board = tmp_path / "map.grafli"
    board.write_text(board_text)
    (tmp_path / "map-res").mkdir(exist_ok=True)
    (tmp_path / "map-res" / "palette.json").write_text(_palette(entries))
    return board


def test_the_canvas_draws_a_box_with_its_kind(tmp_path: Path):
    from PySide6.QtCore import Qt
    view = _view_of(_kind_map(
        tmp_path, '#!grafli v4\n@ box a "A" 0,0 240x100 %plugin\n',
        {"plugin": PLUGIN}))
    item = view._box_items["a"]
    assert item.pen().style() == Qt.PenStyle.DashLine
    assert item._has_lead_icon()
    assert item._label.font().bold()
    from grafli.constants import resolve_textsize_px
    assert item.label_px() == resolve_textsize_px("small", "")


def test_a_kind_draws_as_its_tokens_written_out(tmp_path: Path):
    """``%plugin`` draws pixel for pixel what the same tokens on the box
    draw, in the PNG export as on the canvas."""
    kinded = _kind_map(
        tmp_path, '#!grafli v4\n@ box a "Plugin" 0,0 240x100 %plugin\n',
        {"plugin": PLUGIN})
    with_kind = _view_of(kinded)._render_png_image(scale=1)
    written = tmp_path / "written"
    written.mkdir()
    spelled = _kind_map(
        written, '#!grafli v4\n@ box a "Plugin" 0,0 240x100 %plugin ~small '
        '!dashed !bold *lead:puzzle\n',
        {"plugin": {"color": "%teal", "label": "Plugin"}})
    assert with_kind == _view_of(spelled)._render_png_image(scale=1)


def test_the_canvas_keeps_a_token_written_on_the_box(tmp_path: Path):
    from PySide6.QtCore import Qt
    view = _view_of(_kind_map(
        tmp_path, '#!grafli v4\n@ box a "A" 0,0 240x100 %plugin ~large '
        '!dotted *badge:star\n', {"plugin": PLUGIN}))
    item = view._box_items["a"]
    assert item.pen().style() == Qt.PenStyle.DotLine
    assert item._has_badge_icon() and not item._has_lead_icon()
    from grafli.constants import resolve_textsize_px
    assert item.label_px() == resolve_textsize_px("large", "")


def test_recolouring_a_box_to_a_kind_gives_it_the_kind(tmp_path: Path):
    from PySide6.QtCore import Qt
    view = _view_of(_kind_map(
        tmp_path, '#!grafli v4\n@ box a "A" 0,0 240x100 %teal\n',
        {"plugin": PLUGIN}))
    item = view._box_items["a"]
    assert not item._has_lead_icon()
    item.set_color("%plugin")
    assert item.pen().style() == Qt.PenStyle.DashLine
    assert item._has_lead_icon() and item._label.font().bold()
    item.set_color("%teal")
    assert item.pen().style() == Qt.PenStyle.SolidLine
    assert not item._has_lead_icon() and not item._label.font().bold()
    assert view._board.box_by_id("a").icon == ""


def test_the_app_redraws_a_kind_when_the_palette_file_changes(tmp_path: Path):
    from PySide6.QtCore import Qt
    _app()
    board = _kind_map(
        tmp_path, '#!grafli v4\n@ box a "A" 0,0 240x100 %plugin\n',
        {"plugin": {"color": "%teal"}})
    from grafli.app import MainWindow
    w = MainWindow(str(board))
    item = w._view._box_items["a"]
    assert item.pen().style() == Qt.PenStyle.SolidLine
    (tmp_path / "map-res" / "palette.json").write_text(
        _palette({"plugin": PLUGIN}))
    w._on_palette_changed([str(tmp_path / "map-res" / "palette.json")])
    assert item.pen().style() == Qt.PenStyle.DashLine
    assert item._has_lead_icon() and item._label.font().bold()
    assert board.read_text() == '#!grafli v4\n@ box a "A" 0,0 240x100 %plugin\n'


def test_diagnose_warns_about_a_malformed_kind(tmp_path: Path):
    root, _ = _map(tmp_path)
    (tmp_path / "map-res" / "palette.json").write_text(_palette({
        "storage": {"color": HOT, "outline": "wavy"}}))
    code, findings = _diagnose(root)
    bad = [f for f in findings if f["code"] == "bad-palette"]
    assert len(bad) == 1 and bad[0]["severity"] == "warning"
    assert "'outline' must be" in bad[0]["message"]


# ── Style mode `s` `c` ─────────────────────────────────────────────

def _picker(tmp_path: Path, box_id: str = "items") -> GrafliView:
    root, _ = _map(tmp_path, HOT)
    vault = tmp_path / "map-res"
    (vault / "palette.json").write_text(_palette({
        "storage": {"color": HOT, "label": "Persistence"},
        "ui": {"color": "%plum", "label": "Interface"}}))
    view = _view_of(root)
    view.resize(900, 600)
    view._box_items[box_id].setSelected(True)
    return view


def test_the_colour_grid_lists_the_palette_entries(tmp_path: Path):
    from grafli.constants import COLOR_PALETTE
    view = _picker(tmp_path)
    choices = view._color_choices()
    assert choices[:len(COLOR_PALETTE)] == list(COLOR_PALETTE)
    assert choices[len(COLOR_PALETTE):] == [
        ("Persistence", "%storage"), ("Interface", "%ui")]


def test_the_grid_without_a_palette_is_the_theme_tokens(tmp_path: Path):
    from grafli.constants import COLOR_PALETTE
    board = tmp_path / "plain.grafli"
    board.write_text(ROOT)
    assert _view_of(board)._color_choices() == list(COLOR_PALETTE)


def test_the_grid_opens_on_a_box_palette_entry(tmp_path: Path):
    view = _picker(tmp_path, "view")
    view._open_color_picker()
    assert view._color_choices()[view._color_picker_index][1] == "%storage"


def test_picking_a_palette_entry_colours_the_box_and_writes_v4(tmp_path: Path):
    view = _picker(tmp_path)
    view._open_color_picker()
    for _ in range(4):
        view._color_picker_move(0, 1)            # j past the theme rows
    view._color_picker_move(1, 0)                # l -> the second entry
    assert view._color_choices()[view._color_picker_index][1] == "%ui"
    view._commit_color_picker()
    assert view._board.box_by_id("items").color == "%ui"
    assert _fill(view, "items") == QColor(theme.resolve_color("%plum"))
    assert serialize(view._board).splitlines()[0] == "#!grafli v4"


def test_the_grid_skips_the_gap_before_the_palette_rows(tmp_path: Path,
                                                         monkeypatch):
    from grafli.constants import COLOR_PALETTE
    from grafli.view import style_mode
    monkeypatch.setattr(style_mode, "COLOR_PALETTE", COLOR_PALETTE[:13])
    view = _picker(tmp_path)
    choices = view._color_choices()
    assert choices[13:15] == [("", None), ("", None)]
    view._open_color_picker()
    view._color_picker_move(4, 0)                # l to the row's end
    view._color_picker_move(0, 2)                # j onto the last token row
    assert view._color_picker_index == 12
    view._color_picker_move(0, 1)
    assert choices[view._color_picker_index][1] == "%ui"


def test_the_help_sheet_names_the_palette_in_the_grid():
    import inspect
    from grafli.view.overlays import OverlaysMixin
    source = inspect.getsource(OverlaysMixin._show_cheatsheet)
    assert '("  c", "Color grid, then the map palette\'s %names' in source


def _key(view: GrafliView, key) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    view._handle_color_picker_key(
        QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _kind_picker(tmp_path: Path) -> GrafliView:
    view = _picker(tmp_path)
    (tmp_path / "map-res" / "palette.json").write_text(_palette({
        "storage": {"color": HOT, "label": "Persistence"},
        "plugin": PLUGIN}))
    view.load_map_palette()
    return view


def test_a_digit_in_the_grid_applies_that_kind_at_once(tmp_path: Path):
    from PySide6.QtCore import Qt
    view = _kind_picker(tmp_path)
    item = view._box_items["items"]
    view._open_color_picker()
    _key(view, Qt.Key.Key_2)
    assert not view._color_picker_active
    assert view._board.box_by_id("items").color == "%plugin"
    assert item.pen().style() == Qt.PenStyle.DashLine
    assert item._has_lead_icon() and item._label.font().bold()
    view._undo()
    assert view._board.box_by_id("items").color == "%primary"


def test_a_digit_past_the_palette_leaves_the_grid_open(tmp_path: Path):
    from PySide6.QtCore import Qt
    view = _kind_picker(tmp_path)
    toasts = []
    view.toast = lambda msg, *a, **k: toasts.append(msg)
    view._open_color_picker()
    _key(view, Qt.Key.Key_3)
    assert view._color_picker_active
    assert view._board.box_by_id("items").color == "%primary"
    assert toasts == ["The map's palette has no entry 3"]


def test_the_grid_names_the_digit_of_a_palette_entry(tmp_path: Path):
    view = _kind_picker(tmp_path)
    view._open_color_picker()
    entries = {"%storage": (1, None), "%plugin": (2, None)}
    assert view._color_picker_caption(entries) == "Primary"
    values = [v for _, v in view._color_choices()]
    view._color_picker_index = values.index("%plugin")
    assert view._color_picker_caption(entries) == "2  Plugin"


def test_the_grid_draws_a_kind_swatch_with_its_icon(tmp_path: Path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter
    view = _kind_picker(tmp_path)
    view._open_color_picker()

    def grid() -> QImage:
        img = QImage(900, 600, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.white)
        painter = QPainter(img)
        view._draw_color_picker(painter)
        painter.end()
        return img

    with_kind = grid()
    (tmp_path / "map-res" / "palette.json").write_text(_palette({
        "storage": {"color": HOT, "label": "Persistence"},
        "plugin": {"color": "%teal", "label": "Plugin"}}))
    view.load_map_palette()
    assert grid() != with_kind
