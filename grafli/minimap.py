"""Minimap rendering mixin for GrafliView."""

from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen

from grafli.constants import (
    BOX_BORDER,
    FONT_FAMILY,
    MINIMAP_BG,
    MINIMAP_BORDER_COLOR,
    MINIMAP_CAMERA_COLOR,
    MINIMAP_CONNECTOR_COLOR,
    MINIMAP_GRID_COLOR,
    MINIMAP_INFO_COLOR,
    MINIMAP_MARGIN,
    MINIMAP_MAX_H,
    MINIMAP_MAX_W,
    MINIMAP_STATS_COLOR,
    MINIMAP_STATS_FONT_SIZE,
    MINIMAP_TIER_COLORS,
    NOTE_DISCUSSION_COLOR,
    NOTE_PEN_COLOR,
    NOTE_QUESTION_COLOR,
    NOTE_TASK_COLOR,
    _resolve_color,
)

_RE_SPEAKER = re.compile(r"^([A-Z][A-Za-z0-9_-]{0,15}): ", re.MULTILINE)

_TIER_LABELS = ("Simple", "Moderate", "Intricate", "Dense")


def _box_depth_order(boxes):
    """Return ``boxes`` ordered by parent-chain depth (top-level first).

    Parents must paint before children so the minimap's solid fill
    doesn't hide nested boxes (parents are usually declared after
    their children in `.grafli` files).

    Cyclic parent refs are tolerated — the chain walk bails on
    revisits and the offending box gets a stable but arbitrary depth.
    """
    by_id = {b.id: b for b in boxes}

    def depth(box):
        d = 0
        cur = box
        seen = {cur.id}
        while cur.parent and cur.parent in by_id and cur.parent not in seen:
            cur = by_id[cur.parent]
            seen.add(cur.id)
            d += 1
        return d

    return sorted(boxes, key=depth)


