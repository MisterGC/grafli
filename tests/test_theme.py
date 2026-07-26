"""Light/dark theme: palette completeness, live switching, token semantics."""

from __future__ import annotations

import os
from dataclasses import fields

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.format import parse
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_BOARD = """#!grafli v2
@ box a "A" 0,0 100x100 %accent
@ box b "B" 200,0 100x100 #C0FFEE
@ arrow a -> b
"""


def _view(text: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(text))
    return view


def test_both_palettes_define_every_role():
    """A missing role would only surface as a crash on the theme that lacks it."""
    roles = [f.name for f in fields(theme.Palette)]
    for palette in (theme.LIGHT, theme.DARK):
        for role in roles:
            assert getattr(palette, role) is not None, f"{palette.name}.{role}"


def test_palettes_actually_differ():
    assert theme.LIGHT.SCENE_BG != theme.DARK.SCENE_BG
    assert theme.LIGHT.INK != theme.DARK.INK


def test_dark_inverts_the_ground_ink_relationship():
    """Ink must contrast with the canvas in both themes, in opposite directions."""
    def lum(c: QColor) -> float:
        return 0.299 * c.redF() + 0.587 * c.greenF() + 0.114 * c.blueF()

    assert lum(theme.LIGHT.SCENE_BG) > lum(theme.LIGHT.INK)
    assert lum(theme.DARK.SCENE_BG) < lum(theme.DARK.INK)


def test_set_theme_rebinds_module_attributes():
    try:
        assert theme.set_theme("dark")
        assert theme.SCENE_BG == theme.DARK.SCENE_BG
        assert theme.is_dark()
        assert theme.set_theme("light")
        assert theme.SCENE_BG == theme.LIGHT.SCENE_BG
        assert not theme.is_dark()
    finally:
        theme.set_theme("light")


def test_set_theme_rejects_unknown_and_noop():
    assert not theme.set_theme("solarized")   # unknown name
    assert not theme.set_theme("light")       # already active
    assert theme.name() == "light"


def test_toggle_round_trips():
    try:
        assert theme.toggle() == "dark"
        assert theme.toggle() == "light"
    finally:
        theme.set_theme("light")


def test_notifier_fires_only_on_a_real_change():
    seen = []
    theme.notifier.changed.connect(lambda: seen.append(theme.name()))
    try:
        theme.set_theme("dark")
        theme.set_theme("dark")   # no-op, must not notify
        theme.set_theme("light")
        assert seen == ["dark", "light"]
    finally:
        theme.notifier.changed.disconnect()
        theme.set_theme("light")


def test_semantic_tokens_reresolve_per_theme():
    """%tokens are semantic, so the same board reads correctly in both themes."""
    try:
        light_accent = theme.resolve_color("%accent")
        theme.set_theme("dark")
        dark_accent = theme.resolve_color("%accent")
        assert light_accent != dark_accent
        assert light_accent and dark_accent
    finally:
        theme.set_theme("light")


def test_literal_hex_is_never_remapped():
    """A board that pins an exact colour keeps it under both themes."""
    try:
        assert theme.resolve_color("#C0FFEE") == "#C0FFEE"
        theme.set_theme("dark")
        assert theme.resolve_color("#C0FFEE") == "#C0FFEE"
    finally:
        theme.set_theme("light")


def test_unknown_token_resolves_empty():
    assert theme.resolve_color("%nosuchtoken") == ""


def test_view_apply_theme_repaints_canvas_and_items():
    view = _view(_BOARD)
    box = view._box_items["a"]
    assert view._scene.backgroundBrush().color() == theme.LIGHT.SCENE_BG
    light_fill = box.brush().color()
    try:
        theme.set_theme("dark")
        view.apply_theme()
        assert view._scene.backgroundBrush().color() == theme.DARK.SCENE_BG
        # %accent re-resolves, so the node fill moves with the theme.
        assert box.brush().color() != light_fill
    finally:
        theme.set_theme("light")
        view.apply_theme()
    assert view._scene.backgroundBrush().color() == theme.LIGHT.SCENE_BG
    assert box.brush().color() == light_fill


def test_pinned_hex_node_keeps_its_fill_across_a_switch():
    view = _view(_BOARD)
    pinned = view._box_items["b"].brush().color()
    try:
        theme.set_theme("dark")
        view.apply_theme()
        assert view._box_items["b"].brush().color() == pinned
    finally:
        theme.set_theme("light")


def test_no_module_level_bindings_freeze_the_palette():
    """Guard the failure mode this design exists to avoid.

    ``X = theme.SOMETHING`` at module or class scope evaluates once at import
    and then keeps whichever theme was active then — the colour silently stops
    following a switch. Roles must be read at use time, via ``theme.ROLE``.
    Assignments inside a function body are fine; those re-run per call.
    """
    import ast
    import pathlib

    def reads_theme(node) -> bool:
        return any(
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "theme"
            and n.attr.isupper()
            for n in ast.walk(node)
        )

    root = pathlib.Path(__file__).resolve().parent.parent / "grafli"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "theme.py":
            continue
        tree = ast.parse(path.read_text())
        # Module body plus every class body — i.e. everything that runs at import.
        scopes = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, ast.ClassDef)]
        for scope in scopes:
            for stmt in scope.body:
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    if stmt.value is not None and reads_theme(stmt.value):
                        offenders.append(f"{path.name}:{stmt.lineno}")
    assert not offenders, (
        "palette frozen at import — read these at use time instead: "
        + ", ".join(offenders))


def test_arrows_are_rebuilt_on_a_switch():
    """Arrow pens are baked at build time — the switch has to redraw them."""
    view = _view(_BOARD)
    def arrow_pens():
        return {gfx.pen().color().name() for gfx in view._arrow_items
                if hasattr(gfx, "pen")}

    light_pens = arrow_pens()
    try:
        theme.set_theme("dark")
        view.apply_theme()
        assert arrow_pens() != light_pens
    finally:
        theme.set_theme("light")
        view.apply_theme()
    assert arrow_pens() == light_pens
