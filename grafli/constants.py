"""Shared constants, enums, and helpers for the grafli app."""

from __future__ import annotations

import enum
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont


# ── Colors ───────────────────────────────────────────────────────

BOX_FILL = QColor("#E8E4DD")
BOX_BORDER = QColor("#2F3437")
ARROW_COLOR = QColor("#2F3437")
NOTE_COLOR = QColor("#2B6CB0")
NOTE_PEN_COLOR = QColor("#2B6CB0")
NOTE_TASK_COLOR = QColor("#C53030")
NOTE_QUESTION_COLOR = QColor("#805AD5")
NOTE_DISCUSSION_COLOR = QColor("#2C7A7B")

DISCUSSION_COLORS = [
    QColor("#2F855A"),  # green
    QColor("#805AD5"),  # purple
    QColor("#C05621"),  # orange
    QColor("#2B6CB0"),  # blue
    QColor("#B83280"),  # pink
    QColor("#2C7A7B"),  # teal
]
GRID_COLOR = QColor("#CDC8BF")
SCENE_BG = QColor("#E8E4DD")
CONTENT_BORDER_COLOR = QColor("#D5D0C8")

COLOR_TOKENS = {
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
}

COLOR_PALETTE = [
    ("Default", ""),
    ("Base", "%base"),
    ("Primary", "%primary"),
    ("Secondary", "%secondary"),
    ("Tertiary", "%tertiary"),
    ("Subtle", "%subtle"),
    ("Accent", "%accent"),
    ("Highlight", "%highlight"),
    ("Muted", "%muted"),
    ("Soft", "%soft"),
    ("Clay", "%clay"),
    ("Teal", "%teal"),
    ("Rose", "%rose"),
    ("Forest", "%forest"),
    ("Plum", "%plum"),
]


def _resolve_color(color: str) -> str:
    """Resolve %token to hex, or pass through hex/empty as-is."""
    if color.startswith("%"):
        return COLOR_TOKENS.get(color[1:], "")
    return color


_COLOR_VALUES = [c for _, c in COLOR_PALETTE]

# ── Fonts ────────────────────────────────────────────────────────

FONT_FAMILY = "JetBrainsMono Nerd Font"
NOTE_FONT_FAMILY = "Patrick Hand"

BOX_FONT = QFont(FONT_FAMILY, 13)
NOTE_FONT = QFont(NOTE_FONT_FAMILY, 15)
LABEL_FONT = QFont(FONT_FAMILY, 10)

BOX_FONT_SIZES = {"": 13, "small": 10, "large": 18, "xlarge": 24, "xxlarge": 32, "xxxlarge": 44, "xxxxlarge": 60}
NOTE_FONT_SIZES = {"": 15, "small": 11, "large": 21, "xlarge": 28, "xxlarge": 40, "xxxlarge": 52, "xxxxlarge": 64}
# Short aliases accepted on input for the multi-x tiers — the modern
# "2xl / 3xl / 4xl" scheme (the type grid already labels them that way).
# Resolved to the canonical token below; stored verbatim, so a file keeps
# whichever form was written.
_SIZE_ALIASES = {"2xl": "xxlarge", "3xl": "xxxlarge", "4xl": "xxxxlarge"}
ARROW_LABEL_FONT_SIZES = {"": 10, "small": 8, "large": 13, "xlarge": 18, "xxlarge": 24, "xxxlarge": 32}

# ── Sizes ────────────────────────────────────────────────────────

BOX_RADIUS = 8
BOX_BORDER_WIDTH = 2
ARROW_WIDTH = 2
ARROWHEAD_SIZE = 10
ANNOTATION_ARROW_COLOR = QColor("#8A8580")
ANNOTATION_ARROW_WIDTH = 1

# Connector thickness scales with the size of the nodes it links, so a
# high-level diagram reads as a hierarchy: big containers get heavier arrows,
# small inner children stay light. Width is referenced to a default-sized box
# (min dimension == CONNECTOR_REF_SIZE → ARROW_WIDTH) and grows sub-linearly.
CONNECTOR_REF_SIZE = 80
CONNECTOR_WIDTH_MIN = 1.5
CONNECTOR_WIDTH_MAX = 9.0

DEFAULT_BOX_W = 160
DEFAULT_BOX_H = 80
MIN_BOX_SIZE = 20
HANDLE_SIZE = 11

# ── Minimap ──────────────────────────────────────────────────────

