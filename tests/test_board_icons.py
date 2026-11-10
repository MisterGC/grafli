"""A board's own SVG icons in ``<stem>-res/icons/`` work as ``*name`` like
the built-in symbols (issue #299): listed and tinted by the iconset, drawn
in every placement on the canvas, in ``grafli render`` and the exports,
offered by the symbol grid and known to ``diagnose``."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli import iconset, theme
from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# A filled square: an unset fill draws in the tint.
SQUARE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
          '<rect x="2" y="2" width="20" height="20"/></svg>')
# A stroked outline in currentColor, wider than tall.
SCREEN = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 24" '
          'fill="none" stroke="currentColor" stroke-width="3">'
          '<rect x="2" y="2" width="44" height="20"/></svg>')


def _app():
    return QApplication.instance() or QApplication([])


def _board(tmp_path: Path, text: str, icons: dict[str, str] | None = None,
           stem: str = "board") -> Path:
    path = tmp_path / f"{stem}.grafli"
    path.write_text("#!grafli v4\n" + text, encoding="utf-8")
    if icons:
        folder = iconset.board_icon_dir(path)
        folder.mkdir(parents=True)
        for name, svg in icons.items():
            (folder / name).write_text(svg, encoding="utf-8")
    return path


def _view(path: Path) -> GrafliView:
    _app()
    view = GrafliView()
    view.render_headless(path)
    view.load_board(parse(path.read_text(encoding="utf-8")))
    view.resize(900, 600)
    view._mode = Mode.SELECT
    return view


def _ink_pixels(img: QImage, ink: QColor) -> int:
    """How many pixels of *img* are within a few steps of *ink*."""
    count = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - ink.red()) + abs(c.green() - ink.green())
                    + abs(c.blue() - ink.blue())) < 24:
                count += 1
    return count


def _paint(name: str, icons, color: QColor, size: int = 40) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    iconset.paint_icon(p, name, QRectF(0, 0, size, size), color, icons)
    p.end()
    return img


# ── the folder ──────────────────────────────────────────────────

def test_the_folder_lists_its_svgs_by_name(tmp_path):
    path = _board(tmp_path, "", {
        "monitor.svg": SQUARE, "game-pad.svg": SQUARE, "phone2.svg": SQUARE,
        "Upper.svg": SQUARE, "under_score.svg": SQUARE, "7.svg": SQUARE,
        "solid-3.svg": SQUARE, "notes.txt": "x"})
    icons = iconset.BoardIcons.of(path)
    # A name a `*name` token can't spell, or a number badge's, is no icon.
    assert icons.names() == ["game-pad", "monitor", "phone2"]
    assert "monitor" in icons and "Upper" not in icons


def test_a_built_in_name_wins_over_the_folder(tmp_path):
    path = _board(tmp_path, "", {"gear.svg": SQUARE, "own.svg": SQUARE})
    icons = iconset.BoardIcons.of(path)
    assert icons.names() == ["own"]
    assert icons.path("gear") is None
    assert iconset.resolve_icon("gear", icons) == "gear"


def test_a_board_without_a_file_or_folder_has_no_icons(tmp_path):
    assert iconset.BoardIcons.of(None) is None
    icons = iconset.BoardIcons.of(_board(tmp_path, ""))
    assert icons.names() == [] and "monitor" not in icons


def test_an_icon_added_later_is_found(tmp_path):
    path = _board(tmp_path, "")
    icons = iconset.BoardIcons.of(path)
    assert "monitor" not in icons
    folder = iconset.board_icon_dir(path)
    folder.mkdir(parents=True)
    (folder / "monitor.svg").write_text(SQUARE, encoding="utf-8")
    assert "monitor" in icons


def test_names_resolve_only_with_the_boards_icons(tmp_path):
    path = _board(tmp_path, "", {"monitor.svg": SQUARE})
    icons = iconset.BoardIcons.of(path)
    assert not iconset.has_icon("monitor")
    assert iconset.has_icon("monitor", icons)
    assert iconset.resolve_icon("monitor", icons) == "monitor"
    assert iconset.number_badge("monitor") is None


# ── tinting ─────────────────────────────────────────────────────

def test_tint_takes_current_color_black_and_an_unset_fill():
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4">'
           b'<path stroke="currentColor" fill="#000"/>'
           b'<path style="fill:black;stroke:#000000"/>'
           b'<circle fill="#ff8800"/></svg>')
    out = iconset.tint_svg(svg, "#123456").decode()
    assert 'stroke="#123456" fill="#123456"' in out
    assert "fill:#123456;stroke:#123456" in out
    assert 'fill="#ff8800"' in out              # another colour stays
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg" '
                          'viewBox="0 0 4 4" fill="#123456" color="#123456">')


def test_tint_leaves_a_set_root_fill_alone():
    out = iconset.tint_svg(SCREEN.encode(), "#123456").decode()
    assert 'fill="none"' in out and out.count("fill=") == 1
    assert 'stroke="#123456"' in out


def test_an_icon_paints_in_the_colour_it_is_given(tmp_path):
    _app()
    icons = iconset.BoardIcons.of(_board(tmp_path, "", {"block.svg": SQUARE}))
    red, blue = QColor("#d02020"), QColor("#2040d0")
    assert _ink_pixels(_paint("block", icons, red), red) > 600
    assert _ink_pixels(_paint("block", icons, blue), blue) > 600
    assert _ink_pixels(_paint("block", None, red), red) == 0


def test_the_aspect_comes_from_the_view_box(tmp_path):
    _app()
    icons = iconset.BoardIcons.of(_board(tmp_path, "", {"screen.svg": SCREEN}))
    assert iconset.icon_aspect("screen", icons) == 2.0
    assert iconset.icon_aspect("screen") == 1.0


def test_the_pixmap_is_rendered_again_when_the_file_changes(tmp_path):
    _app()
    path = _board(tmp_path, "", {"block.svg": SQUARE})
    icons = iconset.BoardIcons.of(path)
    ink = QColor("#d02020")
    full = iconset.icon_pixmap("block", ink, 30, 1.0, icons).toImage()
    svg = iconset.board_icon_dir(path) / "block.svg"
    svg.write_text(SQUARE.replace('width="20"', 'width="4"'), "utf-8")
    os.utime(svg, ns=(svg.stat().st_atime_ns, svg.stat().st_mtime_ns + 10**9))
    thin = iconset.icon_pixmap("block", ink, 30, 1.0, icons).toImage()
    assert _ink_pixels(thin, ink) < _ink_pixels(full, ink)


# ── the canvas ──────────────────────────────────────────────────

ALL_PLACES = ('@ box fill "" 0,0 160x160 *monitor\n'
              '@ box lead "Lead" 200,0 200x60 *lead:monitor\n'
              '@ box badge "Badge" 200,100 200x60 *badge:monitor\n'
              '@ note n 0,200 "lead note" *lead:monitor\n'
              '@ note m 200,200 *monitor\n'
              '@ note b 400,200 "badge note" *badge:monitor\n')


def test_every_placement_resolves_on_the_canvas(tmp_path):
    view = _view(_board(tmp_path, ALL_PLACES, {"monitor.svg": SQUARE}))
    boxes, notes = view._box_items, view._note_items
    assert boxes["lead"]._has_lead_icon()
    assert boxes["badge"]._has_badge_icon()
    assert notes["n"]._is_marker_icon() and notes["m"]._is_marker_icon()
    assert notes["b"]._has_badge_icon()


def test_without_the_folder_the_names_stay_unknown(tmp_path):
    view = _view(_board(tmp_path, ALL_PLACES))
    assert not view._box_items["lead"]._has_lead_icon()
    assert not view._note_items["n"]._is_marker_icon()


def test_a_lead_icon_reserves_room_for_its_shape(tmp_path):
    view = _view(_board(tmp_path, '@ box a "Wide" 0,0 240x60 *lead:screen\n',
                        {"screen.svg": SCREEN}))
    item = view._box_items["a"]
    assert item._lead_icon_w() == item._lead_icon_side() * 1.6


def test_a_box_made_later_lays_out_around_its_icon(tmp_path):
    from grafli.format import Box
    from grafli.items import BoxItem
    view = _view(_board(tmp_path, "", {"monitor.svg": SQUARE}))
    box = Box(id="x", label="Late", x=0, y=0, w=200, h=60,
              icon="monitor", icon_placement="lead")
    item = BoxItem(box)
    assert not item._has_lead_icon()      # no scene, no board icons yet
    view._scene.addItem(item)
    assert item._has_lead_icon()
    assert item._label.textWidth() == 200 - (item._lead_icon_w() + 24.0)


def test_a_miniature_view_reads_the_sub_boards_icons(tmp_path):
    sub = _board(tmp_path, '@ box a "" 0,0 100x100 *chip\n',
                 {"chip.svg": SQUARE}, stem="sub")
    _app()
    view = GrafliView()
    view.load_board(parse(sub.read_text(encoding="utf-8")), board_file=sub)
    assert "chip" in view._scene.board_icons
    item = view._box_items["a"]
    assert iconset.has_icon(item.look.icon, view._scene.board_icons)


# ── render and exports ──────────────────────────────────────────

def _render(path: Path) -> QImage:
    from grafli.app import _cmd_render
    out = path.with_suffix(".png")
    assert _cmd_render([str(path), str(out)]) == 0
    return QImage(str(out))


def test_grafli_render_draws_the_icon_in_the_board_ink(tmp_path):
    _app()
    text = '@ box a "" 0,0 160x160 *block\n'
    (tmp_path / "with").mkdir()
    (tmp_path / "bare").mkdir()
    drawn = _render(_board(tmp_path / "with", text, {"block.svg": SQUARE}))
    bare = _render(_board(tmp_path / "bare", text))
    ink = QColor(theme.INK)
    assert drawn.size() == bare.size()
    assert _ink_pixels(drawn, ink) > _ink_pixels(bare, ink) + 2000


def test_grafli_render_tints_an_ink_box_icon(tmp_path):
    _app()
    text = '@ box a "" 0,0 160x160 #203040 !ink *block\n'
    img = _render(_board(tmp_path, text, {"block.svg": SQUARE}))
    on_fill = theme.ink_on(QColor("#203040"))
    assert _ink_pixels(img, on_fill) > 2000


def test_the_svg_export_carries_the_icon(tmp_path):
    text = '@ box a "" 0,0 160x160 *block\n'
    (tmp_path / "with").mkdir()
    (tmp_path / "bare").mkdir()
    drawn = bytes(_view(_board(tmp_path / "with", text, {"block.svg": SQUARE}))
                  ._render_svg_bytes()).decode()
    bare = bytes(_view(_board(tmp_path / "bare", text))
                 ._render_svg_bytes()).decode()
    assert len(drawn) > len(bare)
    assert QColor(theme.INK).name() in drawn


def test_the_html_export_carries_the_icon(tmp_path):
    from grafli.htmlexport import export_html
    _app()
    text = '@ box a "" 0,0 160x160 *block\n'
    (tmp_path / "with").mkdir()
    (tmp_path / "bare").mkdir()
    with_path = _board(tmp_path / "with", text, {"block.svg": SQUARE})
    bare_path = _board(tmp_path / "bare", text)
    drawn = export_html(with_path, tmp_path / "with.html").path.read_text()
    bare = export_html(bare_path, tmp_path / "bare.html").path.read_text()
    assert len(drawn) > len(bare)


def test_the_pdf_export_draws_the_icon(tmp_path):
    from grafli.pdfexport import export_flow_to_pdf
    text = ('@ box a "" 0,0 160x160 *block\n'
            '@ bookmark bm "A" @a\n@ flow tour "Tour" bm\n')
    (tmp_path / "with").mkdir()
    (tmp_path / "bare").mkdir()
    shots = []
    for path in (_board(tmp_path / "with", text, {"block.svg": SQUARE}),
                 _board(tmp_path / "bare", text)):
        view = _view(path)
        scene = view._scene
        original = scene.render

        def capture(painter, target, source, *args):
            original(painter, target, source, *args)
            shots.append(QImage(painter.device()))

        scene.render = capture
        try:
            export_flow_to_pdf(view, view.board.flow_by_id("tour"),
                               path.with_suffix(".pdf"))
        finally:
            del scene.render
    ink = QColor(theme.INK)
    assert len(shots) == 2
    assert _ink_pixels(shots[0], ink) > _ink_pixels(shots[1], ink) + 1000


# ── the symbol grid ─────────────────────────────────────────────

def test_the_grid_lists_the_boards_icons_after_the_built_in_ones(tmp_path):
    view = _view(_board(tmp_path, '@ box a "A" 0,0 100x100\n',
                        {"monitor.svg": SQUARE, "phone.svg": SQUARE}))
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    entries = view._ICON_ENTRIES
    assert entries[:len(iconset.ICON_NAMES) + 1] == [""] + iconset.ICON_NAMES
    assert entries[-2:] == ["monitor", "phone"]
    header, start, count = view._ICON_BLOCKS[-1]
    assert (header, start, count) == ("this board", len(entries) - 2, 2)
    # The last row holds them, on a row of their own.
    assert view._icon_grid_rows()[-1] == [len(entries) - 2, len(entries) - 1]
    view._icon_picker_move(0, 99)
    assert view._icon_picker_name() == "monitor"
    view._commit_icon_picker()
    assert view.board.box_by_id("a").icon == "monitor"


def test_the_grid_opens_on_the_boards_icon_a_box_has(tmp_path):
    view = _view(_board(tmp_path, '@ box a "A" 0,0 100x100 *phone\n',
                        {"monitor.svg": SQUARE, "phone.svg": SQUARE}))
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    assert view._icon_picker_name() == "phone"
    view._cancel_icon_picker()


def test_the_grid_paints_with_the_boards_icons(tmp_path):
    view = _view(_board(tmp_path, '@ box a "A" 0,0 100x100\n',
                        {"monitor.svg": SQUARE}))
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    img = QImage(900, 600, QImage.Format.Format_ARGB32)
    img.fill(0)
    view.viewport().render(img)
    assert not img.isNull()


def test_without_own_icons_the_grid_keeps_its_two_blocks(tmp_path):
    view = _view(_board(tmp_path, '@ box a "A" 0,0 100x100\n'))
    view._box_items["a"].setSelected(True)
    view._open_icon_picker()
    assert [b[0] for b in view._ICON_BLOCKS] == ["semantic", "emphasis"]
    assert view._ICON_ENTRIES == [""] + iconset.ICON_NAMES


def test_the_help_sheet_names_the_boards_icons_in_the_grid():
    import inspect
    from grafli.view.overlays import OverlaysMixin
    source = inspect.getsource(OverlaysMixin._show_cheatsheet)
    line = next(ln for ln in source.splitlines() if '("  i", ' in ln)
    assert "the board's own icons" in line and "-res/icons/" in line
    assert "<" not in line.split('", "', 1)[1]   # the sheet is HTML


# ── diagnose ────────────────────────────────────────────────────

def _unknown(path: Path) -> list:
    from grafli.diagnostics import run_all
    board = parse(path.read_text(encoding="utf-8"))
    return [d for d in run_all(board, base_dir=path.parent, grafli_path=path)
            if d.code == "unknown-icon"]


def test_diagnose_knows_the_boards_icons(tmp_path):
    path = _board(tmp_path, '@ box a "A" 0,0 100x100 *monitor\n'
                            '@ note n 0,200 *badge:monitor\n',
                  {"monitor.svg": SQUARE})
    assert _unknown(path) == []


def test_diagnose_reports_a_name_found_nowhere(tmp_path):
    path = _board(tmp_path, '@ box a "A" 0,0 100x100 *monitr\n'
                            '@ box b "B" 200,0 100x100 *zzqqxx\n',
                  {"monitor.svg": SQUARE})
    found = {d.item_ids[0]: d for d in _unknown(path)}
    assert set(found) == {"a", "b"}
    assert "neither built in nor in board-res/icons/" in found["a"].message
    assert "did you mean *monitor?" in found["a"].message
    assert found["a"].fix["new"] == "monitor"
    assert found["b"].fix is None


BROKEN = "<!doctype html><html><body>Not found</body></html>"


def test_a_file_that_is_no_svg_is_no_icon(tmp_path):
    path = _board(tmp_path, '@ box a "A" 0,0 200x60 *lead:x\n'
                            '@ box b "B" 0,100 160x160 *x\n',
                  {"x.svg": BROKEN, "monitor.svg": SQUARE})
    icons = iconset.BoardIcons.of(path)
    assert "x" not in icons and icons.names() == ["monitor"]
    assert icons.unreadable("x") == iconset.board_icon_dir(path) / "x.svg"
    assert icons.unreadable("monitor") is None
    # It reserves no place: the label keeps the layout of a box without one.
    view = _view(path)
    assert not view._box_items["a"]._has_lead_icon()
    b = view._box_items["b"]
    assert b._label.pos().y() - b.box.y < 160 / 2   # centred, not a caption


def test_diagnose_names_a_file_that_is_no_svg(tmp_path):
    path = _board(tmp_path, '@ box a "A" 0,0 100x100 *x\n',
                  {"x.svg": BROKEN})
    found = _unknown(path)
    assert [d.item_ids for d in found] == [["a"]]
    assert ("board-res/icons/x.svg is not a readable SVG"
            in found[0].message)
    assert found[0].fix is None


def test_the_diagnose_cli_passes_a_board_using_its_icons(tmp_path, capsys):
    from grafli.app import _cmd_diagnose
    path = _board(tmp_path, '@ box a "A" 0,0 100x100 *lead:monitor\n',
                  {"monitor.svg": SQUARE})
    _cmd_diagnose([str(path)])
    assert "unknown-icon" not in capsys.readouterr().out
