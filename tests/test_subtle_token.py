"""`%subtle` (#309) is the quietest filled grey: it renders lighter than
`%muted` and darker than an unfilled box on paper, and in the dark theme sits
between the two by the same measure — its contrast against the canvas — on
the canvas and in `grafli render`."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.format import parse


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _rel_lum(c: QColor) -> float:
    def ch(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = _rel_lum(a), _rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _quietness_order(plain: QColor, subtle: QColor, muted: QColor,
                     ground: QColor) -> None:
    """An unfilled box is quieter than %subtle, %subtle quieter than %muted."""
    assert (_contrast(plain, ground) < _contrast(subtle, ground)
            < _contrast(muted, ground)), (plain.name(), subtle.name(),
                                          muted.name())
    lo, hi = sorted((_rel_lum(plain), _rel_lum(muted)))
    assert lo < _rel_lum(subtle) < hi


@pytest.fixture(autouse=True)
def _light_after():
    yield
    theme.set_theme("light")


def test_subtle_is_lighter_than_muted_and_darker_than_a_plain_box_on_paper():
    theme.set_theme("light")
    subtle = QColor(theme.resolve_color("%subtle"))
    muted = QColor(theme.resolve_color("%muted"))
    assert _rel_lum(muted) < _rel_lum(subtle) < _rel_lum(theme.BOX_FILL)


@pytest.mark.parametrize("name", ["light", "dark"])
def test_subtle_sits_between_a_plain_box_and_muted(name: str):
    theme.set_theme(name)
    _quietness_order(theme.BOX_FILL,
                     QColor(theme.resolve_color("%subtle")),
                     QColor(theme.resolve_color("%muted")),
                     theme.SCENE_BG)


@pytest.mark.parametrize("name", ["light", "dark"])
def test_the_canvas_fills_a_subtle_box_with_the_quiet_grey(name: str):
    from grafli.view import GrafliView
    _app()
    theme.set_theme(name)
    view = GrafliView()
    view.load_board(parse('#!grafli v4\n'
                          '@ box p "p" 0,0 200x80\n'
                          '@ box s "s" 0,120 200x80 %subtle\n'
                          '@ box m "m" 0,240 200x80 %muted\n'))
    fill = {k: view._box_items[k].brush().color() for k in "psm"}
    assert fill["s"] == QColor(theme.resolve_color("%subtle"))
    _quietness_order(fill["p"], fill["s"], fill["m"], theme.SCENE_BG)


def _render_fill(tmp_path: Path, name: str, color: str) -> QColor:
    """The colour `grafli render` paints inside a lone box, away from its
    label plate and outline."""
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}{color.strip('%') or 'plain'}.grafli"
    board.write_text(f'#!grafli v4\n@ box b "b" 0,0 400x200 {color}\n')
    out = board.with_suffix(".png")
    assert _cmd_render([str(board), str(out), "--theme", name,
                        "--padding", "40"]) == 0
    image = QImage(str(out))
    return image.pixelColor(image.width() // 5, image.height() // 4)


@pytest.mark.parametrize("name", ["light", "dark"])
def test_render_paints_subtle_between_a_plain_box_and_muted(
        tmp_path: Path, name: str):
    _app()
    plain = _render_fill(tmp_path, name, "")
    subtle = _render_fill(tmp_path, name, "%subtle")
    muted = _render_fill(tmp_path, name, "%muted")
    theme.set_theme(name)
    assert subtle == QColor(theme.resolve_color("%subtle"))
    _quietness_order(plain, subtle, muted, theme.SCENE_BG)