MINIMAP_MAX_W = 360
MINIMAP_MAX_H = 240
MINIMAP_MARGIN = 12
MINIMAP_BG = QColor(40, 40, 40, 180)
MINIMAP_VIEWPORT_COLOR = QColor(255, 255, 255, 60)
MINIMAP_BORDER_COLOR = QColor(80, 80, 80, 200)
MINIMAP_STATS_FONT_SIZE = 10
MINIMAP_STATS_COLOR = QColor(170, 170, 170)
MINIMAP_TIER_COLORS = [
    QColor(127, 185, 127),  # Simple — green
    QColor(201, 184, 78),   # Moderate — yellow
    QColor(212, 136, 58),   # Intricate — orange
    QColor(199, 80, 80),    # Dense — red
]
MINIMAP_INFO_COLOR = QColor(106, 159, 181)  # #6A9FB5 accent
MINIMAP_CONNECTOR_COLOR = QColor(180, 180, 180, 110)  # neutral, low alpha — density only
MINIMAP_CAMERA_COLOR = QColor(106, 159, 181)   # RTS camera frame — the minimap's own accent (#6A9FB5)
MINIMAP_GRID_COLOR = QColor(150, 142, 128, 24)   # faint warm-neutral grid
MINIMAP_SELECT_COLOR = QColor(255, 196, 87)   # selected-element glow ring — warm amber, distinct from the blue camera

# ── Complexity heatmap ──────────────────────────────────────────
HEATMAP_STOPS = [
    (0.00, QColor("#5B8FA8")),  # cold: muted steel blue
    (0.25, QColor("#6BAA8A")),  # sage green
    (0.50, QColor("#C4B555")),  # warm gold
    (0.75, QColor("#D4804E")),  # Grafli accent orange
    (1.00, QColor("#C75050")),  # hot: warm red
]
HEATMAP_BG = QColor("#1E1E2E")
HEATMAP_GRID_COLOR = QColor("#2A2A3A")
HEATMAP_CONTENT_BORDER = QColor("#3A3A4A")
HEATMAP_COLD_ALPHA = 0.30
HEATMAP_HOT_ALPHA = 0.95
HEATMAP_NOTE_OPACITY = 0.15
HEATMAP_BORDER_DARKEN = 125
HEATMAP_GLOW_THRESHOLD = 0.5
HEATMAP_GLOW_BLUR = 15
HEATMAP_TEXT_COLOR = QColor("#FFFFFF")
HEATMAP_EQUAL_HEAT = 0.5
HEATMAP_LEGEND_W = 120
HEATMAP_LEGEND_H = 8
HEATMAP_LEGEND_MARGIN = 6

# ── Zen overlay ──────────────────────────────────────────────────
ZEN_DIM_COLOR = QColor(180, 175, 168, 160)
ZEN_PANEL_BG = QColor("#F5F2ED")
ZEN_PANEL_BORDER = QColor("#CDC8BF")
ZEN_PANEL_WIDTH = 480
ZEN_TEXT_COLOR = QColor("#403A30")
ZEN_TITLE_COLOR = QColor("#004578")
ZEN_HINT_COLOR = QColor("#8A8580")

# ── Zen markdown editor ──────────────────────────────────────────
ZEN_MD_MAX_WIDTH = 700          # default content-column width (user-adjustable)
ZEN_MD_MAX_WIDTH_MIN = 360      # narrowest the column can step to
ZEN_MD_MAX_WIDTH_MAX = 1400     # widest (further clamped to the window)
ZEN_MD_WIDTH_STEP = 80          # per-keystroke width increment
ZEN_MD_BG = QColor("#EEE5D0")
ZEN_MD_HEADING_SIZES = {1: 22, 2: 18, 3: 15}
ZEN_MD_CODE_BG = QColor("#EDE9E3")
ZEN_MD_LINK_COLOR = QColor("#004578")
ZEN_MD_MUTED_ALPHA = 100
ZEN_MD_SYNTAX_COLOR = QColor("#B8B3AB")
ZEN_MD_FONT_SIZE = 16
ZEN_MD_FONT_SIZE_MIN = 10
ZEN_MD_FONT_SIZE_MAX = 32
# Modal card: width hugs the text column, height takes most of the window.
# Card chrome strips (the area outside the canvas) get the dim wash so the
# graph canvas itself stays fully saturated.
ZEN_MD_CARD_INNER_PAD_H = 64
ZEN_MD_CARD_INNER_PAD_V = 40
ZEN_MD_CARD_H_RATIO = 0.85
ZEN_MD_CARD_RADIUS = 12
ZEN_MD_DIM_COLOR = QColor(0, 0, 0, 115)         # chrome — full wash
ZEN_MD_CANVAS_DIM_COLOR = QColor(0, 0, 0, 165)  # canvas — strong step-back
# Light, muted-red marker behind a commented span in the rendered read view —
# translucent so it composites over the warm paper as a soft highlighter wash
# that accompanies the zen style without shouting.
ZEN_MD_COMMENT_HL = QColor(199, 92, 78, 72)

