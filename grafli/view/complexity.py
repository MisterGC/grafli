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

from grafli import theme
from grafli.constants import (
    BOX_BORDER_WIDTH,
    FONT_FAMILY,
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
    MINIMAP_MARGIN,
    MINIMAP_STATS_FONT_SIZE,
    resolve_textsize_px,
)
from grafli.items import ArrowLineItem, ClusterHullItem, LabelItem
from grafli.lod import should_collapse, should_collapse_container


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
        stops = theme.HEATMAP_STOPS
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
        self._scene.setBackgroundBrush(QBrush(theme.HEATMAP_BG))

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

            text_color = QColor(theme.HEATMAP_TEXT_COLOR)
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
        for pos, color in theme.HEATMAP_STOPS:
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

    # ── LoD status & aggregation (moved from view.py) ──

    def _update_status_lod(self):
        """Reflect the LoD state in the status bar: off / actively summarizing /
        (blank when on but showing everything at full detail)."""
        window = self.window()
        if not hasattr(window, '_status_lod'):
            return
        aggregating = bool(self._lod_collapsed or self._lod_hulls
                           or self._lod_simplified or self._lod_hidden_notes)
        if not self._lod_enabled:
            window._status_lod.setText("LoD off")
            window._status_lod.setStyleSheet(f"color: {theme.STATUS_DIM.name()};")
        elif aggregating:
            window._status_lod.setText("◧ LoD")
            window._status_lod.setStyleSheet(
                f"color: {theme.FLOWS_ACCENT.name()}; font-weight: bold;")
        else:
            window._status_lod.setText("")

    def _refresh_lod(self):
        """Recompute the Level-of-Detail state at the current zoom.

        The "zoom clock": cheap, reads the live scale and resolves each box into
        one of these states with hysteresis (so scrubbing the zoom doesn't
        flicker):

        * **tile** — a collapsed container with no collapsed ancestor: its
          headline + child-count badge stand in for the whole group.
        * **hidden** — a box inside a collapsed container (subsumed by the tile).
        * **shell** — a leaf whose own label is illegible: a bare coloured box.
        * **cluster** — a parent-less connected component (>=3) whose members are
          all illegible and spatially compact: hidden behind a concave hull.
        * **detailed** — shown as authored.

        Disabled (everything detailed) when LoD is toggled off. Re-routes arrows
        to the surviving tiles / hulls only when the routing actually changes.
        """
        # Consume a pending edit: the structural model is rebuilt here (lazily,
        # at most once per settled gesture or zoom tick) rather than on every
        # mutation, so the graph rebuild stays off the per-frame path.
        if self._lod_dirty:
            self._rebuild_lod_model()
        scale = self._current_zoom()
        model = self._lod
        # A presentation override (flow step / export honouring one) trumps
        # the global toggle: "full" renders everything as authored, "summary"
        # collapses every container to its tile regardless of zoom.
        force_summary = self._present_detail == "summary"
        lod_on = (self._lod_enabled if self._present_detail is None
                  else force_summary)
        # Container aggregation is a zoom-OUT affordance: at 100%+ the board is
        # at (or above) authored size, so everything stays fully detailed. This
        # also guarantees a small-child container (a notes legend, tiny boxes)
        # can always reach detail — the collapse threshold sits above such
        # children's on-screen size, so without this floor the hysteresis would
        # keep them tiled even at full zoom.
        may_collapse = scale < 1.0 or force_summary
        collapsed: set[str] = set()
        if lod_on and may_collapse and model is not None:
            prev_c = self._lod_collapsed
            # Size-driven, per container: each folds when its own children get
            # too small on screen (a small container no longer waits for a large
            # same-level sibling). A cascade guarantee inside collapse_extents
            # still folds the innermost containers first and never folds a parent
            # before a tile it would subsume.
            extents = model.collapse_extents()
            for cid in model.containers:
                if cid not in self._box_items:
                    continue
                if force_summary:
                    collapsed.add(cid)
                    continue
                ext = extents.get(cid, float("inf"))
                if ext == float("inf"):
                    continue
                if should_collapse_container(ext * scale, cid in prev_c):
                    collapsed.add(cid)

        # Outermost collapsed containers become tiles; anything with a collapsed
        # ancestor is hidden inside one.
        tiles: set[str] = set()
        hidden: set[str] = set()
        if model is not None:
            for bid in self._box_items:
                ancestors = model.ancestors(bid)
                if any(a in collapsed for a in ancestors):
                    hidden.add(bid)
                elif bid in collapsed:
                    tiles.add(bid)

        # Leaf shells: visible, non-container leaves whose own label is illegible.
        shells: set[str] = set()
        if lod_on:
            for bid, item in self._box_items.items():
                if bid in hidden or bid in tiles or item._is_parent:
                    continue
                label_px = resolve_textsize_px(item.box.textsize, "") * scale
                if should_collapse(label_px, bid in self._lod_simplified):
                    shells.add(bid)

        # Loose clusters: a parent-less component is hulled (members hidden) once
        # it is spatially compact, has >=3 members, and every member's own label
        # has dropped below the legibility floor (all shells) — the leaf-level
        # equivalent of a container folding when its children get too small to
        # read. Compactness ignores boxes already subsumed by a collapsed tile.
        clusters: dict[tuple, list] = {}
        if lod_on and may_collapse and model is not None:
            for comp in model.components:
                if (len(comp) >= 3 and all(m in shells for m in comp)
                        and self._cluster_compact(comp, hidden)):
                    clusters[tuple(sorted(comp))] = comp
                    shells.difference_update(comp)
                    hidden.update(comp)

        # Notes & images: a note subsumed by a collapsed container is hidden
        # (the tile stands in for it). A standalone note whose own text is
        # illegible doesn't vanish — it paints a 'text here' marker (plate +
        # skeleton bars + accent tick), so nothing is silently lost. Standalone
        # images stay — a shrunk image is still a legible thumbnail.
        hidden_notes: set[str] = set()
        note_shells: set[str] = set()
        for nid, nitem in self._note_items.items():
            if model is not None and any(a in collapsed
                                         for a in model.ancestors(nid)):
                hidden_notes.add(nid)
            elif lod_on:
                px = resolve_textsize_px(nitem.note.textsize, "") * scale
                if should_collapse(px, nid in self._lod_note_shells):
                    note_shells.add(nid)
        hidden_images: set[str] = set()
        if model is not None:
            for iid in self._image_items:
                if any(a in collapsed for a in model.ancestors(iid)):
                    hidden_images.add(iid)

        # Arrow labels are text too: hide one once it's too small to read, the
        # same legibility floor that shells a node label — otherwise a connector
        # caption stays as unreadable specks over nodes already reduced to bars.
        # When hidden the line is drawn unbroken (no leftover label gap), which
        # _redraw_arrows handles off this set — so a crossing forces a redraw.
        prev_labels_hidden = self._lod_arrow_labels_hidden
        arrow_labels_hidden: set = set()
        for it in self._arrow_items:
            if not isinstance(it, LabelItem):
                continue
            a = it.data(0)
            key = (a.from_id, a.to_id) if a is not None else id(it)
            px = resolve_textsize_px(getattr(a, "textsize", ""), "") * scale
            if lod_on and should_collapse(px, key in prev_labels_hidden):
                arrow_labels_hidden.add(key)

        state = (frozenset(collapsed), frozenset(shells), frozenset(clusters),
                 frozenset(hidden_notes), frozenset(note_shells),
                 frozenset(hidden_images), frozenset(arrow_labels_hidden))
        if state == self._lod_state:
            return
        routing_changed = (collapsed != self._lod_collapsed
                           or set(clusters) != set(self._lod_hulls)
                           or arrow_labels_hidden != prev_labels_hidden)
        self._lod_state = state
        self._lod_arrow_labels_hidden = arrow_labels_hidden

        for bid, item in self._box_items.items():
            if bid in hidden:
                item.setVisible(False)
                item._label.setVisible(False)
                # Clear any stale tile/shell state: a box subsumed by an outer
                # tile must not keep reporting as a tile (it would linger as a
                # read-only lock and leave its move flag disabled).
                item.set_lod_tile(None)
                item.set_lod_simplified(False)
                continue
            item.setVisible(True)
            is_shell = bid in shells
            is_tile = bid in tiles
            item.set_lod_simplified(is_shell)
            item.set_lod_tile(model.summary(bid) if is_tile else None)
            # The tile paints its own counter-scaled headline; a shell shows
            # nothing — so the normal label item is hidden in both cases.
            item._label.setVisible(not is_shell and not is_tile)

        for nid, nitem in self._note_items.items():
            hidden = nid in hidden_notes
            nitem.setVisible(not hidden)
            nitem.set_lod_text_marker(not hidden and nid in note_shells)
        for iid, iitem in self._image_items.items():
            iitem.setVisible(iid not in hidden_images)

        self._apply_lod_hulls(clusters)
        self._lod_simplified = shells
        self._lod_collapsed = collapsed
        self._lod_hidden_notes = hidden_notes
        self._lod_note_shells = note_shells
        if routing_changed:
            # Hidden endpoints re-route to their tile/hull; illegible labels
            # drop out and their lines redraw unbroken.
            self._redraw_arrows()
        if self._present_focus_rect is not None:
            # Tiles appearing / elements hiding change what counts as fully
            # framed — recompute the focus fade against the new composition.
            self._apply_presentation_focus()

    def _cluster_compact(self, comp, hidden=frozenset()) -> bool:
        """A component is compact when no *visible* non-member box centre falls
        inside its bounding box — so a hull won't visually swallow unrelated
        nodes. Boxes already subsumed by a collapsed container tile (``hidden``)
        are invisible and must not block the hull: otherwise a loose cluster
        sitting among already-aggregated peers would never get to aggregate
        itself."""
        boxes = [self._box_items[m].box for m in comp if m in self._box_items]
        if not boxes:
            return False
        x0 = min(b.x for b in boxes); y0 = min(b.y for b in boxes)
        x1 = max(b.x + b.w for b in boxes); y1 = max(b.y + b.h for b in boxes)
        member = set(comp)
        for bid, item in self._box_items.items():
            if bid in member or bid in hidden:
                continue
            b = item.box
            cx, cy = b.x + b.w / 2, b.y + b.h / 2
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return False
        return True

    def _apply_lod_hulls(self, clusters: dict[tuple, list]):
        """Create / update / remove cluster hull items to match `clusters`."""
        model = self._lod
        # Drop hulls that are no longer active.
        for key in list(self._lod_hulls):
            if key not in clusters:
                self._scene.removeItem(self._lod_hulls.pop(key))
        # Add hulls that became active.
        for key, comp in clusters.items():
            if key in self._lod_hulls:
                continue
            rects = {m: (self._box_items[m].box.x, self._box_items[m].box.y,
                         self._box_items[m].box.w, self._box_items[m].box.h)
                     for m in comp if m in self._box_items}
            hub = model.component_hub(comp)
            color = self._cluster_color(comp)
            hull = ClusterHullItem(rects, model.component_edges(comp),
                                   model.cluster_pad(comp), model.label_of(hub),
                                   len(comp), color)
            self._scene.addItem(hull)
            self._lod_hulls[key] = hull
        # Rebuild the member -> hull lookup used for arrow re-anchoring.
        self._lod_hull_member = {}
        for key, comp in clusters.items():
            hull = self._lod_hulls[key]
            for m in comp:
                self._lod_hull_member[m] = hull

    def _lod_reroute(self, elem_id: str) -> str:
        """Map an arrow endpoint to its visible tile if it sits in a collapsed
        container; otherwise return it unchanged."""
        if self._lod is None or not self._lod_collapsed:
            return elem_id
        return self._lod.resolve_visible(elem_id, self._lod_collapsed)

    def _cluster_color(self, comp) -> str:
        """Hull colour: the members' shared colour, or a neutral grey when they
        disagree — an honest 'this is a heterogeneous group' instead of picking
        one member's colour and misrepresenting the rest."""
        hexes = set()
        for m in comp:
            it = self._box_items.get(m)
            if it is not None:
                hexes.add(theme.resolve_color(it.box.color))
        hexes.discard(None)
        return hexes.pop() if len(hexes) == 1 else self.LOD_NEUTRAL

    def _toggle_lod(self):
        self._lod_enabled = not self._lod_enabled
        self._refresh_lod()
        self._record_shortcut(
            "level-of-detail ON" if self._lod_enabled else "level-of-detail OFF")

