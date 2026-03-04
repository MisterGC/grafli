"""Shared constants, enums, and helpers for the whiteboard app."""

from __future__ import annotations

import enum
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont


# ── Colors ───────────────────────────────────────────────────────

BOX_FILL = QColor("#E8E4DD")
BOX_BORDER = QColor("#2F3437")
ARROW_COLOR = QColor("#2F3437")
NOTE_COLOR = QColor("#D4BA6A")
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
NOTE_FONT = QFont(NOTE_FONT_FAMILY, 11)
LABEL_FONT = QFont(FONT_FAMILY, 10)

BOX_FONT_SIZES = {"": 13, "small": 10, "large": 18, "xlarge": 24, "xxlarge": 32, "xxxlarge": 44}
NOTE_FONT_SIZES = {"": 11, "small": 9, "large": 15, "xlarge": 21, "xxlarge": 28, "xxxlarge": 40}

# ── Sizes ────────────────────────────────────────────────────────

BOX_RADIUS = 8
BOX_BORDER_WIDTH = 2
ARROW_WIDTH = 2
ARROWHEAD_SIZE = 10

DEFAULT_BOX_W = 160
DEFAULT_BOX_H = 80
MIN_BOX_SIZE = 20
HANDLE_SIZE = 8

# ── Minimap ──────────────────────────────────────────────────────

MINIMAP_MAX_W = 180
MINIMAP_MAX_H = 120
MINIMAP_MARGIN = 12
MINIMAP_BG = QColor(40, 40, 40, 180)
MINIMAP_VIEWPORT_COLOR = QColor(255, 255, 255, 60)
MINIMAP_BORDER_COLOR = QColor(80, 80, 80, 200)

# ── Sequences & cycles ───────────────────────────────────────────

_SIZE_SEQUENCE = ["small", "", "large", "xlarge", "xxlarge", "xxxlarge"]
_ANCHOR_CYCLE = ["", "topleft", "topcenter"]
_BOX_STYLE_CYCLE = ["", "flat"]
_NOTE_STYLE_CYCLE = ["", "mono"]
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
