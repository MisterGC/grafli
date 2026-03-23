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

BOX_FONT_SIZES = {"": 13, "small": 10, "large": 18, "xlarge": 24, "xxlarge": 32, "xxxlarge": 44}
NOTE_FONT_SIZES = {"": 15, "small": 11, "large": 21, "xlarge": 28, "xxlarge": 40, "xxxlarge": 52}
ARROW_LABEL_FONT_SIZES = {"": 10, "small": 8, "large": 13, "xlarge": 18, "xxlarge": 24, "xxxlarge": 32}

# ── Sizes ────────────────────────────────────────────────────────

BOX_RADIUS = 8
BOX_BORDER_WIDTH = 2
ARROW_WIDTH = 2
ARROWHEAD_SIZE = 10
ANNOTATION_ARROW_COLOR = QColor("#8A8580")
ANNOTATION_ARROW_WIDTH = 1

DEFAULT_BOX_W = 160
DEFAULT_BOX_H = 80
MIN_BOX_SIZE = 20
HANDLE_SIZE = 8

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
ZEN_TEXT_COLOR = QColor("#2F3437")
ZEN_TITLE_COLOR = QColor("#004578")
ZEN_HINT_COLOR = QColor("#8A8580")

# ── Glyph picker ─────────────────────────────────────────────────
GLYPH_PICKER_BG = QColor(47, 52, 55, 242)
GLYPH_PICKER_HIGHLIGHT = QColor("#4A6A7A")
GLYPH_PICKER_BADGE = QColor("#6A9FB5")

# ── Layout ────────────────────────────────────────────────────────
LAYOUT_LAYER_GAP = 40   # px between layers (edge-to-edge)
LAYOUT_NODE_GAP = 20    # px between nodes within a layer
LAYOUT_PADDING = 20     # px padding inside parent box

# ── Sequences & cycles ───────────────────────────────────────────

_SIZE_SEQUENCE = ["small", "", "large", "xlarge", "xxlarge", "xxxlarge"]
_BOX_STYLE_CYCLE = ["", "flat"]
_ARROW_STYLE_CYCLE = ["", "thick", "dashed", "dotted"]

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
