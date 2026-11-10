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