# Suggestion (track-changes) styling in the rendered read view. Removed text is
# struck through in muted red (it stays in the body mono font); added text is
# written in the handwriting note font in zen blue — so an edit reads as a
# proposal pencilled over the typeset prose. A long rewrite drops the handwriting
# (hard to read in bulk) for the body font over a faint blue wash instead.
ZEN_MD_SUGGEST_DEL = QColor("#C53030")
ZEN_MD_SUGGEST_ADD = QColor("#2B6CB0")
ZEN_MD_SUGGEST_ADD_WASH = QColor(43, 108, 176, 40)
ZEN_MD_SUGGEST_LONG = 80   # added-text length above which we use the wash, not hand

# ── Side panel ───────────────────────────────────────────────────
SIDE_PANEL_WIDTH = 180
SIDE_PANEL_BG = QColor("#F5F2ED")
SIDE_PANEL_BORDER = QColor("#CDC8BF")
SIDE_PANEL_SECTION_COLOR = QColor("#8A8580")
SIDE_PANEL_BTN_HOVER = QColor("#E8E4DD")
SIDE_PANEL_BTN_ACTIVE = QColor("#D5D0C8")
SIDE_PANEL_SHORTCUT_COLOR = QColor("#B8B3AB")
SIDE_PANEL_TOGGLE_SIZE = 28
SIDE_PANEL_TOGGLE_BG = QColor(245, 242, 237, 200)
SIDE_PANEL_TOGGLE_BORDER = QColor("#CDC8BF")
SIDE_PANEL_TOGGLE_MARGIN = 8

# ── Glyph picker ─────────────────────────────────────────────────
GLYPH_PICKER_BG = QColor(47, 52, 55, 242)
GLYPH_PICKER_HIGHLIGHT = QColor("#4A6A7A")
GLYPH_PICKER_BADGE = QColor("#6A9FB5")

# ── Layout ────────────────────────────────────────────────────────
LAYOUT_LAYER_GAP = 40   # px between layers (edge-to-edge)
LAYOUT_NODE_GAP = 20    # px between nodes within a layer
LAYOUT_PADDING = 20     # px padding inside parent box

# ── Sequences & cycles ───────────────────────────────────────────

_SIZE_SEQUENCE = ["small", "", "large", "xlarge", "xxlarge", "xxxlarge", "4xl"]
# Fine-grained size ladder that box/note text-size cycling steps through.
# Stored numerically (e.g. textsize="16"); legacy named sizes still resolve.
_SIZE_LADDER = [8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 24, 28, 32, 40, 48, 56, 64, 72]
_BOX_STYLE_CYCLE = ["", "flat"]
_ARROW_STYLE_CYCLE = ["", "thick", "dashed", "dotted"]


def resolve_textsize_px(textsize: str, default_key: str) -> int:
    """Resolve a box/note ``textsize`` token to a font size.

    Accepts a numeric size string (e.g. "16"), a named size
    ("small"/"large"/…), a short alias ("2xl"/"3xl"/"4xl"), or "" / unknown
    which falls back to ``default_key`` in ``BOX_FONT_SIZES`` (use "small" for
    a parent header, "" for a normal node default).
    """
    if textsize:
        if textsize.isdigit():
            return max(1, int(textsize))
        textsize = _SIZE_ALIASES.get(textsize, textsize)
        if textsize in BOX_FONT_SIZES:
            return BOX_FONT_SIZES[textsize]
    return BOX_FONT_SIZES[default_key]


def step_textsize_px(px: int, direction: int) -> int:
    """Next ladder size up (+1) or down (-1) from ``px`` (a font size) — always moves."""
    if direction > 0:
        return next((v for v in _SIZE_LADDER if v > px), _SIZE_LADDER[-1])
    return next((v for v in reversed(_SIZE_LADDER) if v < px), _SIZE_LADDER[0])


# ── Modifier helpers ─────────────────────────────────────────────

_SIGNIFICANT_MODS = (
    Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
)

_CTRL_MOD = (
    Qt.KeyboardModifier.MetaModifier
    if sys.platform == "darwin"
    else Qt.KeyboardModifier.ControlModifier
)

_UNDO_LIMIT = 50

# ── Mode enum ────────────────────────────────────────────────────


class Mode(enum.Enum):
    SELECT = "select"
    RECT = "rect"
    TEXT = "text"
    CONNECT = "connect"
