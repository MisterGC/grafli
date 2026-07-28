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


def _rel_lum(c: QColor) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = _rel_lum(a), _rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_tokens_keep_their_contrast_role_across_themes():
    """A token's contrast against its own canvas encodes how loud it is.

    %highlight is a quiet tint in both themes, %primary the loud one. Without
    this, dark fills drift toward light-theme luminance and glow against the
    dark ground instead of tinting the node.
    """
    for token in theme.LIGHT.COLOR_TOKENS:
        if token == "base":
            continue  # base *is* the ground; contrast is ~1 by definition
        light = _contrast(QColor(theme.LIGHT.COLOR_TOKENS[token]),
                          theme.LIGHT.SCENE_BG)
        dark = _contrast(QColor(theme.DARK.COLOR_TOKENS[token]),
                         theme.DARK.SCENE_BG)
        assert abs(light - dark) < 1.0, (
            f"%{token}: {light:.2f}:1 on light vs {dark:.2f}:1 on dark — "
            "the dark fill no longer plays the same role")


def test_dark_tokens_stay_as_distinct_as_the_light_ones():
    """Categorical colours must stay tellable apart, not just correctly toned."""
    import itertools
    import math

    def lab(c: QColor):
        def inv(v):
            v /= 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

        def f(t):
            return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

        r, g, b = inv(c.red()), inv(c.green()), inv(c.blue())
        x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
        fx, fy, fz = f(x), f(y), f(z)
        return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))

    def min_separation(tokens):
        values = [QColor(v) for k, v in tokens.items() if k != "base"]
        return min(math.dist(lab(a), lab(b))
                   for a, b in itertools.combinations(values, 2))

    light_min = min_separation(theme.LIGHT.COLOR_TOKENS)
    dark_min = min_separation(theme.DARK.COLOR_TOKENS)
    # The light palette sets the bar; allow a small margin, not a collapse.
    assert dark_min > light_min - 2.0, (
        f"dark tokens crowd together (min ΔE {dark_min:.1f} vs "
        f"light {light_min:.1f})")


def _chips():
    """Every small coloured chip that carries text on top of itself."""
    return ([(f"edge:{k}", v) for k, v in theme.EDGE_KIND_COLORS.items()]
            + [(f"speaker{i}", c)
               for i, c in enumerate(theme.DISCUSSION_COLORS)]
            + [("task", theme.NOTE_TASK_COLOR),
               ("question", theme.NOTE_QUESTION_COLOR),
               ("bookmark", theme.BOOKMARK_BG),
               ("error", theme.ERROR_BG)])


def test_chip_text_stays_readable_on_every_chip():
    """Chip ink is derived from the chip, never hardcoded.

    A fixed light ink only looks right while the chip is dark. The dark theme
    lifts these fills, so a hardcoded white turns into glary, low-contrast text
    on a light green ``verify`` badge. 3:1 is the bar for bold text this size.
    """
    try:
        for name in ("light", "dark"):
            theme.set_theme(name)
            for label, chip in _chips():
                got = _contrast(theme.ink_on(chip), chip)
                assert got >= 3.0, (
                    f"{name} {label}: chip {chip.name()} with "
                    f"{theme.ink_on(chip).name()} ink is only {got:.2f}:1")
    finally:
        theme.set_theme("light")


def test_ink_on_flips_with_the_fill():
    assert theme.ink_on(QColor("#FFFFFF")) == theme.INK_ON_LIGHT_FILL
    assert theme.ink_on(QColor("#000000")) == theme.INK_ON_DARK_FILL


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


# ── Overlay cards ──────────────────────────────────────────────────

def _flatten(ink: QColor, card: QColor) -> QColor:
    """The ink as it actually lands, composited over the card at its alpha."""
    a = ink.alphaF()
    return QColor(round(ink.red() * a + card.red() * (1 - a)),
                  round(ink.green() * a + card.green() * (1 - a)),
                  round(ink.blue() * a + card.blue() * (1 - a)))


def test_overlay_ink_stays_readable_on_its_card():
    """Overlay cards invert against the board, so their ink must invert too.

    The tiers are emphasis, not fixed greys: the faintest one (hints) still has
    to clear 3:1 once composited, and the order title > body > hint has to hold
    in both palettes rather than only on the card the values were picked for.
    """
    tiers = (("title", 1.0), ("body", 0.86), ("hint", 0.59))
    for name in ("light", "dark"):
        theme.set_theme(name)
        card = QColor(theme.OVERLAY_BG)
        ratios = []
        for label, strength in tiers:
            got = _contrast(_flatten(theme.overlay_ink(strength), card), card)
            assert got >= 3.0, f"{name} overlay {label}: {got:.2f}:1 on the card"
            ratios.append(got)
        assert ratios == sorted(ratios, reverse=True), (
            f"{name}: emphasis order collapsed — {ratios}")
    theme.set_theme("light")


def test_no_overlay_panel_hardcodes_a_light_ink():
    """The regression that made the flow caption vanish on the dark theme.

    Every one of these panels drew near-white text because ``OVERLAY_BG`` was
    always a dark card. The dark theme flips that card to paper, so a baked
    light neutral drops to ~1.1:1 and the text is simply gone. Saturated
    literals (the cyan selection ring, the red 'no colour' slash) are fine —
    they read on either ground; it is the *light neutrals* that are the bug.
    """
    import ast
    import pathlib

    offenders = []
    for path in sorted(pathlib.Path(theme.__file__).parent.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(n, ast.Attribute) and n.attr == "OVERLAY_BG"
                       for n in ast.walk(fn)):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "QColor"
                        and len(node.args) >= 3
                        and all(isinstance(a, ast.Constant)
                                and isinstance(a.value, int)
                                for a in node.args)):
                    continue
                r, g, b = (a.value for a in node.args[:3])
                near_neutral = max(r, g, b) - min(r, g, b) <= 12
                if near_neutral and _rel_lum(QColor(r, g, b)) > 0.25:
                    offenders.append(
                        f"{path.name}:{node.lineno} QColor({r}, {g}, {b})")
    assert not offenders, (
        "light ink baked onto an overlay card — use theme.overlay_ink(): "
        + ", ".join(offenders))
