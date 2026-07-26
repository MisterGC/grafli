"""Colour palette — light and dark, swappable at runtime.

Every colour the app paints comes from here. Modules read roles as module
attributes::

    from grafli import theme
    painter.fillRect(rect, theme.SCENE_BG)

Access is deliberately ``theme.X`` rather than ``from theme import X``: the
module globals are rebound when the theme switches, so a plain attribute read
always yields the active value with no indirection at paint time.

The two palettes are counterparts, not inversions. Light is warm paper
(``#E8E4DD``) with near-black ink; dark is the same warm hue family rotated to
a low-key ground (``#1E1C19``) with the light theme's paper colour as its ink.
Contrast relationships between roles are preserved so a board reads the same
way in both.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


@dataclass(frozen=True)
class Palette:
    """One complete set of colour roles."""

    name: str
    is_dark: bool

    # ── Ground & surfaces ────────────────────────────────────────
    SCENE_BG: QColor                 # the canvas itself
    BOX_FILL: QColor                 # default node fill
    SURFACE: QColor                  # note / chip / code paper
    SURFACE_FLAT: QColor             # flat-style note paper
    GRID_COLOR: QColor
    CONTENT_BORDER_COLOR: QColor

    # ── Ink ──────────────────────────────────────────────────────
    INK: QColor                      # primary text & node borders
    BOX_BORDER: QColor
    ARROW_COLOR: QColor
    INK_ON_LIGHT_FILL: QColor        # text over a bright node fill
    INK_ON_DARK_FILL: QColor         # text over a dark node fill
    INK_SUBTLE: QColor
    INK_MUTED: QColor
    INK_FAINT: QColor                # hints, comments, section labels
    INK_DISABLED: QColor
    ON_ACCENT: QColor                # text over a saturated accent fill

    # ── Notes ────────────────────────────────────────────────────
    NOTE_COLOR: QColor
    NOTE_PEN_COLOR: QColor
    NOTE_TASK_COLOR: QColor
    NOTE_QUESTION_COLOR: QColor
    NOTE_DISCUSSION_COLOR: QColor
    DISCUSSION_COLORS: list

    # ── Code-mode notes ──────────────────────────────────────────
    NOTE_CODE_BG_COLOR: QColor
    NOTE_CODE_BORDER_COLOR: QColor
    NOTE_CODE_KW_COLOR: QColor
    NOTE_CODE_KW_CONTRACT_COLOR: QColor
    NOTE_CODE_REF_COLOR: QColor
    NOTE_CODE_COMMENT_COLOR: QColor
    NOTE_CODE_TEXT_COLOR: QColor
    NOTE_CODE_INDENT_GUIDE_COLOR: QColor
    NOTE_MD_CODE_BG_COLOR: QColor

    # ── Accents, selection, handles ──────────────────────────────
    ACCENT_TEAL: QColor              # selection dashes, glyph outlines
    SELECT_COLOR: QColor             # selection glow
    SHADOW_COLOR: QColor
    INFO_COLOR: QColor
    ANNOTATION_ARROW_COLOR: QColor
    HANDLE_FILL: QColor
    HANDLE_PEN: QColor
    HANDLE_HOVER_FILL: QColor
    HANDLE_HOVER_PEN: QColor
    GLYPH_BADGE_BG: QColor
    GLYPH_BADGE_FG: QColor
    PLACEHOLDER_FILL: QColor         # image placeholder
    BAR_COLOR: QColor                # progress / rule bars
    FALLBACK_FILL: QColor
    BOOKMARK_BG: QColor
    ERROR_BG: QColor
    SELECT_MARQUEE: QColor           # rubber-band selection
    CONFLICT_BG: QColor              # sync-conflict banner
    STATUS_DIM: QColor               # status-bar secondary text
    LOD_NEUTRAL: QColor              # level-of-detail aggregation tint
    ICON_SHEET_INK: QColor           # sketchnote symbol stroke
    ICON_BADGE_PLATE: QColor         # plate behind a corner badge

    # ── Floating chrome (badges, tooltips) ───────────────────────
    OVERLAY_BG: QColor
    OVERLAY_FG: QColor

    # ── Author-facing %tokens ────────────────────────────────────
    COLOR_TOKENS: dict

    # ── Edge kinds ───────────────────────────────────────────────
    EDGE_KIND_COLORS: dict

    # ── Minimap ──────────────────────────────────────────────────
    MINIMAP_BG: QColor
    MINIMAP_VIEWPORT_COLOR: QColor
    MINIMAP_BORDER_COLOR: QColor
    MINIMAP_STATS_COLOR: QColor
    MINIMAP_TIER_COLORS: list
    MINIMAP_INFO_COLOR: QColor
    MINIMAP_CONNECTOR_COLOR: QColor
    MINIMAP_CAMERA_COLOR: QColor
    MINIMAP_GRID_COLOR: QColor
    MINIMAP_SELECT_COLOR: QColor

    # ── Complexity heatmap ───────────────────────────────────────
    HEATMAP_STOPS: list
    HEATMAP_BG: QColor
    HEATMAP_GRID_COLOR: QColor
    HEATMAP_CONTENT_BORDER: QColor
    HEATMAP_TEXT_COLOR: QColor

    # ── Zen overlay ──────────────────────────────────────────────
    ZEN_DIM_COLOR: QColor
    ZEN_PANEL_BG: QColor
    ZEN_PANEL_BORDER: QColor
    ZEN_TEXT_COLOR: QColor
    ZEN_TITLE_COLOR: QColor
    ZEN_HINT_COLOR: QColor

    # ── Side panel ───────────────────────────────────────────────
    SIDE_PANEL_BG: QColor
    SIDE_PANEL_BORDER: QColor
    SIDE_PANEL_SECTION_COLOR: QColor
    SIDE_PANEL_BTN_HOVER: QColor
    SIDE_PANEL_BTN_ACTIVE: QColor
    SIDE_PANEL_SHORTCUT_COLOR: QColor
    SIDE_PANEL_TOGGLE_BG: QColor
    SIDE_PANEL_TOGGLE_BORDER: QColor

    # ── Glyph picker ─────────────────────────────────────────────
    GLYPH_PICKER_BG: QColor
    GLYPH_PICKER_HIGHLIGHT: QColor
    GLYPH_PICKER_BADGE: QColor
    GLYPH_PICKER_BORDER: QColor
    GLYPH_PICKER_FIELD_BG: QColor
    GLYPH_PICKER_NAME_FG: QColor
    GLYPH_PICKER_INACTIVE_FG: QColor

    # ── Help / diagnostics overlay ───────────────────────────────
    HELP_BG: QColor
    HELP_FG: QColor
    HELP_BORDER: QColor
    HELP_TAB_SELECTED: QColor
    HELP_CODE_BG: QColor

    # ── Inline editors & flows panel ─────────────────────────────
    EDITOR_BG: QColor
    EDITOR_BORDER: QColor
    EDITOR_SELECTION_BG: QColor
    FIELD_BG: QColor
    TOOLTIP_BG: QColor
    TOOLTIP_FG: QColor
    TOOLTIP_HOVER: QColor
    FLOWS_ACCENT: QColor


LIGHT = Palette(
    name="light",
    is_dark=False,

    SCENE_BG=QColor("#E8E4DD"),
    BOX_FILL=QColor("#E8E4DD"),
    SURFACE=QColor("#F2F0EB"),
    SURFACE_FLAT=QColor("#E9E5DD"),
    GRID_COLOR=QColor("#CDC8BF"),
    CONTENT_BORDER_COLOR=QColor("#D5D0C8"),

    INK=QColor("#2F3437"),
    BOX_BORDER=QColor("#2F3437"),
    ARROW_COLOR=QColor("#2F3437"),
    INK_ON_LIGHT_FILL=QColor("#2D2D2D"),
    INK_ON_DARK_FILL=QColor("#F2F0EB"),
    INK_SUBTLE=QColor("#4A4A4A"),
    INK_MUTED=QColor("#5A5A5A"),
    INK_FAINT=QColor("#8A8580"),
    INK_DISABLED=QColor("#B8B3AB"),
    ON_ACCENT=QColor("#FFFFFF"),

    NOTE_COLOR=QColor("#2B6CB0"),
    NOTE_PEN_COLOR=QColor("#2B6CB0"),
    NOTE_TASK_COLOR=QColor("#C53030"),
    NOTE_QUESTION_COLOR=QColor("#805AD5"),
    NOTE_DISCUSSION_COLOR=QColor("#2C7A7B"),
    DISCUSSION_COLORS=[
        QColor("#2F855A"),  # green
        QColor("#805AD5"),  # purple
        QColor("#C05621"),  # orange
        QColor("#2B6CB0"),  # blue
        QColor("#B83280"),  # pink
        QColor("#2C7A7B"),  # teal
    ],

    NOTE_CODE_BG_COLOR=QColor("#F2F0EB"),
    NOTE_CODE_BORDER_COLOR=QColor("#CDC8BF"),
    NOTE_CODE_KW_COLOR=QColor("#2B6CB0"),
    NOTE_CODE_KW_CONTRACT_COLOR=QColor("#C53030"),
    NOTE_CODE_REF_COLOR=QColor("#2B6CB0"),
    NOTE_CODE_COMMENT_COLOR=QColor("#8A8580"),
    NOTE_CODE_TEXT_COLOR=QColor("#2F3437"),
    NOTE_CODE_INDENT_GUIDE_COLOR=QColor("#B5B0A8"),
    NOTE_MD_CODE_BG_COLOR=QColor("#E7E3DA"),

    ACCENT_TEAL=QColor("#2F5D5C"),
    SELECT_COLOR=QColor("#D4BA6A"),
    SHADOW_COLOR=QColor("#000000"),
    INFO_COLOR=QColor("#6A9FB5"),
    ANNOTATION_ARROW_COLOR=QColor("#8A8580"),
    HANDLE_FILL=QColor("#FFFFFF"),
    HANDLE_PEN=QColor("#2F5D5C"),
    HANDLE_HOVER_FILL=QColor("#2F5D5C"),
    HANDLE_HOVER_PEN=QColor("#FFFFFF"),
    GLYPH_BADGE_BG=QColor("#2F3437"),
    GLYPH_BADGE_FG=QColor("#ECECEC"),
    PLACEHOLDER_FILL=QColor("#D5D0C8"),
    BAR_COLOR=QColor("#9A968D"),
    FALLBACK_FILL=QColor("#C8CCD0"),
    BOOKMARK_BG=QColor("#C1086D"),
    ERROR_BG=QColor("#E04040"),
    SELECT_MARQUEE=QColor("#0178D4"),
    CONFLICT_BG=QColor("#7A1F1F"),
    STATUS_DIM=QColor("#888888"),
    LOD_NEUTRAL=QColor("#8E9299"),
    ICON_SHEET_INK=QColor("#2D3033"),
    ICON_BADGE_PLATE=QColor("#F7F5F0"),

    OVERLAY_BG=QColor("#2F3437"),
    OVERLAY_FG=QColor("#FFFFFF"),

    COLOR_TOKENS={
        "base": "#E8E4DD",
        "primary": "#004578",
        "secondary": "#0178D4",
        "tertiary": "#4EBF71",
        "subtle": "#4A4A4A",
        "accent": "#D4804E",
        "highlight": "#D4BA6A",
        "muted": "#B8B3AB",
        "soft": "#B0A1CA",
        # Extended muted hues filling the gaps (red / teal / pink / deep green /
        # deep purple), tuned to the same desaturated, slightly-warm character.
        "clay": "#C56C54",
        "teal": "#3E9B92",
        "rose": "#C98BA8",
        "forest": "#3F7A57",
        "plum": "#8160A8",
    },

    EDGE_KIND_COLORS={
        "call": QColor("#2F5D5C"),
        "data": QColor("#2B6CB0"),
        "event": QColor("#C05621"),
        "state": QColor("#805AD5"),
        "step": QColor("#805AD5"),
        "verify": QColor("#2F855A"),
        "owns": QColor("#2C7A7B"),
        "depends": QColor("#6A9FB5"),
        "risk": QColor("#C53030"),
        "note": QColor("#8A8580"),
    },

    MINIMAP_BG=QColor(40, 40, 40, 180),
    MINIMAP_VIEWPORT_COLOR=QColor(255, 255, 255, 60),
    MINIMAP_BORDER_COLOR=QColor(80, 80, 80, 200),
    MINIMAP_STATS_COLOR=QColor(170, 170, 170),
    MINIMAP_TIER_COLORS=[
        QColor(127, 185, 127),  # Simple — green
        QColor(201, 184, 78),   # Moderate — yellow
        QColor(212, 136, 58),   # Intricate — orange
        QColor(199, 80, 80),    # Dense — red
    ],
    MINIMAP_INFO_COLOR=QColor(106, 159, 181),
    MINIMAP_CONNECTOR_COLOR=QColor(180, 180, 180, 110),
    MINIMAP_CAMERA_COLOR=QColor(106, 159, 181),
    MINIMAP_GRID_COLOR=QColor(150, 142, 128, 24),
    MINIMAP_SELECT_COLOR=QColor(255, 196, 87),

    HEATMAP_STOPS=[
        (0.00, QColor("#5B8FA8")),  # cold: muted steel blue
        (0.25, QColor("#6BAA8A")),  # sage green
        (0.50, QColor("#C4B555")),  # warm gold
        (0.75, QColor("#D4804E")),  # Grafli accent orange
        (1.00, QColor("#C75050")),  # hot: warm red
    ],
    HEATMAP_BG=QColor("#1E1E2E"),
    HEATMAP_GRID_COLOR=QColor("#2A2A3A"),
    HEATMAP_CONTENT_BORDER=QColor("#3A3A4A"),
    HEATMAP_TEXT_COLOR=QColor("#FFFFFF"),

    ZEN_DIM_COLOR=QColor(180, 175, 168, 160),
    ZEN_PANEL_BG=QColor("#F5F2ED"),
    ZEN_PANEL_BORDER=QColor("#CDC8BF"),
    ZEN_TEXT_COLOR=QColor("#403A30"),
    ZEN_TITLE_COLOR=QColor("#004578"),
    ZEN_HINT_COLOR=QColor("#8A8580"),

    SIDE_PANEL_BG=QColor("#F5F2ED"),
    SIDE_PANEL_BORDER=QColor("#CDC8BF"),
    SIDE_PANEL_SECTION_COLOR=QColor("#8A8580"),
    SIDE_PANEL_BTN_HOVER=QColor("#E8E4DD"),
    SIDE_PANEL_BTN_ACTIVE=QColor("#D5D0C8"),
    SIDE_PANEL_SHORTCUT_COLOR=QColor("#B8B3AB"),
    SIDE_PANEL_TOGGLE_BG=QColor(245, 242, 237, 200),
    SIDE_PANEL_TOGGLE_BORDER=QColor("#CDC8BF"),

    GLYPH_PICKER_BG=QColor(47, 52, 55, 242),
    GLYPH_PICKER_HIGHLIGHT=QColor("#4A6A7A"),
    GLYPH_PICKER_BADGE=QColor("#6A9FB5"),
    GLYPH_PICKER_BORDER=QColor("#555555"),
    GLYPH_PICKER_FIELD_BG=QColor("#3A3F42"),
    GLYPH_PICKER_NAME_FG=QColor("#888888"),
    GLYPH_PICKER_INACTIVE_FG=QColor("#AAAAAA"),

    HELP_BG=QColor("#2A2A2A"),
    HELP_FG=QColor("#E0E0E0"),
    HELP_BORDER=QColor("#555555"),
    HELP_TAB_SELECTED=QColor("#3A3A3A"),
    HELP_CODE_BG=QColor("#1E1E1E"),

    EDITOR_BG=QColor("#FBFAF7"),
    EDITOR_BORDER=QColor("#2F5D5C"),
    EDITOR_SELECTION_BG=QColor("#B8D4E8"),
    FIELD_BG=QColor("#FFFFFF"),
    TOOLTIP_BG=QColor("#2A2D2E"),
    TOOLTIP_FG=QColor("#D4D4D4"),
    TOOLTIP_HOVER=QColor("#3A3D3E"),
    FLOWS_ACCENT=QColor("#D4804E"),
)


DARK = Palette(
    name="dark",
    is_dark=True,

    # The ground keeps the light theme's warm hue, rotated to low key — a
    # neutral-cool dark would read as a different product.
    SCENE_BG=QColor("#1E1C19"),
    BOX_FILL=QColor("#2C2924"),
    SURFACE=QColor("#26241F"),
    SURFACE_FLAT=QColor("#302D27"),
    # Same canvas-to-dot delta the light theme uses, so the grid reads as
    # equally present rather than disappearing into the dark ground.
    GRID_COLOR=QColor("#393733"),
    CONTENT_BORDER_COLOR=QColor("#3B372F"),

    # Ink is the light theme's paper — the pairing that makes the two themes
    # read as counterparts rather than two unrelated palettes.
    INK=QColor("#E8E4DD"),
    BOX_BORDER=QColor("#E8E4DD"),
    ARROW_COLOR=QColor("#D8D3CA"),
    INK_ON_LIGHT_FILL=QColor("#2D2D2D"),
    INK_ON_DARK_FILL=QColor("#F2F0EB"),
    INK_SUBTLE=QColor("#C4BFB6"),
    INK_MUTED=QColor("#A9A49B"),
    INK_FAINT=QColor("#8C877F"),
    INK_DISABLED=QColor("#6B665F"),
    ON_ACCENT=QColor("#FFFFFF"),

    # Note hues lifted in lightness and slightly desaturated so they sit on a
    # dark ground at the same perceived weight they have on paper.
    NOTE_COLOR=QColor("#6BA3DC"),
    NOTE_PEN_COLOR=QColor("#6BA3DC"),
    NOTE_TASK_COLOR=QColor("#E07070"),
    NOTE_QUESTION_COLOR=QColor("#A98BE8"),
    NOTE_DISCUSSION_COLOR=QColor("#56AFB0"),
    DISCUSSION_COLORS=[
        QColor("#5FB588"),  # green
        QColor("#A98BE8"),  # purple
        QColor("#DD8A4E"),  # orange
        QColor("#6BA3DC"),  # blue
        QColor("#DB6FAC"),  # pink
        QColor("#56AFB0"),  # teal
    ],

    NOTE_CODE_BG_COLOR=QColor("#24221D"),
    NOTE_CODE_BORDER_COLOR=QColor("#3B372F"),
    NOTE_CODE_KW_COLOR=QColor("#6BA3DC"),
    NOTE_CODE_KW_CONTRACT_COLOR=QColor("#E07070"),
    NOTE_CODE_REF_COLOR=QColor("#6BA3DC"),
    NOTE_CODE_COMMENT_COLOR=QColor("#8C877F"),
    NOTE_CODE_TEXT_COLOR=QColor("#E4E0D8"),
    NOTE_CODE_INDENT_GUIDE_COLOR=QColor("#453F37"),
    NOTE_MD_CODE_BG_COLOR=QColor("#1A1815"),

    ACCENT_TEAL=QColor("#6FB3B0"),
    SELECT_COLOR=QColor("#E0C87E"),
    SHADOW_COLOR=QColor("#000000"),
    INFO_COLOR=QColor("#7FB6CC"),
    ANNOTATION_ARROW_COLOR=QColor("#7E7972"),
    HANDLE_FILL=QColor("#1E1C19"),
    HANDLE_PEN=QColor("#6FB3B0"),
    HANDLE_HOVER_FILL=QColor("#6FB3B0"),
    HANDLE_HOVER_PEN=QColor("#1E1C19"),
    GLYPH_BADGE_BG=QColor("#E8E4DD"),
    GLYPH_BADGE_FG=QColor("#26241F"),
    PLACEHOLDER_FILL=QColor("#3B372F"),
    BAR_COLOR=QColor("#6B665F"),
    FALLBACK_FILL=QColor("#3A4045"),
    BOOKMARK_BG=QColor("#D4459A"),
    ERROR_BG=QColor("#E05555"),
    SELECT_MARQUEE=QColor("#4EA8E8"),
    CONFLICT_BG=QColor("#8E2F2F"),
    STATUS_DIM=QColor("#8C877F"),
    LOD_NEUTRAL=QColor("#7E827F"),
    ICON_SHEET_INK=QColor("#E4E0D8"),
    ICON_BADGE_PLATE=QColor("#302D27"),

    # Floating chrome inverts relative to the light theme: on a dark canvas a
    # near-black badge would disappear, so it becomes a light chip.
    OVERLAY_BG=QColor("#EDE9E1"),
    OVERLAY_FG=QColor("#26241F"),

    # Semantic %tokens re-resolve per theme, so a board authored in one theme
    # reads correctly in the other. Hues match the light set; lightness and
    # saturation are retuned for a dark ground.
    COLOR_TOKENS={
        "base": "#2C2924",
        "primary": "#2F6EA8",
        "secondary": "#3E9BE8",
        "tertiary": "#55C182",
        "subtle": "#6E6A63",
        "accent": "#DB8B5C",
        "highlight": "#D9C177",
        "muted": "#57534D",
        "soft": "#8D7DB0",
        "clay": "#CD7A62",
        "teal": "#46AAA0",
        "rose": "#C98BA8",
        "forest": "#4E9469",
        "plum": "#9070B8",
    },

    EDGE_KIND_COLORS={
        "call": QColor("#6FB3B0"),
        "data": QColor("#6BA3DC"),
        "event": QColor("#DD8A4E"),
        "state": QColor("#A98BE8"),
        "step": QColor("#A98BE8"),
        "verify": QColor("#5FB588"),
        "owns": QColor("#56AFB0"),
        "depends": QColor("#7FB6CC"),
        "risk": QColor("#E07070"),
        "note": QColor("#8C877F"),
    },

    # The minimap is already a dark chip; on a dark canvas it needs to lift
    # away from the ground rather than sink into it.
    MINIMAP_BG=QColor(58, 55, 49, 205),
    MINIMAP_VIEWPORT_COLOR=QColor(255, 255, 255, 45),
    MINIMAP_BORDER_COLOR=QColor(110, 104, 95, 220),
    MINIMAP_STATS_COLOR=QColor(178, 172, 163),
    MINIMAP_TIER_COLORS=[
        QColor(127, 185, 127),
        QColor(201, 184, 78),
        QColor(212, 136, 58),
        QColor(199, 80, 80),
    ],
    MINIMAP_INFO_COLOR=QColor(127, 182, 204),
    MINIMAP_CONNECTOR_COLOR=QColor(190, 184, 175, 100),
    MINIMAP_GRID_COLOR=QColor(190, 180, 162, 20),
    MINIMAP_CAMERA_COLOR=QColor(127, 182, 204),
    MINIMAP_SELECT_COLOR=QColor(255, 196, 87),

    # The heatmap owns its own cold-to-hot scale; only its chrome follows the
    # theme, so the tier colours stay comparable across a theme switch.
    HEATMAP_STOPS=[
        (0.00, QColor("#5B8FA8")),
        (0.25, QColor("#6BAA8A")),
        (0.50, QColor("#C4B555")),
        (0.75, QColor("#D4804E")),
        (1.00, QColor("#C75050")),
    ],
    HEATMAP_BG=QColor("#16151C"),
    HEATMAP_GRID_COLOR=QColor("#232230"),
    HEATMAP_CONTENT_BORDER=QColor("#33323F"),
    HEATMAP_TEXT_COLOR=QColor("#FFFFFF"),

    ZEN_DIM_COLOR=QColor(12, 11, 10, 170),
    ZEN_PANEL_BG=QColor("#24221D"),
    ZEN_PANEL_BORDER=QColor("#3B372F"),
    ZEN_TEXT_COLOR=QColor("#E4E0D8"),
    ZEN_TITLE_COLOR=QColor("#7FB6CC"),
    ZEN_HINT_COLOR=QColor("#8C877F"),

    SIDE_PANEL_BG=QColor("#24221D"),
    SIDE_PANEL_BORDER=QColor("#3B372F"),
    SIDE_PANEL_SECTION_COLOR=QColor("#8C877F"),
    SIDE_PANEL_BTN_HOVER=QColor("#302D27"),
    SIDE_PANEL_BTN_ACTIVE=QColor("#3B372F"),
    SIDE_PANEL_SHORTCUT_COLOR=QColor("#6B665F"),
    SIDE_PANEL_TOGGLE_BG=QColor(36, 34, 29, 210),
    SIDE_PANEL_TOGGLE_BORDER=QColor("#3B372F"),

    GLYPH_PICKER_BG=QColor(38, 36, 31, 246),
    GLYPH_PICKER_HIGHLIGHT=QColor("#4A6A7A"),
    GLYPH_PICKER_BADGE=QColor("#7FB6CC"),
    GLYPH_PICKER_BORDER=QColor("#4A453D"),
    GLYPH_PICKER_FIELD_BG=QColor("#302D27"),
    GLYPH_PICKER_NAME_FG=QColor("#8C877F"),
    GLYPH_PICKER_INACTIVE_FG=QColor("#A9A49B"),

    HELP_BG=QColor("#24221D"),
    HELP_FG=QColor("#E4E0D8"),
    HELP_BORDER=QColor("#4A453D"),
    HELP_TAB_SELECTED=QColor("#332F29"),
    HELP_CODE_BG=QColor("#1A1815"),

    EDITOR_BG=QColor("#2A2721"),
    EDITOR_BORDER=QColor("#6FB3B0"),
    EDITOR_SELECTION_BG=QColor("#3E5A6B"),
    FIELD_BG=QColor("#302D27"),
    TOOLTIP_BG=QColor("#EDE9E1"),
    TOOLTIP_FG=QColor("#26241F"),
    TOOLTIP_HOVER=QColor("#DCD7CD"),
    FLOWS_ACCENT=QColor("#DB8B5C"),
)


PALETTES = {"light": LIGHT, "dark": DARK}

_ROLES = tuple(f.name for f in fields(Palette) if f.name not in ("name", "is_dark"))


class _Notifier(QObject):
    """Emits whenever the active palette changes."""

    changed = Signal()


notifier = _Notifier()

_active = LIGHT


def active() -> Palette:
    """The palette in effect right now."""
    return _active


def is_dark() -> bool:
    return _active.is_dark


def name() -> str:
    return _active.name


def set_theme(theme_name: str) -> bool:
    """Make ``theme_name`` active and notify listeners.

    Returns False for an unknown name or a no-op switch, so callers can skip
    the (comparatively expensive) restyle pass.
    """
    palette = PALETTES.get(theme_name)
    if palette is None or palette is _active:
        return False
    _install(palette)
    notifier.changed.emit()
    return True


def toggle() -> str:
    """Switch to the other theme; returns the name now active."""
    set_theme("light" if _active.is_dark else "dark")
    return _active.name


def _install(palette: Palette) -> None:
    """Rebind every role to this module's globals.

    Consumers read ``theme.ROLE``, so rebinding here is what makes a switch
    take effect everywhere without touching a single call site.
    """
    global _active
    _active = palette
    g = globals()
    for role in _ROLES:
        g[role] = getattr(palette, role)
    g["IS_DARK"] = palette.is_dark
    g["NAME"] = palette.name


def resolve_color(color: str) -> str:
    """Resolve a ``%token`` to hex against the active theme.

    Literal hex passes through untouched — only semantic tokens follow the
    theme, so a board that pins an exact colour keeps it.
    """
    if color.startswith("%"):
        return _active.COLOR_TOKENS.get(color[1:], "")
    return color


_install(LIGHT)
