"""The map palette's legend on the canvas for GrafliView (mixin).

``Shift+M`` toggles a card in the bottom-left corner listing the palette
entries the board uses (``grafli.legend``). The same switch puts the legend
into the SVG/PNG exports and the PDF slides exported from the app.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QPainter, QPen

from grafli import theme
from grafli.constants import MINIMAP_MARGIN
from grafli.legend import draw_legend, legend_height, legend_width, used_entries

_CARD_PAD = 10
_CARD_TEXT_PX = 13


class LegendMixin:
    """Expects the host class to have: _legend_visible, _map_palette,
    _board."""

    def legend_entries(self) -> list:
        """The map palette's entries this board colours something with."""
        return used_entries(self._board, self._map_palette)

    def _toggle_legend(self):
        self._legend_visible = not self._legend_visible
        if self._legend_visible and not self.legend_entries():
            self.toast("No palette colours on this board", "warn")
        self._record_shortcut(
            f"⇧M → legend {'on' if self._legend_visible else 'off'}")
        self.viewport().update()

    def _draw_palette_legend(self, painter: QPainter):
        """The legend card, bottom left, as wide as its entries need up to
        half the viewport."""
        if not self._legend_visible:
            return
        entries = self.legend_entries()
        if not entries:
            return
        painter.resetTransform()
        vp = self.viewport().rect()
        px = _CARD_TEXT_PX
        inner = min(legend_width(entries, px), vp.width() * 0.5)
        height = legend_height(entries, px, inner)
        card = QRectF(MINIMAP_MARGIN,
                      vp.height() - MINIMAP_MARGIN - height - 2 * _CARD_PAD,
                      inner + 2 * _CARD_PAD, height + 2 * _CARD_PAD)
        painter.setPen(QPen(theme.MINIMAP_BORDER_COLOR, 1))
        painter.setBrush(QBrush(theme.OVERLAY_BG))
        painter.drawRoundedRect(card, 6, 6)
        draw_legend(painter, card.adjusted(_CARD_PAD, _CARD_PAD,
                                           -_CARD_PAD, -_CARD_PAD),
                    entries, px, theme.overlay_ink())
