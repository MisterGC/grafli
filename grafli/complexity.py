"""Complexity heatmap mixin for GrafliView."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
)

from grafli.constants import (
    BOX_BORDER_WIDTH,
    FONT_FAMILY,
    HEATMAP_BG,
    HEATMAP_BORDER_DARKEN,
    HEATMAP_COLD_ALPHA,
    HEATMAP_EQUAL_HEAT,
    HEATMAP_GLOW_BLUR,
    HEATMAP_GLOW_THRESHOLD,
    HEATMAP_HOT_ALPHA,
    HEATMAP_LEGEND_H,
    HEATMAP_LEGEND_MARGIN,
    HEATMAP_LEGEND_W,
    HEATMAP_NOTE_OPACITY,
    HEATMAP_STOPS,
    HEATMAP_TEXT_COLOR,
    MINIMAP_MARGIN,
    MINIMAP_STATS_FONT_SIZE,
    SCENE_BG,
)
from grafli.items import ArrowLineItem, LabelItem


class ComplexityMixin:
    """Mixin providing complexity heatmap rendering.

    Expects the host class to have: _board, _box_items, _note_items,
    _arrow_items, _complexity_active, _complexity_node_heat,
    _complexity_saved, _minimap_visible, _minimap_rect, viewport().
    """

    def _compute_node_heat(self) -> dict[str, float]:
        """Degree centrality per box, normalized 0.0-1.0."""
        if not self._board or not self._board.boxes:
            return {}

        degree: dict[str, int] = {b.id: 0 for b in self._board.boxes}
        for arrow in self._board.arrows:
            if arrow.from_id in degree:
                degree[arrow.from_id] += 1
            if arrow.to_id in degree:
                degree[arrow.to_id] += 1

        max_deg = max(degree.values()) if degree else 0
        if max_deg == 0:
            return {bid: 0.0 for bid in degree}

        # All-equal case
        if min(degree.values()) == max_deg:
            return {bid: HEATMAP_EQUAL_HEAT for bid in degree}

        return {bid: d / max_deg for bid, d in degree.items()}

    @staticmethod
    def _heat_to_color(heat: float) -> QColor:
        """Interpolate the 5-stop gradient at the given heat value."""
        heat = max(0.0, min(1.0, heat))
        stops = HEATMAP_STOPS
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if heat <= t1:
                frac = (heat - t0) / (t1 - t0) if t1 > t0 else 0.0
                r = c0.red() + (c1.red() - c0.red()) * frac
                g = c0.green() + (c1.green() - c0.green()) * frac
                b = c0.blue() + (c1.blue() - c0.blue()) * frac
                return QColor(int(r), int(g), int(b))
        return QColor(stops[-1][1])

    def _apply_complexity_heatmap(self):
        """Color boxes/arrows by degree centrality."""
        self._complexity_node_heat = self._compute_node_heat()
        heat = self._complexity_node_heat
        if not heat:
            return

        # Dark background
        self._saved_bg_brush = QBrush(self._scene.backgroundBrush())
        self._scene.setBackgroundBrush(QBrush(HEATMAP_BG))

        # Save original box state
        saved = []
        for box_id, item in self._box_items.items():
            saved.append((
                item,
                QPen(item.pen()),
                QBrush(item.brush()),
                QColor(item._label.defaultTextColor()),
                item.graphicsEffect(),
            ))

            h = heat.get(box_id, 0.0)
            c = self._heat_to_color(h)

            fill = QColor(c)
            alpha = HEATMAP_COLD_ALPHA + (HEATMAP_HOT_ALPHA - HEATMAP_COLD_ALPHA) * h
            fill.setAlphaF(alpha)
            item.setBrush(QBrush(fill))
            item.setPen(QPen(c.darker(HEATMAP_BORDER_DARKEN), BOX_BORDER_WIDTH))

            text_color = QColor(HEATMAP_TEXT_COLOR)
            text_alpha = 0.5 + 0.5 * h
            text_color.setAlphaF(text_alpha)
            item._label.setDefaultTextColor(text_color)

            if h > HEATMAP_GLOW_THRESHOLD:
                glow = QGraphicsDropShadowEffect()
                glow.setColor(c)
                glow.setBlurRadius(HEATMAP_GLOW_BLUR)
                glow.setOffset(0, 0)
                item.setGraphicsEffect(glow)

        self._complexity_saved = saved

        # Dim notes
        for item in self._note_items.values():
            item.setOpacity(HEATMAP_NOTE_OPACITY)

        # Color arrows by max endpoint heat (skip LabelItems)
        for gfx in self._arrow_items:
            if isinstance(gfx, LabelItem):
                continue
            arrow = gfx.data(0)
            if arrow is None:
                continue
            from_h = heat.get(arrow.from_id, 0.0)
            to_h = heat.get(arrow.to_id, 0.0)
            edge_heat = max(from_h, to_h)
            edge_color = self._heat_to_color(edge_heat)

            if isinstance(gfx, (QGraphicsLineItem, ArrowLineItem)):
                pen = QPen(gfx.pen())
                pen.setColor(edge_color)
                gfx.setPen(pen)
            elif isinstance(gfx, QGraphicsPolygonItem):
                gfx.setPen(QPen(edge_color, gfx.pen().widthF()))
                gfx.setBrush(QBrush(edge_color))

        self._update_complexity_status()
        self.viewport().update()

    def _clear_complexity_heatmap(self):
        """Restore original box/note/arrow appearance."""
        self._complexity_active = False

        # Restore background
        if hasattr(self, '_saved_bg_brush'):
            self._scene.setBackgroundBrush(self._saved_bg_brush)
            del self._saved_bg_brush

        # Restore boxes
        for item, pen, brush, text_color, effect in self._complexity_saved:
            item.setPen(pen)
            item.setBrush(brush)
            item._label.setDefaultTextColor(text_color)
            item.setGraphicsEffect(effect)

        self._complexity_saved.clear()
        self._complexity_node_heat.clear()

        # Restore notes
        for item in self._note_items.values():
            item.setOpacity(1.0)

        # Redraw arrows to restore original colors
        self._redraw_arrows()

        self._update_complexity_status()
        self.viewport().update()

    def _update_complexity_status(self):
        """Show/clear ANALYSIS in the status focus label."""
        window = self.window()
        if not hasattr(window, '_status_focus'):
            return
        if self._complexity_active:
            window._status_focus.setText("ANALYSIS")
        elif not self._focus_active:
            window._status_focus.setText("")

    def _draw_complexity_legend(self, painter: QPainter):
        """Horizontal gradient bar above minimap stats line."""
        if not self._complexity_active or not self._minimap_visible:
            return
        if not self._board:
            return

        painter.resetTransform()
        vp = self.viewport().rect()

        # Position: above minimap stats line
        mr = self._minimap_rect
        if mr.isNull():
            return

        font = QFont(FONT_FAMILY, MINIMAP_STATS_FONT_SIZE - 1)
        painter.setFont(font)
        fm = painter.fontMetrics()

        stats_y = mr.y() - 6
        title_text = "COMPLEXITY"
        title_w = fm.horizontalAdvance(title_text)

        legend_y = stats_y - fm.height() - HEATMAP_LEGEND_MARGIN
        bar_y = legend_y + fm.ascent() + 3

        bar_x = mr.x()
        bar_w = HEATMAP_LEGEND_W
        bar_h = HEATMAP_LEGEND_H

        # Title centered above bar
        title_x = bar_x + (bar_w - title_w) / 2
        painter.setPen(QPen(QColor(200, 200, 200)))
        painter.drawText(QPointF(title_x, legend_y + fm.ascent()), title_text)

        # Gradient bar
        grad = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
        for pos, color in HEATMAP_STOPS:
            grad.setColorAt(pos, color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        # Low / High labels
        label_font = QFont(FONT_FAMILY, MINIMAP_STATS_FONT_SIZE - 2)
        painter.setFont(label_font)
        lfm = painter.fontMetrics()
        label_y = bar_y + bar_h + lfm.ascent() + 2

        painter.setPen(QPen(QColor(150, 150, 150)))
        painter.drawText(QPointF(bar_x, label_y), "Low")
        high_text = "High"
        high_w = lfm.horizontalAdvance(high_text)
        painter.drawText(QPointF(bar_x + bar_w - high_w, label_y), high_text)
