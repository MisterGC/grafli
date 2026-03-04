"""WhiteboardView — the main canvas view for the whiteboard app."""

from __future__ import annotations

import math

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QTimeLine,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPolygonF,
    QTextCursor,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QMessageBox,
)

from whiteboard.arrows import _aligned_edge_points, _arrowhead_polygon, _box_edge_point, _line_rect_clip
from whiteboard.commands import CommandsMixin
from whiteboard.constants import (
    ARROW_COLOR,
    ARROW_WIDTH,
    BOX_BORDER,
    COLOR_PALETTE,
    CONTENT_BORDER_COLOR,
    DEFAULT_BOX_H,
    DEFAULT_BOX_W,
    FONT_FAMILY,
    GRID_COLOR,
    LABEL_FONT,
    MIN_BOX_SIZE,
    NOTE_COLOR,
    SCENE_BG,
    Mode,
    _ARROW_STYLE_CYCLE,
    _CTRL_MOD,
    _SIGNIFICANT_MODS,
    _resolve_color,
)
from whiteboard.format import Arrow, Board, Box, Note, parse, serialize
from whiteboard.items import ArrowLineItem, BoxItem, LabelItem, NoteItem, ResizeHandle
from whiteboard.minimap import MinimapMixin


# ── Canvas view ─────────────────────────────────────────────────