class MinimapMixin:
    """Mixin providing minimap rendering and click-to-navigate.

    Expects the host class to have: _minimap_visible, _minimap_rect,
    _minimap_panel_rect, _minimap_scene_rect, _board, _note_items,
    viewport(), mapToScene().
    """

    def _compute_graph_stats(self) -> dict:
        """Compute node/edge/cyclomatic stats for the current board."""
        boxes = self._board.boxes
        arrows = self._board.arrows
        n = len(boxes)
        e = len(arrows)

        # Connected components via BFS (undirected)
        ids = {b.id for b in boxes}
        adj: dict[str, set[str]] = {bid: set() for bid in ids}
        for a in arrows:
            if a.from_id in adj and a.to_id in adj:
                adj[a.from_id].add(a.to_id)
                adj[a.to_id].add(a.from_id)
        visited: set[str] = set()
        components = 0
        for bid in ids:
            if bid not in visited:
                components += 1
                stack = [bid]
                while stack:
                    cur = stack.pop()
                    if cur in visited:
                        continue
                    visited.add(cur)
                    stack.extend(adj[cur] - visited)

        cyclomatic = e - n + 2 * components if n > 0 else 0

        # Fuzzy label: tier = max(node_tier, cyclomatic_tier)
        n_tier = 0 if n <= 8 else (1 if n <= 20 else (2 if n <= 40 else 3))
        c_tier = 0 if cyclomatic <= 3 else (1 if cyclomatic <= 8 else (2 if cyclomatic <= 15 else 3))
        tier = max(n_tier, c_tier)
        label = _TIER_LABELS[tier]

        return {"n": n, "e": e, "c": cyclomatic, "label": label, "tier": tier}

    def _draw_minimap(self, painter: QPainter):
        """Draw the minimap overlay. Call from drawForeground."""
        if not self._minimap_visible or not self._board:
            return
        if not self._board.boxes and not self._board.notes:
            return

        painter.resetTransform()
        vp = self.viewport().rect()

        # Compute scene bounding rect of all boxes + notes with padding
        rects = []
        for box in self._board.boxes:
            rects.append(QRectF(box.x, box.y, box.w, box.h))
        for note in self._board.notes:
            ni = self._note_items.get(note.id)
            if ni:
                br = ni.boundingRect()
                rects.append(QRectF(note.x, note.y, br.width(), br.height()))
        if not rects:
            return
        scene_rect = rects[0]
        for r in rects[1:]:
            scene_rect = scene_rect.united(r)
        scene_rect = scene_rect.adjusted(-40, -40, 40, 40)
        self._minimap_scene_rect = scene_rect

        # Fit into minimap dimensions preserving aspect ratio
        aspect = scene_rect.width() / max(scene_rect.height(), 1)
        if aspect > MINIMAP_MAX_W / MINIMAP_MAX_H:
            mw = MINIMAP_MAX_W
            mh = mw / max(aspect, 0.01)
        else:
            mh = MINIMAP_MAX_H
            mw = mh * aspect

        # Compute stats text height for unified panel
        if not self._graph_stats:
            self._graph_stats = self._compute_graph_stats()
        stats = self._graph_stats

        stats_font = QFont(FONT_FAMILY, MINIMAP_STATS_FONT_SIZE)
        painter.setFont(stats_font)
        fm = painter.fontMetrics()
        stats_line_h = fm.height()
        stats_gap = 6
        panel_pad = 8

        hint_font = QFont(FONT_FAMILY, 9)
        painter.setFont(hint_font)
        hint_line_h = painter.fontMetrics().height()
        hint_gap = 4
        painter.setFont(stats_font)

        # Panel dimensions: stats header + gap + minimap + gap + hint footer
        panel_h = panel_pad + stats_line_h + stats_gap + mh + hint_gap + hint_line_h + panel_pad
        panel_w = mw + panel_pad * 2
        panel_x = vp.width() - panel_w - MINIMAP_MARGIN
        panel_y = vp.height() - panel_h - MINIMAP_MARGIN
        panel_rect = QRectF(panel_x, panel_y, panel_w, panel_h)
        self._minimap_panel_rect = panel_rect

        # Minimap content area inside the panel
        mx = panel_x + panel_pad
        my = panel_y + panel_pad + stats_line_h + stats_gap
        self._minimap_rect = QRectF(mx, my, mw, mh)

        # Draw unified panel background
        painter.setPen(QPen(MINIMAP_BORDER_COLOR, 1))
        painter.setBrush(QBrush(MINIMAP_BG))
        painter.drawRoundedRect(panel_rect, 6, 6)

        # ── Stats line inside panel header ──
        stats_text = f"N:{stats['n']}  E:{stats['e']}  C:{stats['c']}"
        label_text = stats["label"]
        separator = " \u00b7 "

        stats_baseline = panel_y + panel_pad + fm.ascent()

        painter.setFont(stats_font)
        painter.setPen(QPen(MINIMAP_STATS_COLOR))
        stats_w = fm.horizontalAdvance(stats_text)
        painter.drawText(QPointF(mx, stats_baseline), stats_text)

        sep_x = mx + stats_w
        sep_w = fm.horizontalAdvance(separator)
        painter.drawText(QPointF(sep_x, stats_baseline), separator)

        label_x = sep_x + sep_w
        tier_color = MINIMAP_TIER_COLORS[stats["tier"]]
        painter.setPen(QPen(tier_color))
        painter.drawText(QPointF(label_x, stats_baseline), label_text)

        # Info circle (right-aligned in panel header)
        info_r = 7
        info_cx = mx + mw - info_r - 1
        info_cy = stats_baseline - fm.ascent() / 2
        info_rect = QRectF(info_cx - info_r, info_cy - info_r,
                           info_r * 2, info_r * 2)
        self._minimap_info_rect = info_rect

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(MINIMAP_INFO_COLOR))
        painter.drawEllipse(info_rect)

        info_font = QFont(FONT_FAMILY, 9)
        info_font.setBold(True)
        painter.setFont(info_font)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(info_rect, Qt.AlignmentFlag.AlignCenter, "i")

        # ── Minimap content ──
        sx = mw / scene_rect.width()
        sy = mh / scene_rect.height()

        # Faint tactical grid under everything — RTS radar terrain feel.
        self._draw_minimap_grid(painter)

        # Draw connectors first (under boxes/notes) — single neutral colour
        # gives a density read of the graph without competing with the
        # element markers drawn on top.
        elem_centers: dict[str, tuple[float, float]] = {}
        for box in self._board.boxes:
            cx = mx + (box.x - scene_rect.x() + box.w / 2) * sx
            cy = my + (box.y - scene_rect.y() + box.h / 2) * sy
            elem_centers[box.id] = (cx, cy)
        for note in self._board.notes:
            ni = self._note_items.get(note.id)
            br = ni.boundingRect() if ni is not None else None
            half_w = br.width() / 2 if br is not None else 10
            half_h = br.height() / 2 if br is not None else 10
            cx = mx + (note.x - scene_rect.x() + half_w) * sx
            cy = my + (note.y - scene_rect.y() + half_h) * sy
            elem_centers[note.id] = (cx, cy)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        connector_color = MINIMAP_CONNECTOR_COLOR
        connector_dim = QColor(connector_color)
        connector_dim.setAlpha(40)
        any_dim = bool(getattr(self, "_search_dimmed_ids", set()))
        for arrow in self._board.arrows:
            src = elem_centers.get(arrow.from_id)
            dst = elem_centers.get(arrow.to_id)
            if src is None or dst is None or src == dst:
                continue
            painter.setPen(QPen(connector_dim if any_dim else connector_color, 1))
            painter.drawLine(QPointF(src[0], src[1]), QPointF(dst[0], dst[1]))

        # Dimmed-id set fed by the search filter (and reusable by other
        # filters later). Items in this set render at low alpha so the user
        # can still see where they are while highlighted hits stand out.
        dimmed_ids: set[str] = getattr(self, "_search_dimmed_ids", set()) or set()
        dim_alpha = 50

        # Draw boxes — top-level parents first so nested children
        # render on top instead of being covered by the parent's fill.
        painter.setPen(Qt.PenStyle.NoPen)
        for box in _box_depth_order(self._board.boxes):
            color_hex = _resolve_color(box.color) if box.color else ""
            if color_hex:
                c = QColor(color_hex)
            else:
                c = QColor(BOX_BORDER)
            if box.id in dimmed_ids:
                c = QColor(c)
                c.setAlpha(dim_alpha)
            painter.setBrush(QBrush(c))
            bx = mx + (box.x - scene_rect.x()) * sx
            by = my + (box.y - scene_rect.y()) * sy
            bw = max(box.w * sx, 2)
            bh = max(box.h * sy, 2)
            painter.drawRect(QRectF(bx, by, bw, bh))

        # Draw notes as small markers
        from grafli.items import note_prefix as _note_prefix
        for note in self._board.notes:
            p = _note_prefix(note.text)
            if p is not None:
                color = NOTE_TASK_COLOR if p[0] == "T:" else NOTE_QUESTION_COLOR
            elif len(set(_RE_SPEAKER.findall(note.text))) >= 2:
                color = NOTE_DISCUSSION_COLOR
            else:
                color = NOTE_PEN_COLOR
            if note.id in dimmed_ids:
                color = QColor(color)
                color.setAlpha(dim_alpha)
            nx = mx + (note.x - scene_rect.x()) * sx
            ny = my + (note.y - scene_rect.y()) * sy
            # Scale to the note's rendered size, like boxes, so a big note
            # reads as a big marker instead of a fixed square.
            ni = self._note_items.get(note.id)
            if ni is not None:
                br = ni.boundingRect()
                nw = max(br.width() * sx, 2)
                nh = max(br.height() * sy, 2)
            else:
                nw = nh = max(3, 20 * sx)
            self._draw_minimap_note(painter, QRectF(nx, ny, nw, nh), color,
                                    dimmed=note.id in dimmed_ids)

        # Camera box — RTS-style: faint fill, thin outline, glowing corner
        # brackets that read as the on-screen "camera".
        vp_scene = self.mapToScene(vp).boundingRect()
        vx = mx + (vp_scene.x() - scene_rect.x()) * sx
        vy = my + (vp_scene.y() - scene_rect.y()) * sy
        vw = vp_scene.width() * sx
        vh = vp_scene.height() * sy
        vp_rect = QRectF(vx, vy, vw, vh).intersected(self._minimap_rect)
        self._draw_minimap_camera(painter, vp_rect)

        # HUD corner brackets framing the radar.
        frame = QColor(MINIMAP_CAMERA_COLOR)
        frame.setAlpha(120)
        self._corner_brackets(painter, self._minimap_rect, 9, [(frame, 1.4)])

        # ── F1 Help hint in bottom-left of panel ──
        hint_font = QFont(FONT_FAMILY, 9)
        painter.setFont(hint_font)
        painter.setPen(QPen(MINIMAP_STATS_COLOR))
        hint_y = panel_y + panel_h - panel_pad
        painter.drawText(QPointF(mx, hint_y), "F1 Help")

    def _draw_minimap_note(self, painter, rect, accent, *, dimmed=False):
        """Draw a note marker as a light 'card' with an accent border and a
        few short text lines — so notes read as text at a glance and stand
        out from the solid box markers. ``accent`` already carries any dim
        alpha applied by the caller.
        """
        # Too small for a card: a solid accent dot keeps it visible.
        if rect.width() < 10 or rect.height() < 8:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(accent))
            painter.drawRect(rect)
            return

        card = QColor("#F4F1EA")
        if dimmed:
            card.setAlpha(50)
        painter.setBrush(QBrush(card))
        painter.setPen(QPen(accent, 1))
        painter.drawRoundedRect(rect, 2, 2)

        # Text lines suggesting prose; widths vary for a texty rhythm.
        inset = 2.5
        gap = 3.0
        fracs = (0.85, 0.6, 0.75, 0.5, 0.8)
        y = rect.top() + inset + 1.0
        i = 0
        while y <= rect.bottom() - inset and i < 8:
            line_w = (rect.width() - 2 * inset) * fracs[i % len(fracs)]
            painter.drawLine(QPointF(rect.left() + inset, y),
                             QPointF(rect.left() + inset + line_w, y))
            y += gap
            i += 1

    def _draw_minimap_grid(self, painter):
        """Faint regular grid across the radar — RTS terrain texture."""
        r = self._minimap_rect
        if r.isNull():
            return
        painter.save()
        painter.setClipRect(r)
        painter.setPen(QPen(MINIMAP_GRID_COLOR, 1))
        step = 28.0
        x = r.left() + step
        while x < r.right():
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            x += step
        y = r.top() + step
        while y < r.bottom():
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            y += step
        painter.restore()

    def _corner_brackets(self, painter, rect, length, pens):
        """Draw inward L-brackets at each corner of ``rect``.

        ``pens`` is a list of ``(QColor, width)`` drawn back-to-front, so a
        wide low-alpha pen followed by a thin bright one yields a glow.
        """
        size = min(length, rect.width() / 2, rect.height() / 2)
        if size < 1:
            return
        corners = (
            (rect.left(), rect.top(), 1, 1),
            (rect.right(), rect.top(), -1, 1),
            (rect.left(), rect.bottom(), 1, -1),
            (rect.right(), rect.bottom(), -1, -1),
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for color, width in pens:
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for x, y, dx, dy in corners:
                painter.drawLine(QPointF(x, y), QPointF(x + dx * size, y))
                painter.drawLine(QPointF(x, y), QPointF(x, y + dy * size))

    def _draw_minimap_camera(self, painter, rect):
        """RTS camera box: faint fill, thin outline, glowing corner brackets."""
        if rect.isNull() or rect.width() < 1 or rect.height() < 1:
            return
        cam = MINIMAP_CAMERA_COLOR
        fill = QColor(cam)
        fill.setAlpha(26)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill))
        painter.drawRect(rect)
        outline = QColor(cam)
        outline.setAlpha(110)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(outline, 1))
        painter.drawRect(rect)
        glow = QColor(cam)
        glow.setAlpha(70)
        self._corner_brackets(painter, rect, 12, [(glow, 4.0), (QColor(cam), 1.6)])

    def _minimap_viewport_rect(self) -> QRectF:
        """Compute the viewport indicator rect in minimap (widget) coords."""
        mr = self._minimap_rect
        sr = self._minimap_scene_rect
        if mr.isNull() or sr.isNull():
            return QRectF()
        sx = mr.width() / sr.width()
        sy = mr.height() / sr.height()
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        vx = mr.x() + (vp_scene.x() - sr.x()) * sx
        vy = mr.y() + (vp_scene.y() - sr.y()) * sy
        vw = vp_scene.width() * sx
        vh = vp_scene.height() * sy
        return QRectF(vx, vy, vw, vh).intersected(mr)

    def _minimap_to_scene(self, minimap_pos: QPointF) -> QPointF:
        """Map a minimap widget position to scene coordinates."""
        mr = self._minimap_rect
        sr = self._minimap_scene_rect
        rx = (minimap_pos.x() - mr.x()) / mr.width()
        ry = (minimap_pos.y() - mr.y()) / mr.height()
        return QPointF(sr.x() + rx * sr.width(),
                       sr.y() + ry * sr.height())

    def _minimap_press(self, event_position) -> bool:
        """Handle press on minimap: info button, drag viewport, or click-to-jump."""
        if not self._minimap_visible:
            return False

        # Info button hit-test (inside panel header)
        info_rect = getattr(self, "_minimap_info_rect", None)
        if info_rect and info_rect.contains(event_position):
            self._show_graph_stats_dialog()
            return True

        # Click inside minimap content area → navigate
        if not self._minimap_rect.isNull() and self._minimap_rect.contains(event_position):
            pass  # fall through to viewport drag / click-to-jump below
        elif not self._minimap_panel_rect.isNull() and self._minimap_panel_rect.contains(event_position):
            return True  # consume click on panel header / padding
        else:
            return False

        vp_ind = self._minimap_viewport_rect()
        if not vp_ind.isNull() and vp_ind.contains(event_position):
            self._minimap_dragging = True
            center = vp_ind.center()
            self._minimap_drag_offset = QPointF(
                event_position.x() - center.x(),
                event_position.y() - center.y(),
            )
        else:
            self.centerOn(self._minimap_to_scene(event_position))
        return True

    def _minimap_move(self, event_position) -> bool:
        """Handle drag on minimap viewport indicator."""
        if not self._minimap_dragging:
            return False
        adjusted = QPointF(
            event_position.x() - self._minimap_drag_offset.x(),
            event_position.y() - self._minimap_drag_offset.y(),
        )
        self.centerOn(self._minimap_to_scene(adjusted))
        return True

    def _minimap_release(self) -> bool:
        """End minimap viewport drag."""
        if not self._minimap_dragging:
            return False
        self._minimap_dragging = False
        return True
