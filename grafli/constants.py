"""Shared constants, enums, and helpers for the grafli app."""

from __future__ import annotations

import enum
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


# ── Colors ───────────────────────────────────────────────────────
#
# Colour *values* live in grafli.theme, which swaps them at runtime; this
# module keeps only the theme-independent vocabulary — the token names the
# author picks from, and the sizes/fonts everything is laid out with.

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
MINIMAP_STATS_FONT_SIZE = 10

# ── Complexity heatmap ──────────────────────────────────────────
HEATMAP_COLD_ALPHA = 0.30
HEATMAP_HOT_ALPHA = 0.95
HEATMAP_NOTE_OPACITY = 0.15
HEATMAP_BORDER_DARKEN = 125
HEATMAP_GLOW_THRESHOLD = 0.5
HEATMAP_GLOW_BLUR = 15
HEATMAP_EQUAL_HEAT = 0.5
HEATMAP_LEGEND_W = 120
HEATMAP_LEGEND_H = 8
HEATMAP_LEGEND_MARGIN = 6

# ── Zen overlay ──────────────────────────────────────────────────
ZEN_PANEL_WIDTH = 480

# ── Side panel ───────────────────────────────────────────────────
SIDE_PANEL_WIDTH = 180
SIDE_PANEL_TOGGLE_SIZE = 28
SIDE_PANEL_TOGGLE_MARGIN = 8

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
_ARROW_STYLE_CYCLE = ["", "dashed", "dotted"]       # line pattern only


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
