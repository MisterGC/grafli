"""Board navigation for GrafliView (mixin).

Getting around a large board: jump-to mode with two-letter hint labels and
off-screen badges, label search with live filtering, the Ctrl+O / Ctrl+I
navigation jumplist, and Alt-held graph navigation along connectors. Moves
the camera via the host's animated-zoom and selection machinery.
"""

from __future__ import annotations


from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)
from grafli import theme
from grafli.constants import FONT_FAMILY
from grafli.format import Arrow
from grafli.items import BoxItem, ImageItem, NoteItem


_JUMP_KEYS = "asdfjklghqweruioptyzxcvbnm"


class NavigationMixin:
    # ── Jump-to mode (Ctrl+J) ──

    def _start_jump_mode(self):
        if not self._board:
            return
        self._clear_jump_labels()

        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        vp_center = viewport_rect.center()

        # Collect ALL jump targets, split into visible and off-screen
        visible: list[tuple[BoxItem | NoteItem | ImageItem | Arrow, QPointF]] = []
        offscreen: list[tuple[BoxItem | NoteItem | ImageItem | Arrow, QPointF]] = []

        for item in self._box_items.values():
            center = item.sceneBoundingRect().center()
            if viewport_rect.intersects(item.sceneBoundingRect()):
                visible.append((item, center))
            else:
                offscreen.append((item, center))
        for item in self._note_items.values():
            center = item.sceneBoundingRect().center()
            if viewport_rect.intersects(item.sceneBoundingRect()):
                visible.append((item, center))
            else:
                offscreen.append((item, center))
        for item in self._image_items.values():
            center = item.sceneBoundingRect().center()
            if viewport_rect.intersects(item.sceneBoundingRect()):
                visible.append((item, center))
            else:
                offscreen.append((item, center))
        # Arrow midpoints
        for arrow in self._board.arrows:
            from_elem = self._board.box_by_id(arrow.from_id) or self._board.note_by_id(arrow.from_id)
            to_elem = self._board.box_by_id(arrow.to_id) or self._board.note_by_id(arrow.to_id)
            if from_elem and to_elem:
                fr = self._elem_rect(from_elem)
                tr = self._elem_rect(to_elem)
                mid = QPointF(
                    (fr[0] + fr[2] / 2 + tr[0] + tr[2] / 2) / 2,
                    (fr[1] + fr[3] / 2 + tr[1] + tr[3] / 2) / 2,
                )
                if viewport_rect.contains(mid):
                    visible.append((arrow, mid))
                else:
                    offscreen.append((arrow, mid))

        # Sort off-screen by distance from viewport center
        offscreen.sort(key=lambda t: (
            (t[1].x() - vp_center.x()) ** 2 + (t[1].y() - vp_center.y()) ** 2
        ))

        if not visible and not offscreen:
            return

        # Unified label assignment: all items in one list (visible first)
        all_targets = visible + offscreen
        total = len(all_targets)
        keys = _JUMP_KEYS
        self._jump_map = {}
        self._jump_label_items = {}

        if total <= len(keys):
            # Single-letter labels
            labels = [keys[i] for i in range(total)]
            self._jump_two_letter = False
        else:
            # Two-letter labels from _JUMP_KEYS combinations
            labels = []
            for i in range(total):
                first = keys[i // len(keys) % len(keys)]
                second = keys[i % len(keys)]
                labels.append(first + second)
            self._jump_two_letter = True

        zoom = self._current_zoom()
        base_size = 14
        min_screen_px = 14
        scene_size = min(base_size * 3, max(base_size, min_screen_px / zoom))
        font = QFont(FONT_FAMILY, round(scene_size))
        font.setBold(True)

        # Render visible labels on the canvas
        n_visible = len(visible)
        for i, (label_text, (target, center)) in enumerate(zip(labels, all_targets)):
            self._jump_map[label_text] = target
            if i < n_visible:
                self._render_jump_label(label_text, target, center, font, scene_size, base_size)

        # Show off-screen badge list at viewport bottom
        off_labels = labels[n_visible:]
        off_targets = offscreen
        if off_targets:
            self._render_offscreen_badge(off_labels, off_targets)

        self._jump_active = True
        self._jump_prefix = ""

    def _render_jump_label(self, label_text, target, center, font, scene_size, base_size):
        """Render a single jump label on the canvas."""
        # Only boxes carry a fill brush; notes, images and arrows fall back to
        # the default badge colour (calling .brush() on them would crash).
        if isinstance(target, BoxItem):
            bg_color = target.brush().color()
            if bg_color.alphaF() < 0.1:
                bg_color = QColor(theme.BOOKMARK_BG)
            else:
                bg_color = bg_color.darker(130)
        else:
            bg_color = QColor(theme.BOOKMARK_BG)

        text_color = theme.ink_on(bg_color).name()

        text_item = QGraphicsSimpleTextItem(label_text)
        text_item.setFont(font)
        text_item.setBrush(QBrush(QColor(text_color)))
        tr = text_item.boundingRect()

        pad = 3 * scene_size / base_size
        bg = QGraphicsRectItem(
            center.x() - tr.width() / 2 - pad,
            center.y() - tr.height() / 2 - pad,
            tr.width() + 2 * pad,
            tr.height() + 2 * pad,
        )
        bg.setBrush(QBrush(bg_color))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        bg.setZValue(1000)
        self._scene.addItem(bg)
        self._jump_labels.append(bg)

        text_item.setPos(center.x() - tr.width() / 2, center.y() - tr.height() / 2)
        text_item.setZValue(1001)
        self._scene.addItem(text_item)
        self._jump_labels.append(text_item)

        self._jump_label_items[label_text] = [bg, text_item]

    def _ancestry_path(self, target) -> list[str]:
        """Return labels from top-level ancestor down to target."""
        if isinstance(target, Arrow):
            return [f"{target.from_id}\u2192{target.to_id}"]
        elem = self._item_elem(target)
        chain: list[str] = []
        current_id = elem.parent
        while current_id and self._board:
            parent = self._board.box_by_id(current_id)
            if not parent:
                break
            chain.append(parent.label or parent.id)
            current_id = parent.parent
        chain.reverse()  # root-first
        if isinstance(target, BoxItem):
            chain.append(elem.label or elem.id)
        elif isinstance(target, NoteItem):
            chain.append(elem.text[:15])
        else:  # ImageItem
            chain.append(elem.image_path.rsplit("/", 1)[-1] or elem.id)
        return chain

    def _render_offscreen_badge(self, off_labels, offscreen, prefix_filter=""):
        """Show hierarchical badge list of off-screen targets at viewport bottom."""
        vp = self.viewport().rect()
        scene_bottom = self.mapToScene(QPointF(vp.width() / 2, vp.height() - 30).toPoint())

        # Build entries with ancestry paths
        entries: list[tuple[str, object, list[str]]] = []
        for label_text, (target, _center) in zip(off_labels, offscreen):
            if prefix_filter and not label_text.startswith(prefix_filter):
                continue
            path = self._ancestry_path(target)
            entries.append((label_text, target, path))

        if not entries:
            return

        # Group by top-level ancestor (first element of path)
        groups: dict[str, list[tuple[str, list[str]]]] = {}
        for label_text, _target, path in entries:
            root = path[0] if path else ""
            groups.setdefault(root, []).append((label_text, path))

        # Build display string: group by root, show breadcrumbs
        group_parts: list[str] = []
        shown = 0
        for root, members in groups.items():
            if shown >= 10:
                remaining = sum(len(m) for m in list(groups.values())[list(groups.keys()).index(root):])
                group_parts.append(f"...+{remaining}")
                break
            if len(members) == 1:
                lbl, path = members[0]
                display_lbl = lbl[len(prefix_filter):] if prefix_filter else lbl
                group_parts.append(f"[{display_lbl}] {' \u203a '.join(path)}")
                shown += 1
            else:
                items: list[str] = []
                for lbl, path in members:
                    if shown >= 10:
                        leftover = len(members) - len(items)
                        if leftover > 0:
                            items.append(f"...+{leftover}")
                        break
                    display_lbl = lbl[len(prefix_filter):] if prefix_filter else lbl
                    # Show path without the root (already in group header)
                    sub = " \u203a ".join(path[1:]) if len(path) > 1 else path[0]
                    items.append(f"[{display_lbl}] {sub}")
                    shown += 1
                group_parts.append(f"{root}: {'   '.join(items)}")

        display = " | ".join(group_parts)
        badge = QGraphicsTextItem(display)
        font = QFont(FONT_FAMILY, 9)
        badge.setFont(font)
        badge.setDefaultTextColor(QColor(theme.OVERLAY_FG))
        badge.setZValue(10001)
        br = badge.boundingRect()

        bg = QGraphicsRectItem()
        bg_color = QColor(theme.OVERLAY_BG)
        bg_color.setAlphaF(0.85)
        bg.setBrush(QBrush(bg_color))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        bg.setZValue(10000)

        bx = scene_bottom.x() - br.width() / 2
        by = scene_bottom.y()
        badge.setPos(bx, by)
        pad = 6
        bg.setRect(bx - pad, by - pad, br.width() + pad * 2, br.height() + pad * 2)

        self._scene.addItem(bg)
        self._scene.addItem(badge)
        self._jump_labels.append(bg)
        self._jump_labels.append(badge)

        # Track badge items for all labels rendered in this badge
        for label_text, _target, _path in entries:
            self._jump_label_items.setdefault(label_text, []).extend([bg, badge])

    def _handle_jump_key(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._clear_jump_labels()
            return

        text = event.text().lower()
        if not text or not text.isalpha():
            self._clear_jump_labels()
            return

        self._jump_prefix += text

        if self._jump_prefix in self._jump_map:
            target = self._jump_map[self._jump_prefix]
            self._push_nav_snapshot()
            self._clear_jump_labels()
            self._scene.clearSelection()
            if isinstance(target, Arrow):
                self._select_arrow(target)
                from_box = self._board.box_by_id(target.from_id) if self._board else None
                to_box = self._board.box_by_id(target.to_id) if self._board else None
                if from_box and to_box:
                    mid = QPointF(
                        (from_box.x + from_box.w / 2 + to_box.x + to_box.w / 2) / 2,
                        (from_box.y + from_box.h / 2 + to_box.y + to_box.h / 2) / 2,
                    )
                    vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
                    if not vp_scene.contains(mid):
                        r = QRectF(mid.x() - 50, mid.y() - 50, 100, 100)
                        self._animate_to_rect(r.adjusted(-60, -60, 60, 60))
                    else:
                        self.centerOn(mid)
            else:
                target.setSelected(True)
                # Animate to off-screen targets
                if isinstance(target, BoxItem):
                    b = target.box
                    target_rect = QRectF(b.x, b.y, b.w, b.h)
                else:
                    target_rect = target.sceneBoundingRect()
                vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
                if not vp_scene.contains(target_rect):
                    padding = max(60, target_rect.width() * 0.15, target_rect.height() * 0.15)
                    self._animate_to_rect(target_rect.adjusted(-padding, -padding, padding, padding))
                else:
                    self.centerOn(target)
            return

        has_match = any(
            lbl.startswith(self._jump_prefix) for lbl in self._jump_map
        )
        if not has_match:
            self._clear_jump_labels()
            return

        # First-keystroke refinement for two-letter mode
        if self._jump_two_letter and len(self._jump_prefix) == 1:
            self._refine_jump_labels(self._jump_prefix)

    def _refine_jump_labels(self, prefix):
        """After first keystroke in two-letter mode: remove non-matching labels,
        replace matching label text with just the second character, and
        re-render off-screen badge with only matching entries."""
        removed_items: set[int] = set()

        # Remove non-matching on-canvas labels, update matching ones
        for lbl, items in list(self._jump_label_items.items()):
            if not lbl.startswith(prefix):
                for item in items:
                    item_id = id(item)
                    if item_id not in removed_items:
                        self._scene.removeItem(item)
                        removed_items.add(item_id)
                        if item in self._jump_labels:
                            self._jump_labels.remove(item)
                del self._jump_label_items[lbl]
            else:
                # Update text to show only the second character
                for item in items:
                    if isinstance(item, QGraphicsSimpleTextItem):
                        item.setText(lbl[1:])

        # Remove old off-screen badge (it's shared across labels)
        # Collect all badge items (QGraphicsTextItem at z=10001, QGraphicsRectItem at z=10000)
        badge_items_to_remove: list[QGraphicsItem] = []
        for item in self._jump_labels:
            if isinstance(item, QGraphicsTextItem) and item.zValue() == 10001:
                badge_items_to_remove.append(item)
            elif isinstance(item, QGraphicsRectItem) and item.zValue() == 10000:
                badge_items_to_remove.append(item)

        for item in badge_items_to_remove:
            item_id = id(item)
            if item_id not in removed_items:
                self._scene.removeItem(item)
                removed_items.add(item_id)
            if item in self._jump_labels:
                self._jump_labels.remove(item)

        # Re-render off-screen badge showing only matching entries
        # Rebuild offscreen list from jump_map
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        off_labels: list[str] = []
        off_targets: list[tuple[object, QPointF]] = []
        for lbl, target in self._jump_map.items():
            if not lbl.startswith(prefix):
                continue
            if isinstance(target, Arrow):
                if not self._board:
                    continue
                from_elem = self._board.box_by_id(target.from_id) or self._board.note_by_id(target.from_id)
                to_elem = self._board.box_by_id(target.to_id) or self._board.note_by_id(target.to_id)
                if from_elem and to_elem:
                    fr = self._elem_rect(from_elem)
                    tr = self._elem_rect(to_elem)
                    mid = QPointF(
                        (fr[0] + fr[2] / 2 + tr[0] + tr[2] / 2) / 2,
                        (fr[1] + fr[3] / 2 + tr[1] + tr[3] / 2) / 2,
                    )
                    if not viewport_rect.contains(mid):
                        off_labels.append(lbl)
                        off_targets.append((target, mid))
            elif isinstance(target, (BoxItem, NoteItem, ImageItem)):
                if not viewport_rect.intersects(target.sceneBoundingRect()):
                    center = target.sceneBoundingRect().center()
                    off_labels.append(lbl)
                    off_targets.append((target, center))

        if off_targets:
            self._render_offscreen_badge(off_labels, off_targets, prefix_filter=prefix)

    def _clear_jump_labels(self):
        for item in self._jump_labels:
            self._scene.removeItem(item)
        self._jump_labels.clear()
        self._jump_map.clear()
        self._jump_label_items.clear()
        self._jump_prefix = ""
        self._jump_active = False
        self._jump_two_letter = False

    # ── Search by label (/) ──

    def _start_search(self):
        # Search is exclusive with the other dim filters (focus / complexity /
        # arrow-dim). Clear them before opening so the visual stack stays
        # legible.
        if self._focus_active:
            self._clear_focus_filter()
        if self._complexity_active:
            self._clear_complexity_heatmap()
        if self._arrows_dimmed:
            self._toggle_arrows_dimmed()
        self._search_active = True
        self._animate_fade(self._search_badge_opacity, 1.0,
                           self._set_search_badge_opacity)
        self._search_text = ""
        self._search_matches.clear()
        self._search_index = 0
        self._update_search_badge()

    def _handle_search_key(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_search()
            return
        if event.key() == Qt.Key.Key_Return:
            self._accept_search()
            return
        if event.key() == Qt.Key.Key_Backspace:
            self._search_text = self._search_text[:-1]
        elif event.key() == Qt.Key.Key_Tab:
            if self._search_matches:
                step = -1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
                self._search_index = (self._search_index + step) % len(self._search_matches)
                self._focus_current_match(animate=True)
                self._update_search_badge()
            return
        else:
            ch = event.text()
            if ch and ch.isprintable():
                self._search_text += ch
        self._update_search_results()
        self._update_search_badge()

    def _update_search_results(self):
        self._search_matches.clear()
        self._search_index = 0
        if not self._search_text:
            self._scene.clearSelection()
            self._clear_search_filter()
            return
        query = self._search_text.lower()
        for item in self._box_items.values():
            if query in item.box.label.lower() or query in item.box.id.lower():
                self._search_matches.append(item)
        for item in self._note_items.values():
            if query in item.note.text.lower():
                self._search_matches.append(item)
        self._apply_search_filter()
        if self._search_matches:
            self._focus_current_match(animate=False)
        else:
            self._scene.clearSelection()

    def _apply_search_filter(self):
        """Dim every item that isn't a match. Arrows always dim — per the
        agreed UX, only matched items themselves stay full opacity, not the
        connectors between them.
        """
        match_ids: set[str] = set()
        for m in self._search_matches:
            if isinstance(m, BoxItem):
                match_ids.add(m.box.id)
            elif isinstance(m, NoteItem):
                match_ids.add(m.note.id)

        dim = 0.08
        dimmed: set[str] = set()
        for box_id, item in self._box_items.items():
            on = box_id in match_ids
            opacity = 1.0 if on else dim
            item.setOpacity(opacity)
            item._label.setOpacity(opacity)
            if not on:
                dimmed.add(box_id)
        for note_id, item in self._note_items.items():
            on = note_id in match_ids
            item.setOpacity(1.0 if on else dim)
            if not on:
                dimmed.add(note_id)
        for gfx in self._arrow_items:
            gfx.setOpacity(dim)

        self._search_filter_active = True
        self._search_dimmed_ids = dimmed
        self.viewport().update()

    def _clear_search_filter(self):
        if not self._search_filter_active:
            return
        for item in self._box_items.values():
            item.setOpacity(1.0)
            item._label.setOpacity(1.0)
        for item in self._note_items.values():
            item.setOpacity(1.0)
        arrow_opacity = 0.08 if self._arrows_dimmed else 1.0
        for gfx in self._arrow_items:
            gfx.setOpacity(arrow_opacity)
        self._search_filter_active = False
        self._search_dimmed_ids = set()
        self.viewport().update()

    def _focus_current_match(self, animate: bool = True):
        """Move selection + viewport to the current match.

        Search cycling always lands at 100% zoom regardless of where the
        user was before — consistent zoom across the result set makes hits
        easier to compare than auto-fitting each individual rect.
        """
        if not self._search_matches:
            return
        target = self._search_matches[self._search_index]
        self._scene.clearSelection()
        target.setSelected(True)
        if isinstance(target, BoxItem):
            b = target.box
            center = QRectF(b.x, b.y, b.w, b.h).center()
        else:
            center = target.sceneBoundingRect().center()
        if animate:
            self._animate_to_zoom_and_center(1.0, center)
        else:
            self.setTransform(QTransform().scale(1.0, 1.0))
            self.centerOn(center)
            self._update_status_zoom()

    def _accept_search(self):
        """Enter: dismiss the input badge but keep the dim filter active so
        the user can pan/zoom around the highlighted result set. Esc clears
        both."""
        if self._search_matches:
            self._push_nav_snapshot()
            self._focus_current_match(animate=True)
        self._search_active = False
        self._remove_search_badge()

    def _cancel_search(self):
        self._search_active = False
        self._search_text = ""
        self._search_matches.clear()
        self._remove_search_badge()
        self._clear_search_filter()

    def _set_search_badge_opacity(self, value: float):
        self._search_badge_opacity = value
        self.viewport().update()

    def _update_search_badge(self):
        # The badge is now a viewport overlay (see _draw_search_badge),
        # so updating it is just a viewport repaint.
        self.viewport().update()

    def _remove_search_badge(self):
        # Fade the overlay out (callers have already flipped _search_active off;
        # the draw keeps painting while opacity > 0, then stops).
        self._animate_fade(self._search_badge_opacity, 0.0,
                           self._set_search_badge_opacity)

    def _draw_search_badge(self, painter: QPainter):
        """Top-center viewport overlay shown while the search input is open.

        Drawn in viewport coordinates so it doesn't pan/zoom with the scene
        like the previous QGraphicsTextItem implementation did.
        """
        o = max(0.0, min(1.0, self._search_badge_opacity))
        if not self._search_active and o <= 0.0:
            return

        count = len(self._search_matches)
        display = f"/{self._search_text}"
        if self._search_text:
            if count:
                display += f"  [{self._search_index + 1}/{count}]"
            else:
                display += "  [no matches]"
        hint = "Tab/⇧Tab cycle · Enter keep filter · Esc clear"

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        vp = self.viewport().rect()
        font = QFont(FONT_FAMILY, 12)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(display)
        text_h = fm.height()

        hint_font = QFont(FONT_FAMILY, 9)
        painter.setFont(hint_font)
        hfm = painter.fontMetrics()
        hint_w = hfm.horizontalAdvance(hint)
        hint_h = hfm.height()

        pad = 8
        gap = 4
        panel_w = max(text_w, hint_w) + pad * 2
        panel_h = text_h + gap + hint_h + pad * 2
        panel_x = (vp.width() - panel_w) / 2
        panel_y = 10

        bg = QColor(theme.OVERLAY_BG)
        bg.setAlphaF(0.92 * o)
        hair = QColor(theme.OVERLAY_FG)
        hair.setAlpha(int(40 * o))
        painter.setPen(QPen(hair, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(panel_x, panel_y, panel_w, panel_h), 6, 6)

        painter.setFont(font)
        painter.setPen(QPen(QColor(255, 255, 255, int(255 * o))))
        painter.drawText(
            QPointF(panel_x + (panel_w - text_w) / 2,
                    panel_y + pad + fm.ascent()),
            display,
        )
        painter.setFont(hint_font)
        painter.setPen(QPen(QColor(200, 200, 200, int(180 * o))))
        painter.drawText(
            QPointF(panel_x + (panel_w - hint_w) / 2,
                    panel_y + pad + text_h + gap + hfm.ascent()),
            hint,
        )
        painter.restore()

    # ── Navigation jumplist (Ctrl+O / Ctrl+I) ──

    def _push_nav_snapshot(self):
        """Capture current viewport rect before a navigation action."""
        vp_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        # Deduplicate near-identical consecutive positions
        if self._nav_index >= 0 and self._nav_index < len(self._nav_stack):
            prev = self._nav_stack[self._nav_index]
            dx = abs(prev.center().x() - vp_rect.center().x())
            dy = abs(prev.center().y() - vp_rect.center().y())
            if dx < 5 and dy < 5:
                return
        # Truncate forward history
        self._nav_stack = self._nav_stack[:self._nav_index + 1]
        self._nav_stack.append(vp_rect)
        if len(self._nav_stack) > self._NAV_STACK_CAP:
            self._nav_stack.pop(0)
        self._nav_index = len(self._nav_stack) - 1

    def _nav_back(self):
        """Ctrl+O: jump to previous viewport in nav stack."""
        if self._nav_index <= 0:
            return
        # Save current position if at the end
        if self._nav_index == len(self._nav_stack) - 1:
            vp_rect = self.mapToScene(self.viewport().rect()).boundingRect()
            prev = self._nav_stack[self._nav_index]
            dx = abs(prev.center().x() - vp_rect.center().x())
            dy = abs(prev.center().y() - vp_rect.center().y())
            if dx >= 5 or dy >= 5:
                self._nav_stack.append(vp_rect)
                # Don't change _nav_index yet, we just appended current
                # so the back target stays the same
        self._nav_index -= 1
        self._animate_to_rect(self._nav_stack[self._nav_index])

    def _nav_forward(self):
        """Ctrl+I: jump to next viewport in nav stack."""
        if self._nav_index >= len(self._nav_stack) - 1:
            return
        self._nav_index += 1
        self._animate_to_rect(self._nav_stack[self._nav_index])

    def _selection_scene_rect(self) -> QRectF | None:
        """Union of the scene rects of the selected boxes/notes/images, or None."""
        rect: QRectF | None = None
        for it in self._scene.selectedItems():
            if isinstance(it, (BoxItem, NoteItem, ImageItem)):
                r = it.sceneBoundingRect()
                rect = QRectF(r) if rect is None else rect.united(r)
        return rect

    def _toggle_focus_zoom(self):
        """gz: zoom the current selection to fill the viewport; press again to
        fly back to the previous overview.

        Re-pressing after changing the selection re-focuses on the new
        selection while keeping the original return view, so a final press
        always lands you back where you started.
        """
        if not self._board:
            return
        sel_ids = {self._item_id(i) for i in self._scene.selectedItems()
                   if isinstance(i, (BoxItem, NoteItem, ImageItem))}

        if self._focus_return is not None:
            # Already focused: re-focus on a new selection, else return.
            if sel_ids and sel_ids != self._focus_target_ids:
                rect = self._selection_scene_rect()
                if rect is not None:
                    self._focus_target_ids = sel_ids
                    pad = max(40.0, rect.width() * 0.08, rect.height() * 0.08)
                    self._animate_to_rect(rect.adjusted(-pad, -pad, pad, pad))
                    return
            ret = self._focus_return
            self._focus_return = None
            self._focus_target_ids = set()
            self._animate_to_rect(ret)
            return

        # Not focused: need a selection to zoom into.
        rect = self._selection_scene_rect()
        if rect is None:
            self._record_shortcut("gz → select an element first")
            return
        self._focus_return = self.mapToScene(self.viewport().rect()).boundingRect()
        self._focus_target_ids = sel_ids
        pad = max(40.0, rect.width() * 0.08, rect.height() * 0.08)
        self._animate_to_rect(rect.adjusted(-pad, -pad, pad, pad))

    def _select_parent_and_zoom(self):
        """P key: select parent box, zoom to it if not fully visible."""
        if not self._board:
            return

        # Single box selection only
        selected = self._scene.selectedItems()
        if len(selected) != 1 or not isinstance(selected[0], BoxItem):
            return

        self._push_nav_snapshot()
        box = selected[0].box
        if not box.parent:
            self._zoom_to_fit()
            return

        parent_item = self._box_items.get(box.parent)
        if not parent_item:
            return

        # Select parent
        self._scene.clearSelection()
        parent_item.setSelected(True)

        # Zoom only if parent is not fully visible
        pb = parent_item.box
        parent_rect = QRectF(pb.x, pb.y, pb.w, pb.h)
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        if not vp_scene.contains(parent_rect):
            padding = max(60, parent_rect.width() * 0.15, parent_rect.height() * 0.15)
            self._animate_to_rect(parent_rect.adjusted(-padding, -padding, padding, padding))

    def _select_first_child(self):
        """F key: select first child of current box, sorted by (y, x)."""
        if not self._board:
            return
        selected = self._scene.selectedItems()
        if len(selected) != 1 or not isinstance(selected[0], BoxItem):
            return
        box = selected[0].box
        children = [
            b for b in self._board.boxes
            if b.parent == box.id
        ]
        if not children:
            return
        self._push_nav_snapshot()
        children.sort(key=lambda b: (b.y, b.x))
        target = children[0]
        target_item = self._box_items.get(target.id)
        if not target_item:
            return
        self._scene.clearSelection()
        target_item.setSelected(True)
        target_rect = QRectF(target.x, target.y, target.w, target.h)
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        if not vp_scene.contains(target_rect):
            padding = max(60, target_rect.width() * 0.15, target_rect.height() * 0.15)
            self._animate_to_rect(target_rect.adjusted(-padding, -padding, padding, padding))

    def _cycle_sibling(self, direction: int):
        """Tab / Shift+Tab: cycle through ALL sibling boxes at same level."""
        if not self._board:
            return
        selected = self._scene.selectedItems()
        if len(selected) != 1 or not isinstance(selected[0], BoxItem):
            return
        self._push_nav_snapshot()
        box = selected[0].box
        siblings = [
            b for b in self._board.boxes
            if b.parent == box.parent
        ]
        siblings.sort(key=lambda b: (b.y, b.x))
        if len(siblings) <= 1:
            return
        idx = next(i for i, b in enumerate(siblings) if b.id == box.id)
        target = siblings[(idx + direction) % len(siblings)]
        target_item = self._box_items.get(target.id)
        if not target_item:
            return
        self._scene.clearSelection()
        target_item.setSelected(True)
        target_rect = QRectF(target.x, target.y, target.w, target.h)
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        if not vp_scene.contains(target_rect):
            padding = max(60, target_rect.width() * 0.15, target_rect.height() * 0.15)
            self._animate_to_rect(target_rect.adjusted(-padding, -padding, padding, padding))

    # ── Graph navigation (Alt held) ──

    _GRAPH_NAV_KEYS = "hjkluiop"

    def _enter_graph_nav(self, source_item):
        """Show jump labels on graph-edge connectors from the selected node.

        Follows only graph edges (annotation links are skipped) and reaches any
        graph node — boxes and note nodes alike.
        """
        if not self._board:
            return
        self._exit_graph_nav()  # clean up any previous state
        node_id = self._item_id(source_item)
        src_center = source_item.sceneBoundingRect().center()
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()

        # Find graph-edge connectors to other nodes (annotation links skipped)
        targets: list[tuple[str, Arrow]] = []  # (target_id, arrow)
        for arrow in self._board.arrows:
            if not self._is_graph_edge(arrow):
                continue
            target_id = None
            if arrow.from_id == node_id:
                target_id = arrow.to_id
            elif arrow.to_id == node_id:
                target_id = arrow.from_id
            if target_id is None:
                continue
            target_item = (self._box_items.get(target_id)
                           or self._note_items.get(target_id)
                           or self._image_items.get(target_id))
            if target_item is None:
                continue
            # Only connectors whose midpoint is visible in the viewport
            tgt_center = target_item.sceneBoundingRect().center()
            mid = QPointF((src_center.x() + tgt_center.x()) / 2,
                          (src_center.y() + tgt_center.y()) / 2)
            if viewport_rect.contains(mid):
                targets.append((target_id, arrow))

        if len(targets) > 8:
            # Show warning overlay on selected node
            self._show_graph_nav_warning(source_item)
            self._graph_nav_active = True
            return

        if not targets:
            self._graph_nav_active = True
            return

        zoom = self._current_zoom()
        base_size = 14
        min_screen_px = 14
        scene_size = min(base_size * 3, max(base_size, min_screen_px / zoom))
        font = QFont(FONT_FAMILY, round(scene_size))
        font.setBold(True)

        self._graph_nav_map.clear()
        for i, (target_id, arrow) in enumerate(targets):
            if i >= len(self._GRAPH_NAV_KEYS):
                break
            label_key = self._GRAPH_NAV_KEYS[i]
            self._graph_nav_map[label_key] = target_id

            # Position label at connector midpoint
            tgt_item = (self._box_items.get(target_id)
                        or self._note_items.get(target_id))
            tgt_center = tgt_item.sceneBoundingRect().center()
            mid = QPointF((src_center.x() + tgt_center.x()) / 2,
                          (src_center.y() + tgt_center.y()) / 2)

            bg_color = QColor(theme.BOOKMARK_BG)
            text_item = QGraphicsSimpleTextItem(label_key)
            text_item.setFont(font)
            text_item.setBrush(QBrush(theme.ink_on(bg_color)))
            tr = text_item.boundingRect()

            pad = 3 * scene_size / base_size
            bg = QGraphicsRectItem(
                mid.x() - tr.width() / 2 - pad,
                mid.y() - tr.height() / 2 - pad,
                tr.width() + 2 * pad,
                tr.height() + 2 * pad,
            )
            bg.setBrush(QBrush(bg_color))
            bg.setPen(QPen(Qt.PenStyle.NoPen))
            bg.setZValue(10000)
            self._scene.addItem(bg)
            self._graph_nav_labels.append(bg)

            text_item.setPos(mid.x() - tr.width() / 2, mid.y() - tr.height() / 2)
            text_item.setZValue(10001)
            self._scene.addItem(text_item)
            self._graph_nav_labels.append(text_item)

        self._graph_nav_active = True

    def _show_graph_nav_warning(self, source_item: BoxItem):
        """Show warning overlay when node has too many connectors."""
        zoom = self._current_zoom()
        scene_size = min(42, max(14, 14 / zoom))
        font = QFont(FONT_FAMILY, round(scene_size * 0.6))

        br = source_item.sceneBoundingRect()
        text_item = QGraphicsSimpleTextItem("\u26a0 Too many connectors")
        text_item.setFont(font)
        text_item.setBrush(QBrush(theme.ink_on(QColor(theme.ERROR_BG))))
        tr = text_item.boundingRect()

        pad = 6
        bg = QGraphicsRectItem(
            br.center().x() - tr.width() / 2 - pad,
            br.top() - tr.height() - pad * 3,
            tr.width() + 2 * pad,
            tr.height() + 2 * pad,
        )
        bg_color = QColor(theme.ERROR_BG)
        bg_color.setAlphaF(0.9)
        bg.setBrush(QBrush(bg_color))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        bg.setZValue(10000)
        self._scene.addItem(bg)
        self._graph_nav_warning.append(bg)

        text_item.setPos(
            br.center().x() - tr.width() / 2,
            br.top() - tr.height() - pad * 2,
        )
        text_item.setZValue(10001)
        self._scene.addItem(text_item)
        self._graph_nav_warning.append(text_item)

    def _handle_graph_nav_key(self, event):
        """Handle key press while in graph nav mode (Alt held)."""
        if event.key() == Qt.Key.Key_Alt:
            # Alt is still held, ignore repeat
            return
        text = event.text().lower()
        if text in self._graph_nav_map:
            target_id = self._graph_nav_map[text]
            target_item = (self._box_items.get(target_id)
                           or self._note_items.get(target_id))
            if target_item:
                self._push_nav_snapshot()
                self._scene.clearSelection()
                target_item.setSelected(True)
                # Zoom if target not fully visible
                target_rect = target_item.sceneBoundingRect()
                vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
                if not vp_scene.contains(target_rect):
                    padding = max(60, target_rect.width() * 0.15, target_rect.height() * 0.15)
                    self._animate_to_rect(target_rect.adjusted(-padding, -padding, padding, padding))
                # Recompute labels from new position (chainable)
                self._clear_graph_nav_labels()
                self._enter_graph_nav(target_item)

    def _exit_graph_nav(self):
        """Exit graph nav mode, remove all labels."""
        self._clear_graph_nav_labels()
        self._graph_nav_active = False

    def _clear_graph_nav_labels(self):
        """Remove graph nav label graphics items."""
        for item in self._graph_nav_labels:
            self._scene.removeItem(item)
        self._graph_nav_labels.clear()
        self._graph_nav_map.clear()
        for item in self._graph_nav_warning:
            self._scene.removeItem(item)
        self._graph_nav_warning.clear()