class WhiteboardView(CommandsMixin, MinimapMixin, QGraphicsView):
    """QGraphicsView with pan/zoom and file-backed board rendering."""

    arrow_update_needed = Signal()
    mode_changed = Signal(Mode)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(SCENE_BG))
        self.setScene(self._scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        self._grid_visible: bool = True
        self.GRID_SPACING = 20

        self._board: Board | None = None
        self._box_items: dict[str, BoxItem] = {}
        self._arrow_items: list[QGraphicsLineItem | QGraphicsPolygonItem | QGraphicsSimpleTextItem] = []
        self._note_items: list[NoteItem] = []
        self._dirty = False

        # Pan state (middle-click always works)
        self._panning = False
        self._pan_start = QPointF()

        # Mode system
        self._mode = Mode.SELECT

        # RECT mode state
        self._rect_preview: QGraphicsRectItem | None = None
        self._rect_origin: QPointF | None = None

        # CONNECT mode state
        self._connect_source: BoxItem | None = None
        self._connect_line: QGraphicsLineItem | None = None

        # Inline text editor
        self._editor: QGraphicsTextItem | None = None
        self._edit_target: BoxItem | NoteItem | None = None

        # Nesting: guard against recursive position propagation
        self._propagating_move = False

        # Undo / Redo
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._pre_move_snapshot: str = ""

        # Copy / Paste clipboard
        self._clipboard_boxes: list[Box] = []
        self._clipboard_notes: list[Note] = []
        self._clipboard_arrows: list[Arrow] = []

        # Reparenting drag highlight
        self._highlight_parent: BoxItem | None = None
        self._highlight_orig_pen: QPen | None = None

        # Jump-to mode state
        self._jump_active = False
        self._jump_labels: list[QGraphicsRectItem | QGraphicsSimpleTextItem] = []
        self._jump_map: dict[str, BoxItem | NoteItem | Arrow] = {}
        self._jump_prefix = ""

        # Arrow selection state
        self._selected_arrow: Arrow | None = None
        self._selected_arrow_items: list[QGraphicsItem] = []

        # Vim-like box mode (style / dimension)
        self._box_mode: str = ""          # "", "style", "dimension"
        self._mode_badge: QGraphicsTextItem | None = None
        self._mode_badge_bg: QGraphicsRectItem | None = None

        # Minimap
        self._minimap_visible: bool = True
        self._minimap_rect: QRectF = QRectF()
        self._minimap_scene_rect: QRectF = QRectF()

        # Animated zoom
        self._zoom_timeline: QTimeLine | None = None
        self._anim_start_center: QPointF = QPointF()
        self._anim_end_center: QPointF = QPointF()
        self._anim_start_zoom: float = 1.0
        self._anim_end_zoom: float = 1.0

        # Search state
        self._search_active = False
        self._search_text = ""
        self._search_matches: list[BoxItem | NoteItem] = []
        self._search_index = 0
        self._search_label: QGraphicsTextItem | None = None
        self._search_label_bg: QGraphicsRectItem | None = None

        self.arrow_update_needed.connect(self._redraw_arrows)
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if self._grid_visible:
            spacing = self.GRID_SPACING
            left = int(rect.left()) - (int(rect.left()) % spacing)
            top = int(rect.top()) - (int(rect.top()) % spacing)
            painter.setPen(QPen(GRID_COLOR, 2.0))
            x = left
            while x <= rect.right():
                y = top
                while y <= rect.bottom():
                    painter.drawPoint(int(x), int(y))
                    y += spacing
                x += spacing

        # Content-area border — always drawn as an orientation aid
        items_rect = self._scene.itemsBoundingRect()
        if not items_rect.isNull():
            border_rect = items_rect.adjusted(-30, -30, 30, 30)
            pen = QPen(CONTENT_BORDER_COLOR, 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(border_rect, 12, 12)

    def drawForeground(self, painter: QPainter, rect: QRectF):
        super().drawForeground(painter, rect)
        self._draw_minimap(painter)

    def toggle_grid(self):
        self._grid_visible = not self._grid_visible
        self.viewport().update()

    @property
    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode):
        self._cancel_interactions()
        self._mode = mode
        self.mode_changed.emit(mode)

        if mode == Mode.SELECT:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._set_items_movable(True)
        elif mode == Mode.RECT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._set_items_movable(False)
        elif mode == Mode.TEXT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.IBeamCursor)
            self._set_items_movable(False)
        elif mode == Mode.CONNECT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._set_items_movable(False)

    def _set_items_movable(self, movable: bool):
        for item in self._box_items.values():
            if movable:
                item.setFlags(
                    item.flags()
                    | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )
            else:
                item.setFlags(
                    item.flags()
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )
        for item in self._note_items:
            if movable:
                item.setFlags(
                    item.flags()
                    | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )
            else:
                item.setFlags(
                    item.flags()
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    & ~QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                )

    def _cancel_interactions(self):
        """Clean up any in-progress mode interactions."""
        self._clear_box_mode()
        self._clear_jump_labels()
        self._cancel_search()
        self._deselect_arrow()
        if self._rect_preview:
            self._scene.removeItem(self._rect_preview)
            self._rect_preview = None
            self._rect_origin = None
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None
            self._connect_source = None
        self._commit_editor()

    # ── Arrow selection ──

    def _select_arrow(self, arrow: Arrow):
        self._deselect_arrow()
        self._scene.clearSelection()
        self._selected_arrow = arrow
        sel_color = QColor("#0178D4")
        for gfx in self._arrow_items:
            if gfx.data(0) is arrow:
                self._selected_arrow_items.append(gfx)
                if isinstance(gfx, (QGraphicsLineItem, ArrowLineItem)):
                    old_pen = gfx.pen()
                    pen = QPen(sel_color, old_pen.widthF() + 1)
                    pen.setStyle(old_pen.style())
                    pen.setCapStyle(old_pen.capStyle())
                    gfx.setPen(pen)
                elif isinstance(gfx, QGraphicsPolygonItem):
                    gfx.setPen(QPen(sel_color, 1))
                    gfx.setBrush(QBrush(sel_color))
                elif isinstance(gfx, QGraphicsSimpleTextItem):
                    gfx.setBrush(QBrush(sel_color))

    def _deselect_arrow(self):
        if not self._selected_arrow:
            return
        for gfx in self._selected_arrow_items:
            if isinstance(gfx, (QGraphicsLineItem, ArrowLineItem)):
                old_pen = gfx.pen()
                pen = QPen(ARROW_COLOR, old_pen.widthF() - 1)
                pen.setStyle(old_pen.style())
                pen.setCapStyle(old_pen.capStyle())
                gfx.setPen(pen)
            elif isinstance(gfx, QGraphicsPolygonItem):
                gfx.setPen(QPen(ARROW_COLOR, 1))
                gfx.setBrush(QBrush(ARROW_COLOR))
            elif isinstance(gfx, QGraphicsSimpleTextItem):
                gfx.setBrush(QBrush(QColor("#2F3437")))
        self._selected_arrow = None
        self._selected_arrow_items.clear()

    def _find_existing_arrow(self, id_a: str, id_b: str) -> Arrow | None:
        """Find an arrow between the unordered pair {id_a, id_b}."""
        if not self._board:
            return None
        for arrow in self._board.arrows:
            if {arrow.from_id, arrow.to_id} == {id_a, id_b}:
                return arrow
        return None

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self):
        self._dirty = True
        window = self.window()
        if hasattr(window, '_file_path'):
            if window._file_path:
                window.setWindowTitle(window._title_for_path(window._file_path, dirty=True))
            window._schedule_autosave()
        self._update_scene_rect()

    def mark_clean(self):
        self._dirty = False
        window = self.window()
        if hasattr(window, '_file_path') and window._file_path:
            window.setWindowTitle(window._title_for_path(window._file_path))

    def _update_scene_rect(self):
        items_rect = self._scene.itemsBoundingRect()
        if items_rect.isNull():
            return
        inflated = items_rect.adjusted(-2000, -2000, 2000, 2000)
        self._scene.setSceneRect(inflated)

    def load_board(self, board: Board):
        self._board = board
        self._rebuild_scene()

    def _rebuild_scene(self):
        self._scene.clear()
        self._box_items.clear()
        self._arrow_items.clear()
        self._note_items.clear()
        self._editor = None
        self._edit_target = None
        self._rect_preview = None
        self._connect_line = None
        self._connect_source = None
        self._selected_arrow = None
        self._selected_arrow_items.clear()

        if not self._board:
            return

        dupe_ids: list[str] = []
        for box in self._board.boxes:
            item = BoxItem(box)
            self._scene.addItem(item)
            if box.id in self._box_items:
                self._scene.removeItem(self._box_items[box.id])
                dupe_ids.append(box.id)
            self._box_items[box.id] = item
            item._auto_grow()

        window = self.window()
        if hasattr(window, "_status_warn"):
            if dupe_ids:
                window._status_warn.setText(
                    f"Duplicate IDs: {', '.join(dupe_ids)}"
                )
            else:
                window._status_warn.setText("")

        for note in self._board.notes:
            item = NoteItem(note)
            self._scene.addItem(item)
            self._note_items.append(item)

        self._update_z_values()

        # Refresh auto-layout now that all parent-child relationships exist
        for item in self._box_items.values():
            item.refresh_auto_layout()

        self._redraw_arrows()
        self._update_z_values()
        self._update_scene_rect()

    def _redraw_arrows(self):
        for item in self._arrow_items:
            self._scene.removeItem(item)
        self._arrow_items.clear()

        if not self._board:
            return

        # Merge opposite arrow pairs (A->B + B->A) into one line.
        # Build directed lookup: (from, to) -> arrow
        directed: dict[tuple[str, str], Arrow] = {}
        merged: set[int] = set()  # indices of arrows consumed by merge
        # Each entry: (from_box_id, to_box_id, draw_head_to, draw_head_from, fwd_arrow, rev_arrow|None)
        render_list: list[tuple[str, str, bool, bool, Arrow, Arrow | None]] = []

        for i, arrow in enumerate(self._board.arrows):
            directed[(arrow.from_id, arrow.to_id)] = arrow

        for i, arrow in enumerate(self._board.arrows):
            if i in merged:
                continue
            reverse_key = (arrow.to_id, arrow.from_id)
            reverse = directed.get(reverse_key)
            if (
                reverse is not None
                and reverse is not arrow
                and not (arrow.head_from and arrow.head_to)
                and not (reverse.head_from and reverse.head_to)
                and id(reverse) not in {id(self._board.arrows[j]) for j in merged}
            ):
                # Merge: combine head flags from both arrows
                merged.add(self._board.arrows.index(reverse))
                render_list.append((
                    arrow.from_id, arrow.to_id,
                    arrow.head_to or reverse.head_from,
                    arrow.head_from or reverse.head_to,
                    arrow, reverse,
                ))
            else:
                render_list.append((
                    arrow.from_id, arrow.to_id,
                    arrow.head_to, arrow.head_from,
                    arrow, None,
                ))

        for from_id, to_id, draw_head_to, draw_head_from, fwd, rev in render_list:
            from_box = self._board.box_by_id(from_id)
            to_box = self._board.box_by_id(to_id)
            if not from_box or not to_box:
                continue

            pen = QPen(ARROW_COLOR, ARROW_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            if fwd.style == "dashed":
                pen.setStyle(Qt.PenStyle.DashLine)
            elif fwd.style == "dotted":
                pen.setStyle(Qt.PenStyle.DotLine)
            elif fwd.style == "thick":
                pen.setWidthF(ARROW_WIDTH * 2)

            # Calculate start/end points
            aligned = _aligned_edge_points(from_box, to_box)
            if aligned:
                start, end = aligned
            else:
                from_center = QPointF(
                    from_box.x + from_box.w / 2, from_box.y + from_box.h / 2
                )
                to_center = QPointF(
                    to_box.x + to_box.w / 2, to_box.y + to_box.h / 2
                )
                start = _box_edge_point(from_box, to_center)
                end = _box_edge_point(to_box, from_center)

            dx = end.x() - start.x()
            dy = end.y() - start.y()

            # Forward arrowhead (at to_id end)
            if draw_head_to:
                angle = math.atan2(dy, dx)
                head = QGraphicsPolygonItem(_arrowhead_polygon(end, angle))
                head.setPen(QPen(ARROW_COLOR, 1))
                head.setBrush(QBrush(ARROW_COLOR))
                head.setData(0, fwd)
                self._scene.addItem(head)
                self._arrow_items.append(head)

            # Backward arrowhead (at from_id end)
            if draw_head_from:
                back_angle = math.atan2(-dy, -dx)
                back_head = QGraphicsPolygonItem(
                    _arrowhead_polygon(start, back_angle)
                )
                back_head.setPen(QPen(ARROW_COLOR, 1))
                back_head.setBrush(QBrush(ARROW_COLOR))
                back_head.setData(0, fwd)
                self._scene.addItem(back_head)
                self._arrow_items.append(back_head)

            # Collect labels: for merged pairs show both, stacked vertically
            label_texts: list[str] = []
            label_tooltips: list[str] = []
            if fwd.label:
                label_texts.append(fwd.label)
            if fwd.annotation:
                label_tooltips.append(fwd.annotation)
            if rev and rev.label:
                label_texts.append(rev.label)
            if rev and rev.annotation:
                label_tooltips.append(rev.annotation)

            total_len = math.hypot(dx, dy)
            has_label = False
            if label_texts and total_len > 0:
                mid_x = (start.x() + end.x()) / 2
                mid_y = (start.y() + end.y()) / 2

                combined = "\n".join(label_texts)
                label = LabelItem(combined)
                label.setFont(LABEL_FONT)
                label.setBrush(QBrush(QColor("#2F3437")))
                label.setData(0, fwd)
                if label_tooltips:
                    label.setToolTip("\n".join(label_tooltips))
                br = label.boundingRect()
                label_x = mid_x - br.width() / 2
                label_y = mid_y - br.height() / 2

                pad = 4
                gap = QRectF(
                    label_x - pad, label_y - pad,
                    br.width() + 2 * pad, br.height() + 2 * pad,
                )

                label.setPos(label_x, label_y)
                self._scene.addItem(label)
                self._arrow_items.append(label)
                has_label = True

            # Draw line (split around label gap if needed)
            if has_label:
                seg1_end, seg2_start = _line_rect_clip(start, end, gap)
                line1 = ArrowLineItem(
                    start.x(), start.y(), seg1_end.x(), seg1_end.y()
                )
                line1.setPen(pen)
                line1.setData(0, fwd)
                self._scene.addItem(line1)
                self._arrow_items.append(line1)
                line2 = ArrowLineItem(
                    seg2_start.x(), seg2_start.y(), end.x(), end.y()
                )
                line2.setPen(pen)
                line2.setData(0, fwd)
                self._scene.addItem(line2)
                self._arrow_items.append(line2)
            else:
                line = ArrowLineItem(
                    start.x(), start.y(), end.x(), end.y()
                )
                line.setPen(pen)
                line.setData(0, fwd)
                tooltip_parts = []
                if fwd.annotation:
                    tooltip_parts.append(fwd.annotation)
                if rev and rev.annotation:
                    tooltip_parts.append(rev.annotation)
                if tooltip_parts:
                    line.setToolTip("\n".join(tooltip_parts))
                self._scene.addItem(line)
                self._arrow_items.append(line)

        self._update_z_values()

    # ── Nesting helpers ──

    def _has_children(self, box_id: str) -> bool:
        if not self._board:
            return False
        return any(b.parent == box_id for b in self._board.boxes)

    def _descendants(self, box_id: str) -> list[BoxItem]:
        """Return all BoxItems that are descendants of box_id."""
        result = []
        for bid, item in self._box_items.items():
            if item.box.parent == box_id:
                result.append(item)
                result.extend(self._descendants(bid))
        return result

    def _box_depth(self, box_id: str) -> int:
        depth = 0
        current = box_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            box = self._board.box_by_id(current) if self._board else None
            if not box or not box.parent:
                break
            depth += 1
            current = box.parent
        return depth

    def _update_z_values(self):
        max_depth = 0
        for box_id, item in self._box_items.items():
            d = self._box_depth(box_id)
            item.setZValue(d)
            if d > max_depth:
                max_depth = d
        note_z = max_depth + 1
        for item in self._note_items:
            item.setZValue(note_z)
        arrow_z = max_depth + 2
        for item in self._arrow_items:
            item.setZValue(arrow_z)

    def _refresh_auto_layout(self, box_id: str):
        """Refresh auto-layout for a box when its children change."""
        if box_id in self._box_items:
            self._box_items[box_id].refresh_auto_layout()

    def _check_nesting(self, item: BoxItem):
        """Update parent of a box after it has been moved or resized."""
        if not self._board:
            return
        box = item.box
        box_rect = QRectF(box.x, box.y, box.w, box.h)
        desc_ids = {d.box.id for d in self._descendants(box.id)}

        best_parent = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == box.id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(box_rect):
                area = other.w * other.h
                if area < best_area:
                    best_area = area
                    best_parent = other_id

        old_parent = box.parent
        if best_parent:
            box.parent = best_parent
        elif box.parent:
            parent_box = self._board.box_by_id(box.parent)
            if parent_box:
                parent_rect = QRectF(
                    parent_box.x, parent_box.y,
                    parent_box.w, parent_box.h,
                )
                if not parent_rect.contains(box_rect):
                    box.parent = ""
            else:
                box.parent = ""

        if box.parent != old_parent:
            self._update_z_values()
            if old_parent:
                self._refresh_auto_layout(old_parent)
            if box.parent:
                self._refresh_auto_layout(box.parent)
            self.mark_dirty()

    def _update_reparent_highlight(self):
        """Highlight potential parent box during drag."""
        selected = [i for i in self._scene.selectedItems() if isinstance(i, BoxItem)]
        if len(selected) != 1:
            self._clear_reparent_highlight()
            return

        item = selected[0]
        box = item.box
        box_rect = QRectF(box.x, box.y, box.w, box.h)
        desc_ids = {d.box.id for d in self._descendants(box.id)}

        best_parent = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == box.id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(box_rect):
                area = other.w * other.h
                if area < best_area:
                    best_area = area
                    best_parent = other_item

        if best_parent is self._highlight_parent:
            return

        self._clear_reparent_highlight()
        if best_parent:
            self._highlight_orig_pen = best_parent.pen()
            pen = QPen(QColor("#2F5D5C"), 3, Qt.PenStyle.DashLine)
            best_parent.setPen(pen)
            self._highlight_parent = best_parent

    def _clear_reparent_highlight(self):
        if self._highlight_parent and self._highlight_orig_pen is not None:
            self._highlight_parent.setPen(self._highlight_orig_pen)
            self._highlight_parent = None
            self._highlight_orig_pen = None

    # ── Box mode (vim-like style / dimension) ──

    def _set_box_mode(self, mode: str):
        self._box_mode = mode
        # Remove old badge
        if self._mode_badge:
            if self._mode_badge_bg:
                self._scene.removeItem(self._mode_badge_bg)
                self._mode_badge_bg = None
            self._scene.removeItem(self._mode_badge)
            self._mode_badge = None
        if not mode:
            return
        # Create badge above the first selected box
        target = None
        for item in self._scene.selectedItems():
            if isinstance(item, (BoxItem, NoteItem)):
                target = item
                break
        if not target:
            return
        # Background rect
        bg = QGraphicsRectItem()
        bg_color = QColor("#2F3437")
        bg_color.setAlphaF(0.8)
        bg.setBrush(QBrush(bg_color))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        bg.setZValue(9998)
        self._scene.addItem(bg)
        self._mode_badge_bg = bg
        # Text
        label_text = "STYLE" if mode == "style" else "DIM"
        badge = QGraphicsTextItem(label_text)
        font = QFont(FONT_FAMILY, 9)
        badge.setFont(font)
        badge.setDefaultTextColor(QColor("#FFFFFF"))
        badge.setZValue(9999)
        self._scene.addItem(badge)
        self._mode_badge = badge
        self._update_mode_badge_pos()

    def _update_mode_badge_pos(self):
        if not self._mode_badge:
            return
        target = None
        for item in self._scene.selectedItems():
            if isinstance(item, (BoxItem, NoteItem)):
                target = item
                break
        if not target:
            return
        br = target.sceneBoundingRect()
        text_br = self._mode_badge.boundingRect()
        bx = br.center().x() - text_br.width() / 2
        by = br.top() - text_br.height() - 4
        self._mode_badge.setPos(bx, by)
        if self._mode_badge_bg:
            pad = 4
            self._mode_badge_bg.setRect(
                bx - pad, by - pad,
                text_br.width() + pad * 2,
                text_br.height() + pad * 2,
            )

    def _clear_box_mode(self):
        self._set_box_mode("")

    # ── Inline text editing ──

    def _start_editing(self, target: BoxItem | NoteItem):
        self._commit_editor()
        self._edit_target = target

        if isinstance(target, BoxItem):
            text = target.box.label
            pos = target.scenePos()
            rect = target.rect()
            font = target._box_font()
            target._label.setVisible(False)
        else:
            text = target.note.text
            font = target._note_font()
            target.setVisible(False)

        editor = QGraphicsTextItem(text)
        editor.setFont(font)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        editor.setDefaultTextColor(QColor("#2F3437"))
        br = editor.boundingRect()

        if isinstance(target, BoxItem):
            anchor = target._get_effective_anchor()
            if anchor == "topleft":
                editor.setPos(pos.x() + 8, pos.y() + 8)
            elif anchor == "topcenter":
                editor.setPos(
                    pos.x() + (rect.width() - br.width()) / 2,
                    pos.y() + 8,
                )
            else:
                editor.setPos(
                    pos.x() + rect.width() / 2 - br.width() / 2,
                    pos.y() + rect.height() / 2 - br.height() / 2,
                )
        else:
            editor.setPos(target.scenePos())

        self._scene.addItem(editor)
        editor.setZValue(1000)
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cursor)
        self._editor = editor

    def _commit_editor(self):
        if not self._editor or not self._edit_target:
            return
        self._push_undo()
        text = self._editor.toPlainText().strip()
        if text:
            if isinstance(self._edit_target, BoxItem):
                self._edit_target.update_label(text)
            elif isinstance(self._edit_target, NoteItem):
                self._edit_target.update_text(text)
            self.mark_dirty()
        if isinstance(self._edit_target, BoxItem):
            self._edit_target._label.setVisible(True)
        elif isinstance(self._edit_target, NoteItem):
            self._edit_target.setVisible(True)
        self._scene.removeItem(self._editor)
        self._editor = None
        self._edit_target = None

    def _cancel_editor(self):
        if self._editor:
            if isinstance(self._edit_target, BoxItem):
                self._edit_target._label.setVisible(True)
            elif isinstance(self._edit_target, NoteItem):
                self._edit_target.setVisible(True)
            self._scene.removeItem(self._editor)
            self._editor = None
            self._edit_target = None

    # ── Delete selected ──

    def _delete_selected(self):
        if not self._board:
            return
        self._push_undo()
        deleted = False
        former_parents: set[str] = set()
        for item in list(self._scene.selectedItems()):
            if isinstance(item, BoxItem):
                box_id = item.box.id
                # Unparent direct children and track former parent
                for other in self._board.boxes:
                    if other.parent == box_id:
                        other.parent = ""
                if item.box.parent:
                    former_parents.add(item.box.parent)
                # Remove connected arrows
                for arrow in list(self._board.arrows):
                    if arrow.from_id == box_id or arrow.to_id == box_id:
                        self._board.remove_arrow(arrow)
                self._board.remove_box(item.box)
                self._box_items.pop(box_id, None)
                self._scene.removeItem(item)
                deleted = True
            elif isinstance(item, NoteItem):
                self._board.remove_note(item.note)
                self._note_items.remove(item)
                self._scene.removeItem(item)
                deleted = True
        if deleted:
            self._update_z_values()
            self._redraw_arrows()
            for pid in former_parents:
                self._refresh_auto_layout(pid)
            self.mark_dirty()

    # ── Status bar helpers ──

    def _current_zoom(self) -> float:
        return self.transform().m11()

    def _update_status_zoom(self):
        window = self.window()
        if hasattr(window, '_status_zoom'):
            pct = round(self._current_zoom() * 100)
            window._status_zoom.setText(f"{pct}%")

    def _on_selection_changed(self):
        self._clear_box_mode()
        window = self.window()
        if hasattr(window, '_status_sel'):
            count = len(self._scene.selectedItems())
            window._status_sel.setText(f"{count} selected" if count else "")

    # ── Pan / Zoom ──

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._update_status_zoom()

    def mousePressEvent(self, event):
        # Middle-click pan always works
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        # Minimap click-to-navigate
        if self._minimap_click(event.position()):
            event.accept()
            return

        # If editor is active, consume clicks outside it
        if self._editor:
            editor_rect = self._editor.sceneBoundingRect()
            scene_pos = self.mapToScene(event.position().toPoint())
            if not editor_rect.contains(scene_pos):
                event.accept()
                return

        if self._mode == Mode.SELECT:
            # Save snapshot before potential move
            self._save_pre_action_snapshot()
            self._press_select(event)
        elif self._mode == Mode.RECT:
            self._press_rect(event)
        elif self._mode == Mode.TEXT:
            self._press_text(event)
        elif self._mode == Mode.CONNECT:
            self._press_connect(event)

    def mouseMoveEvent(self, event):
        # Update status bar position
        scene_pos = self.mapToScene(event.position().toPoint())
        window = self.window()
        if hasattr(window, '_status_pos'):
            window._status_pos.setText(
                f"{int(scene_pos.x())}, {int(scene_pos.y())}"
            )

        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return

        if self._mode == Mode.SELECT:
            if self._connect_source and self._connect_line:
                src = self._connect_source
                center = QPointF(
                    src.box.x + src.box.w / 2,
                    src.box.y + src.box.h / 2,
                )
                self._connect_line.setLine(
                    center.x(), center.y(), scene_pos.x(), scene_pos.y()
                )
                event.accept()
                return
            super().mouseMoveEvent(event)
            self._update_reparent_highlight()
        elif self._mode == Mode.RECT:
            self._move_rect(event)
        elif self._mode == Mode.CONNECT:
            self._move_connect(event)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        if self._mode == Mode.SELECT:
            if self._connect_source and event.button() == Qt.MouseButton.LeftButton:
                # Finish alt+drag connector
                if self._connect_line:
                    self._scene.removeItem(self._connect_line)
                    self._connect_line = None
                scene_pos = self.mapToScene(event.position().toPoint())
                item = self._scene.itemAt(scene_pos, self.transform())
                if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
                    item = item.parentItem()
                if (isinstance(item, BoxItem)
                        and item is not self._connect_source
                        and self._board):
                    existing = self._find_existing_arrow(
                        self._connect_source.box.id, item.box.id,
                    )
                    if existing:
                        self._select_arrow(existing)
                    else:
                        self._push_undo()
                        arrow = Arrow(
                            from_id=self._connect_source.box.id,
                            to_id=item.box.id,
                        )
                        self._board.add_arrow(arrow)
                        self._redraw_arrows()
                        self.mark_dirty()
                self._connect_source = None
                event.accept()
                return
            self._clear_reparent_highlight()
            super().mouseReleaseEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                for item in self._scene.selectedItems():
                    if isinstance(item, BoxItem):
                        self._check_nesting(item)
                self._commit_pre_action_snapshot()
        elif self._mode == Mode.RECT:
            self._release_rect(event)
        elif self._mode == Mode.CONNECT:
            self._release_connect(event)
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        if self._mode != Mode.SELECT:
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        # Resolve child items to their parent BoxItem
        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if isinstance(item, BoxItem):
            self._start_editing(item)
            event.accept()
            return
        if isinstance(item, NoteItem):
            self._start_editing(item)
            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        # Editor key handling
        if self._editor:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_editor()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Return and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._commit_editor()
                event.accept()
                return
            # Let the editor handle the key
            super().keyPressEvent(event)
            return

        # Search mode handling
        if self._search_active:
            self._handle_search_key(event)
            event.accept()
            return

        # Jump mode handling
        if self._jump_active:
            self._handle_jump_key(event)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Escape:
            if self._box_mode:
                self._clear_box_mode()
                event.accept()
                return
            if self._selected_arrow:
                self._deselect_arrow()
                event.accept()
                return
            self._scene.clearSelection()
            self.set_mode(Mode.SELECT)
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._selected_arrow:
                self._push_undo()
                self._board.remove_arrow(self._selected_arrow)
                self._selected_arrow = None
                self._selected_arrow_items.clear()
                self._redraw_arrows()
                self.mark_dirty()
                event.accept()
                return
            self._delete_selected()
            event.accept()
            return

        # Arrow editing with cursor keys when arrow is selected
        if self._selected_arrow:
            no_mod_check = not (event.modifiers() & _SIGNIFICANT_MODS)
            if no_mod_check and event.key() in (
                Qt.Key.Key_Left, Qt.Key.Key_Right,
                Qt.Key.Key_Up, Qt.Key.Key_Down,
            ):
                self._push_undo()
                arrow = self._selected_arrow
                if event.key() == Qt.Key.Key_Left:
                    arrow.head_from = not arrow.head_from
                elif event.key() == Qt.Key.Key_Right:
                    arrow.head_to = not arrow.head_to
                elif event.key() == Qt.Key.Key_Up:
                    idx = _ARROW_STYLE_CYCLE.index(arrow.style) if arrow.style in _ARROW_STYLE_CYCLE else 0
                    arrow.style = _ARROW_STYLE_CYCLE[(idx + 1) % len(_ARROW_STYLE_CYCLE)]
                elif event.key() == Qt.Key.Key_Down:
                    idx = _ARROW_STYLE_CYCLE.index(arrow.style) if arrow.style in _ARROW_STYLE_CYCLE else 0
                    arrow.style = _ARROW_STYLE_CYCLE[(idx - 1) % len(_ARROW_STYLE_CYCLE)]
                self._redraw_arrows()
                self._select_arrow(arrow)
                self.mark_dirty()
                event.accept()
                return

        mods = event.modifiers()
        has_selection = bool(self._scene.selectedItems())
        no_mod = not (mods & _SIGNIFICANT_MODS)

        # Vim aliases — u (undo), Ctrl+R (redo), x (delete), o/O (adjacent box)
        if event.key() == Qt.Key.Key_U and no_mod:
            self._undo()
            event.accept()
            return
        if event.key() == Qt.Key.Key_R and mods & _CTRL_MOD:
            self._redo()
            event.accept()
            return
        if event.key() == Qt.Key.Key_X and no_mod:
            if self._selected_arrow:
                self._push_undo()
                self._board.remove_arrow(self._selected_arrow)
                self._selected_arrow = None
                self._selected_arrow_items.clear()
                self._redraw_arrows()
                self.mark_dirty()
            else:
                self._delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_O and no_mod:
            self._create_adjacent_box("down")
            event.accept()
            return
        if event.key() == Qt.Key.Key_O and mods & Qt.KeyboardModifier.ShiftModifier:
            self._create_adjacent_box("up")
            event.accept()
            return
        # / — search by label
        if event.key() == Qt.Key.Key_Slash and no_mod:
            self._start_search()
            event.accept()
            return

        # Zoom with +/-
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.scale(1.15, 1.15)
            self._update_status_zoom()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Minus:
            self.scale(1 / 1.15, 1 / 1.15)
            self._update_status_zoom()
            event.accept()
            return

        # Ctrl+J — jump mode
        if (event.key() == Qt.Key.Key_J
                and mods & _CTRL_MOD):
            self._clear_box_mode()
            self._start_jump_mode()
            event.accept()
            return

        # Ctrl+Arrow — create adjacent box
        if mods & _CTRL_MOD:
            arrow_dirs = {
                Qt.Key.Key_Right: "right",
                Qt.Key.Key_Left: "left",
                Qt.Key.Key_Up: "up",
                Qt.Key.Key_Down: "down",
            }
            if event.key() in arrow_dirs:
                self._create_adjacent_box(arrow_dirs[event.key()])
                event.accept()
                return

        # Shift+H — cheatsheet (only when no box mode active)
        if (event.key() == Qt.Key.Key_H
                and mods & Qt.KeyboardModifier.ShiftModifier
                and not self._box_mode):
            self._show_cheatsheet()
            event.accept()
            return

        # Vim-like box modes — SELECT mode with selection
        if self._mode == Mode.SELECT and has_selection:
            shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            only_shift = shift and not (mods & ~Qt.KeyboardModifier.ShiftModifier & _SIGNIFICANT_MODS)

            if self._grid_visible:
                step = self.GRID_SPACING
                big_step = self.GRID_SPACING * 5
            else:
                step = 1
                big_step = 10

            # ── Default mode: hjkl moves, s/d enter sub-modes ──
            if self._box_mode == "":
                move_dirs = {
                    Qt.Key.Key_H: (-1, 0),
                    Qt.Key.Key_J: (0, 1),
                    Qt.Key.Key_K: (0, -1),
                    Qt.Key.Key_L: (1, 0),
                }
                if event.key() in move_dirs and (no_mod or only_shift):
                    dx_dir, dy_dir = move_dirs[event.key()]
                    amount = big_step if shift else step
                    dx = dx_dir * amount
                    dy = dy_dir * amount
                    self._push_undo()
                    for item in self._scene.selectedItems():
                        if isinstance(item, BoxItem):
                            item.box.x += dx
                            item.box.y += dy
                            item.setPos(item.box.x, item.box.y)
                        elif isinstance(item, NoteItem):
                            item.note.x += dx
                            item.note.y += dy
                            item.setPos(item.note.x, item.note.y)
                    self._update_mode_badge_pos()
                    self.arrow_update_needed.emit()
                    self.mark_dirty()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_S and no_mod:
                    self._set_box_mode("style")
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_D and no_mod:
                    self._set_box_mode("dimension")
                    event.accept()
                    return

            # ── Style mode: hjkl cycles color/size ──
            elif self._box_mode == "style":
                if event.key() == Qt.Key.Key_H and no_mod:
                    self._cycle_color(-1)
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_L and no_mod:
                    self._cycle_color(1)
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_J and no_mod:
                    self._cycle_textsize(-1)
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_K and no_mod:
                    self._cycle_textsize(1)
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_D and no_mod:
                    self._set_box_mode("dimension")
                    event.accept()
                    return

            # ── Dimension mode: hjkl shrinks, Shift+hjkl grows ──
            elif self._box_mode == "dimension":
                dim_key = event.key() in (
                    Qt.Key.Key_H, Qt.Key.Key_J,
                    Qt.Key.Key_K, Qt.Key.Key_L,
                )
                if dim_key and (no_mod or only_shift):
                    self._push_undo()
                    for item in self._scene.selectedItems():
                        if not isinstance(item, BoxItem):
                            continue
                        x, y, w, h = item.box.x, item.box.y, item.box.w, item.box.h
                        if shift:
                            # Grow
                            if event.key() == Qt.Key.Key_H:
                                x -= step; w += step
                            elif event.key() == Qt.Key.Key_J:
                                h += step
                            elif event.key() == Qt.Key.Key_K:
                                y -= step; h += step
                            elif event.key() == Qt.Key.Key_L:
                                w += step
                        else:
                            # Shrink
                            if event.key() == Qt.Key.Key_H:
                                if w - step >= MIN_BOX_SIZE:
                                    w -= step
                                else:
                                    continue
                            elif event.key() == Qt.Key.Key_J:
                                if h - step >= MIN_BOX_SIZE:
                                    h -= step
                                else:
                                    continue
                            elif event.key() == Qt.Key.Key_K:
                                if h - step >= MIN_BOX_SIZE:
                                    y += step; h -= step
                                else:
                                    continue
                            elif event.key() == Qt.Key.Key_L:
                                if w - step >= MIN_BOX_SIZE:
                                    x += step; w -= step
                                else:
                                    continue
                        item.box.x = x
                        item.box.y = y
                        item.box.w = w
                        item.box.h = h
                        item.setPos(x, y)
                        item.setRect(0, 0, w, h)
                        item._label.setTextWidth(w - 16)
                        item._position_label()
                        item._update_handles()
                    self._update_mode_badge_pos()
                    self.arrow_update_needed.emit()
                    self.mark_dirty()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_S and no_mod:
                    self._set_box_mode("style")
                    event.accept()
                    return

            # Non-modal keys that work regardless of box mode
            if no_mod:
                if event.key() == Qt.Key.Key_T:
                    self._clear_box_mode()
                    self._cycle_style()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_E:
                    self._clear_box_mode()
                    for item in self._scene.selectedItems():
                        if isinstance(item, (BoxItem, NoteItem)):
                            self._start_editing(item)
                            break
                    event.accept()
                    return

        # Shift+A — cycle anchor (SELECT mode with selection)
        if (event.key() == Qt.Key.Key_A
                and mods & Qt.KeyboardModifier.ShiftModifier
                and self._mode == Mode.SELECT and has_selection):
            self._cycle_anchor()
            event.accept()
            return

        # Shift+G — snap to grid (SELECT mode with selection)
        if (event.key() == Qt.Key.Key_G
                and mods & Qt.KeyboardModifier.ShiftModifier
                and self._mode == Mode.SELECT and has_selection):
            self._snap_to_grid()
            event.accept()
            return

        # G without shift — toggle grid
        if event.key() == Qt.Key.Key_G and no_mod:
            self.toggle_grid()
            event.accept()
            return

        # Arrow key panning (no modifiers, SELECT mode, no selection)
        if no_mod and self._mode == Mode.SELECT and not has_selection:
            PAN_STEP = 50
            pan_keys = {
                Qt.Key.Key_Right: (PAN_STEP, 0),
                Qt.Key.Key_Left: (-PAN_STEP, 0),
                Qt.Key.Key_Up: (0, -PAN_STEP),
                Qt.Key.Key_Down: (0, PAN_STEP),
            }
            if event.key() in pan_keys:
                dx, dy = pan_keys[event.key()]
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() + dx
                )
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() + dy
                )
                event.accept()
                return

        # M — toggle minimap
        if event.key() == Qt.Key.Key_M and no_mod:
            self._minimap_visible = not self._minimap_visible
            self.viewport().update()
            event.accept()
            return

        # Z — zoom to selection (no-op if nothing selected)
        if event.key() == Qt.Key.Key_Z and no_mod:
            self._zoom_to_selection()
            event.accept()
            return

        # Shift+Z — zoom to fit all
        if (event.key() == Qt.Key.Key_Z
                and mods & Qt.KeyboardModifier.ShiftModifier):
            self._zoom_to_fit()
            event.accept()
            return

        # P — select parent box (zoom if needed)
        if event.key() == Qt.Key.Key_P and no_mod:
            self._select_parent_and_zoom()
            event.accept()
            return

        # Mode switching shortcuts (no modifiers)
        if no_mod:
            mode_keys = {
                Qt.Key.Key_V: Mode.SELECT,
                Qt.Key.Key_R: Mode.RECT,
                Qt.Key.Key_T: Mode.TEXT,
                Qt.Key.Key_C: Mode.CONNECT,
            }
            if event.key() in mode_keys:
                self.set_mode(mode_keys[event.key()])
                event.accept()
                return

        super().keyPressEvent(event)

    # ── SELECT mode ──

    def _press_select(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())
        # Resolve child items to parent BoxItem/NoteItem
        resolved = item
        if isinstance(resolved, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(resolved.parentItem(), (BoxItem, NoteItem)):
            resolved = resolved.parentItem()

        # Shift+click toggles selection on individual items
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if isinstance(resolved, (BoxItem, NoteItem)):
                resolved.setSelected(not resolved.isSelected())
                event.accept()
                return
            # Shift+click on empty space: preserve current selection
            event.accept()
            return

        # Alt+click on a BoxItem starts connector drag
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and isinstance(resolved, BoxItem):
            self._connect_source = resolved
            center = QPointF(
                resolved.box.x + resolved.box.w / 2,
                resolved.box.y + resolved.box.h / 2,
            )
            pen = QPen(ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
            self._connect_line = self._scene.addLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y(), pen
            )
            event.accept()
            return

        # Alt+click on empty space: paste clipboard at position
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and not isinstance(resolved, BoxItem):
            if self._clipboard_boxes or self._clipboard_notes:
                self._paste_at(scene_pos)
                event.accept()
                return

        # Check if clicked on an arrow graphics item
        if isinstance(item, (ArrowLineItem, QGraphicsLineItem, QGraphicsPolygonItem, QGraphicsSimpleTextItem)):
            arrow_data = item.data(0)
            if isinstance(arrow_data, Arrow):
                self._select_arrow(arrow_data)
                event.accept()
                return
        # Clicking elsewhere deselects arrow
        self._deselect_arrow()
        super().mousePressEvent(event)

    # ── RECT mode ──

    def _press_rect(self, event):
        if not self._board:
            return
        self._rect_origin = self.mapToScene(event.position().toPoint())
        pen = QPen(BOX_BORDER, 1, Qt.PenStyle.DashLine)
        self._rect_preview = self._scene.addRect(
            QRectF(self._rect_origin, self._rect_origin), pen
        )
        self._rect_preview.setBrush(QBrush(QColor(0x2F, 0x34, 0x37, 30)))
        event.accept()

    def _move_rect(self, event):
        if self._rect_preview and self._rect_origin:
            current = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._rect_origin, current).normalized()
            self._rect_preview.setRect(rect)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def _release_rect(self, event):
        if not self._rect_preview or not self._rect_origin or not self._board:
            super().mouseReleaseEvent(event)
            return

        rect = self._rect_preview.rect()
        self._scene.removeItem(self._rect_preview)
        self._rect_preview = None

        w = max(rect.width(), MIN_BOX_SIZE)
        h = max(rect.height(), MIN_BOX_SIZE)

        # If just a click (tiny drag), use default size
        if w < MIN_BOX_SIZE + 5 and h < MIN_BOX_SIZE + 5:
            w = DEFAULT_BOX_W
            h = DEFAULT_BOX_H
            x = self._rect_origin.x() - w / 2
            y = self._rect_origin.y() - h / 2
        else:
            x = rect.x()
            y = rect.y()

        self._rect_origin = None

        self._push_undo()
        box_id = self._board.next_box_id()
        box = Box(id=box_id, label="", x=x, y=y, w=w, h=h)
        self._board.add_box(box)

        item = BoxItem(box)
        self._scene.addItem(item)
        self._box_items[box_id] = item
        self.mark_dirty()
        self.set_mode(Mode.SELECT)
        item.setSelected(True)
        self._start_editing(item)
        event.accept()

    # ── TEXT mode ──

    def _press_text(self, event):
        if not self._board:
            return
        self._push_undo()
        scene_pos = self.mapToScene(event.position().toPoint())
        note = Note(x=scene_pos.x(), y=scene_pos.y(), text="Note")
        self._board.add_note(note)

        item = NoteItem(note)
        self._scene.addItem(item)
        self._note_items.append(item)
        self.mark_dirty()
        self.set_mode(Mode.SELECT)
        item.setSelected(True)
        self._start_editing(item)
        event.accept()

    # ── CONNECT mode ──

    def _press_connect(self, event):
        if not self._board:
            return

        # Remove preview line before itemAt() so it doesn't block target
        saved_line = self._connect_line
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        # Click on child item → get parent BoxItem
        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if not isinstance(item, BoxItem):
            # Restore preview line if we had one and missed a target
            if saved_line and self._connect_source:
                self._connect_line = saved_line
                self._scene.addItem(self._connect_line)
            event.accept()
            return

        if not self._connect_source:
            # First click — set source
            self._connect_source = item
            center = QPointF(
                item.box.x + item.box.w / 2,
                item.box.y + item.box.h / 2,
            )
            pen = QPen(ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
            self._connect_line = self._scene.addLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y(), pen
            )
        else:
            # Second click — create arrow or select existing
            if item is not self._connect_source:
                existing = self._find_existing_arrow(
                    self._connect_source.box.id, item.box.id,
                )
                if existing:
                    self.set_mode(Mode.SELECT)
                    self._select_arrow(existing)
                else:
                    self._push_undo()
                    arrow = Arrow(
                        from_id=self._connect_source.box.id,
                        to_id=item.box.id,
                    )
                    self._board.add_arrow(arrow)
                    self._redraw_arrows()
                    self.mark_dirty()

            self._connect_source = None

        event.accept()

    def _move_connect(self, event):
        if self._connect_line and self._connect_source:
            scene_pos = self.mapToScene(event.position().toPoint())
            src = self._connect_source
            center = QPointF(
                src.box.x + src.box.w / 2,
                src.box.y + src.box.h / 2,
            )
            self._connect_line.setLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y()
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def _release_connect(self, event):
        if not self._connect_source:
            event.accept()
            return

        # Remove preview line first so it doesn't intercept itemAt()
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())

        if isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
            item = item.parentItem()

        if (isinstance(item, BoxItem)
                and item is not self._connect_source
                and self._board):
            existing = self._find_existing_arrow(
                self._connect_source.box.id, item.box.id,
            )
            if existing:
                self.set_mode(Mode.SELECT)
                self._select_arrow(existing)
            else:
                self._push_undo()
                arrow = Arrow(
                    from_id=self._connect_source.box.id,
                    to_id=item.box.id,
                )
                self._board.add_arrow(arrow)
                self._redraw_arrows()
                self.mark_dirty()

        self._connect_source = None
        event.accept()

    # ── Jump-to mode (Ctrl+J) ──

    def _start_jump_mode(self):
        if not self._board:
            return
        self._clear_jump_labels()

        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        # Collect jump targets: boxes, notes, and arrows (with midpoints)
        targets: list[tuple[BoxItem | NoteItem | Arrow, QPointF]] = []
        for item in self._box_items.values():
            if viewport_rect.intersects(item.sceneBoundingRect()):
                targets.append((item, item.sceneBoundingRect().center()))
        for item in self._note_items:
            if viewport_rect.intersects(item.sceneBoundingRect()):
                targets.append((item, item.sceneBoundingRect().center()))
        # Arrow midpoints
        for arrow in self._board.arrows:
            from_box = self._board.box_by_id(arrow.from_id)
            to_box = self._board.box_by_id(arrow.to_id)
            if from_box and to_box:
                mid = QPointF(
                    (from_box.x + from_box.w / 2 + to_box.x + to_box.w / 2) / 2,
                    (from_box.y + from_box.h / 2 + to_box.y + to_box.h / 2) / 2,
                )
                if viewport_rect.contains(mid):
                    targets.append((arrow, mid))

        if not targets:
            return

        count = len(targets)
        labels: list[str] = []
        if count <= 26:
            for i in range(count):
                labels.append(chr(ord("a") + i))
        else:
            for i in range(count):
                first = chr(ord("a") + i // 26)
                second = chr(ord("a") + i % 26)
                labels.append(first + second)

        self._jump_map = {}
        font = QFont(FONT_FAMILY, 14)
        font.setBold(True)

        for label_text, (target, center) in zip(labels, targets):
            self._jump_map[label_text] = target

            text_item = QGraphicsSimpleTextItem(label_text)
            text_item.setFont(font)
            text_item.setBrush(QBrush(QColor("#FFFFFF")))
            tr = text_item.boundingRect()

            pad = 3
            bg = QGraphicsRectItem(
                center.x() - tr.width() / 2 - pad,
                center.y() - tr.height() / 2 - pad,
                tr.width() + 2 * pad,
                tr.height() + 2 * pad,
            )
            bg.setBrush(QBrush(QColor("#C1086D")))
            bg.setPen(QPen(Qt.PenStyle.NoPen))
            bg.setZValue(1000)
            self._scene.addItem(bg)
            self._jump_labels.append(bg)

            text_item.setPos(
                center.x() - tr.width() / 2,
                center.y() - tr.height() / 2,
            )
            text_item.setZValue(1001)
            self._scene.addItem(text_item)
            self._jump_labels.append(text_item)

        self._jump_active = True
        self._jump_prefix = ""

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
                    self.centerOn(mid)
            else:
                target.setSelected(True)
                self.centerOn(target)
            return

        has_match = any(
            lbl.startswith(self._jump_prefix) for lbl in self._jump_map
        )
        if not has_match:
            self._clear_jump_labels()

    def _clear_jump_labels(self):
        for item in self._jump_labels:
            self._scene.removeItem(item)
        self._jump_labels.clear()
        self._jump_map.clear()
        self._jump_prefix = ""
        self._jump_active = False

    # ── Search by label (/) ──

    def _start_search(self):
        self._search_active = True
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
            # Cycle to next match
            if self._search_matches:
                self._search_index = (self._search_index + 1) % len(self._search_matches)
                self._highlight_search_match()
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
            return
        query = self._search_text.lower()
        for item in self._box_items.values():
            if query in item.box.label.lower() or query in item.box.id.lower():
                self._search_matches.append(item)
        for item in self._note_items:
            if query in item.note.text.lower():
                self._search_matches.append(item)
        self._highlight_search_match()

    def _highlight_search_match(self):
        self._scene.clearSelection()
        if self._search_matches:
            target = self._search_matches[self._search_index]
            target.setSelected(True)
            self.centerOn(target)

    def _accept_search(self):
        if self._search_matches:
            target = self._search_matches[self._search_index]
            self._cancel_search()
            self._scene.clearSelection()
            target.setSelected(True)
            if isinstance(target, BoxItem):
                b = target.box
                r = QRectF(b.x, b.y, b.w, b.h).adjusted(-60, -60, 60, 60)
            else:
                r = target.sceneBoundingRect().adjusted(-60, -60, 60, 60)
            self._animate_to_rect(r)
        else:
            self._cancel_search()

    def _cancel_search(self):
        self._search_active = False
        self._search_text = ""
        self._search_matches.clear()
        self._remove_search_badge()

    def _update_search_badge(self):
        self._remove_search_badge()
        vp = self.viewport().rect()
        # Map viewport top-center to scene coordinates for badge placement
        scene_top = self.mapToScene(QPointF(vp.width() / 2, 10).toPoint())

        count = len(self._search_matches)
        display = f"/{self._search_text}"
        if self._search_text:
            display += f"  [{count} match{'es' if count != 1 else ''}]"

        badge = QGraphicsTextItem(display)
        font = QFont(FONT_FAMILY, 12)
        badge.setFont(font)
        badge.setDefaultTextColor(QColor("#FFFFFF"))
        badge.setZValue(10001)
        br = badge.boundingRect()

        bg = QGraphicsRectItem()
        bg_color = QColor("#2F3437")
        bg_color.setAlphaF(0.9)
        bg.setBrush(QBrush(bg_color))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        bg.setZValue(10000)

        bx = scene_top.x() - br.width() / 2
        by = scene_top.y()
        badge.setPos(bx, by)
        pad = 6
        bg.setRect(bx - pad, by - pad, br.width() + pad * 2, br.height() + pad * 2)

        self._scene.addItem(bg)
        self._scene.addItem(badge)
        self._search_label = badge
        self._search_label_bg = bg

    def _remove_search_badge(self):
        if self._search_label:
            self._scene.removeItem(self._search_label)
            self._search_label = None
        if self._search_label_bg:
            self._scene.removeItem(self._search_label_bg)
            self._search_label_bg = None

    # ── Keyboard box creation (Ctrl+Arrow) ──

    def _create_adjacent_box(self, direction: str):
        if not self._board:
            return
        self._push_undo()

        gap = 40
        anchor_item = None
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                anchor_item = item
                break

        if anchor_item:
            box = anchor_item.box
            w, h = box.w, box.h
            if direction == "right":
                x = box.x + box.w + gap
                y = box.y
            elif direction == "left":
                x = box.x - w - gap
                y = box.y
            elif direction == "up":
                x = box.x
                y = box.y - h - gap
            else:
                x = box.x
                y = box.y + box.h + gap
        else:
            center = self.mapToScene(self.viewport().rect().center())
            w = DEFAULT_BOX_W
            h = DEFAULT_BOX_H
            x = center.x() - w / 2
            y = center.y() - h / 2

        box_id = self._board.next_box_id()
        new_box = Box(id=box_id, label="", x=x, y=y, w=w, h=h)
        self._board.add_box(new_box)

        new_item = BoxItem(new_box)
        self._scene.addItem(new_item)
        self._box_items[box_id] = new_item

        if anchor_item:
            arrow = Arrow(from_id=anchor_item.box.id, to_id=box_id)
            self._board.add_arrow(arrow)
            self._redraw_arrows()

        self.mark_dirty()
        self.set_mode(Mode.SELECT)
        self._scene.clearSelection()
        new_item.setSelected(True)

    # ── Animated zoom ──

    def _animate_to_rect(self, target_rect: QRectF):
        """Smoothly animate zoom and pan to show target_rect."""
        if self._zoom_timeline is not None:
            self._zoom_timeline.stop()
            self._zoom_timeline = None

        vp = self.viewport().rect()
        start_zoom = self.transform().m11()
        start_center = self.mapToScene(vp.center())

        target_zoom = min(vp.width() / max(target_rect.width(), 1),
                          vp.height() / max(target_rect.height(), 1))
        # Clamp to reasonable bounds
        target_zoom = max(0.05, min(target_zoom, 10.0))
        end_center = target_rect.center()

        self._anim_start_zoom = start_zoom
        self._anim_end_zoom = target_zoom
        self._anim_start_center = start_center
        self._anim_end_center = end_center

        tl = QTimeLine(250, self)
        tl.setUpdateInterval(16)
        tl.setEasingCurve(QEasingCurve.Type.OutCubic)
        tl.valueChanged.connect(self._on_zoom_anim_step)
        tl.finished.connect(self._on_zoom_anim_finished)
        self._zoom_timeline = tl
        tl.start()

    def _on_zoom_anim_step(self, value: float):
        z = self._anim_start_zoom + (self._anim_end_zoom - self._anim_start_zoom) * value
        cx = self._anim_start_center.x() + (self._anim_end_center.x() - self._anim_start_center.x()) * value
        cy = self._anim_start_center.y() + (self._anim_end_center.y() - self._anim_start_center.y()) * value
        self.setTransform(QTransform().scale(z, z))
        self.centerOn(QPointF(cx, cy))

    def _on_zoom_anim_finished(self):
        self._zoom_timeline = None
        self._update_status_zoom()

    def _zoom_to_selection(self):
        """z key: zoom to selected items. No-op if nothing selected."""
        if not self._board:
            return

        padding = 60

        # Check if an arrow is selected
        if self._selected_arrow:
            arrow = self._selected_arrow
            rects = []
            for bid in (arrow.from_id, arrow.to_id):
                if bid in self._box_items:
                    b = self._box_items[bid].box
                    rects.append(QRectF(b.x, b.y, b.w, b.h))
            if rects:
                target = rects[0]
                for r in rects[1:]:
                    target = target.united(r)
                self._animate_to_rect(target.adjusted(-padding, -padding, padding, padding))
                return

        # Check for selected boxes/notes
        selected = self._scene.selectedItems()
        if selected:
            rects = []
            for item in selected:
                if isinstance(item, BoxItem):
                    b = item.box
                    rects.append(QRectF(b.x, b.y, b.w, b.h))
                elif isinstance(item, NoteItem):
                    rects.append(QRectF(item.note.x, item.note.y,
                                        item.boundingRect().width(),
                                        item.boundingRect().height()))
            if rects:
                target = rects[0]
                for r in rects[1:]:
                    target = target.united(r)
                self._animate_to_rect(target.adjusted(-padding, -padding, padding, padding))

    def _zoom_to_fit(self):
        """Shift+Z key: zoom to fit entire diagram."""
        if not self._board:
            return
        items_rect = self._scene.itemsBoundingRect()
        if not items_rect.isNull():
            self._animate_to_rect(items_rect.adjusted(-40, -40, 40, 40))

    def _select_parent_and_zoom(self):
        """P key: select parent box, zoom to it if not fully visible."""
        if not self._board:
            return

        # Single box selection only
        selected = self._scene.selectedItems()
        if len(selected) != 1 or not isinstance(selected[0], BoxItem):
            return

        box = selected[0].box
        if not box.parent:
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
            padding = 60
            self._animate_to_rect(parent_rect.adjusted(-padding, -padding, padding, padding))

    # ── Cheatsheet (Shift+H) ──

    def _show_cheatsheet(self):
        shortcuts = [
            # Modes
            ("V", "Select mode"),
            ("R", "Create box (one-shot)"),
            ("T", "Create note (one-shot)"),
            ("C", "Connect arrow (one-shot)"),
            # Navigation
            ("Arrow keys", "Pan viewport"),
            ("Middle-drag", "Pan anywhere"),
            ("+ / -", "Zoom in / out"),
            ("Z", "Zoom to selection"),
            ("Shift+Z", "Zoom to fit all"),
            ("P", "Select parent (zoom if needed)"),
            ("Ctrl+J", "Jump to shape / arrow"),
            ("/", "Search by label"),
            # Editing
            ("E", "Edit selected element"),
            ("Double-click", "Edit text"),
            ("Enter", "Accept edit"),
            ("u", "Undo"),
            ("Ctrl+R", "Redo"),
            ("x", "Delete selected / arrow"),
            ("Delete", "Delete selected / arrow"),
            # Creation
            ("o", "Create box below"),
            ("O", "Create box above"),
            ("Ctrl+Arrow", "Create adjacent box"),
            ("Alt+Drag", "Connect boxes (from SELECT)"),
            ("Alt+Click", "Paste at position"),
            # Style (with selection)
            ("h / l", "Cycle color"),
            ("j / k", "Cycle text size"),
            ("s", "Enter style mode"),
            ("d", "Enter dimension mode"),
            ("Shift+A", "Cycle anchor"),
            ("Shift+G", "Snap to grid"),
            # View
            ("G", "Toggle grid"),
            ("M", "Toggle minimap"),
            # Arrow (selected)
            ("\u2190 / \u2192", "Toggle arrowheads"),
            ("\u2191 / \u2193", "Cycle arrow style"),
            # Other
            ("Shift+Click", "Toggle selection"),
            ("Shift+H", "This cheatsheet"),
            ("Escape", "Cancel / back to SELECT"),
        ]
        rows = "".join(
            f"<tr><td style='padding-right:16px'><b>{key}</b></td>"
            f"<td>{desc}</td></tr>"
            for key, desc in shortcuts
        )
        html = f"<table cellpadding='2'>{rows}</table>"
        msg = QMessageBox(self)
        msg.setWindowTitle("Keyboard Shortcuts")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.exec()

