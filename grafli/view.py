"""GrafliView — the main canvas view for the whiteboard app."""

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
    QDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from grafli.arrows import _aligned_edge_points, _arrowhead_polygon, _box_edge_point, _line_rect_clip, _rect_edge_point
from grafli.commands import CommandsMixin
from grafli.complexity import ComplexityMixin
from grafli.constants import (
    ANNOTATION_ARROW_COLOR,
    ANNOTATION_ARROW_WIDTH,
    ARROW_COLOR,
    ARROW_LABEL_FONT_SIZES,
    ARROW_WIDTH,
    BOX_BORDER,
    COLOR_PALETTE,
    CONTENT_BORDER_COLOR,
    DEFAULT_BOX_H,
    DEFAULT_BOX_W,
    FONT_FAMILY,
    GRID_COLOR,
    HEATMAP_CONTENT_BORDER,
    HEATMAP_GRID_COLOR,
    MIN_BOX_SIZE,
    NOTE_COLOR,
    SCENE_BG,
    Mode,
    _ARROW_STYLE_CYCLE,
    _CTRL_MOD,
    _SIGNIFICANT_MODS,
    _SIZE_SEQUENCE,
    _resolve_color,
)
from grafli.format import Arrow, Board, Box, Note, parse, serialize
from grafli.items import ArrowLineItem, BoxItem, BoxLabelItem, LabelItem, NoteItem, ResizeHandle
from grafli.minimap import MinimapMixin


# ── Canvas view ─────────────────────────────────────────────────

class GrafliView(CommandsMixin, ComplexityMixin, MinimapMixin, QGraphicsView):
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
        self._note_items: dict[str, NoteItem] = {}
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
        self._connect_source: BoxItem | NoteItem | None = None
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

        # Arrow label drag state
        self._label_drag_arrow: Arrow | None = None
        self._label_drag_start: QPointF | None = None
        self._label_drag_orig_offset: tuple[float, float] = (0.0, 0.0)

        # Vim-like box mode (style / dimension)
        self._box_mode: str = ""          # "", "style", "dimension"
        self._arrow_mode: str = ""        # "", "style"
        self._mode_badge: QGraphicsTextItem | None = None
        self._mode_badge_bg: QGraphicsRectItem | None = None

        # Minimap
        self._minimap_visible: bool = True
        self._minimap_rect: QRectF = QRectF()
        self._minimap_scene_rect: QRectF = QRectF()
        self._minimap_dragging: bool = False
        self._minimap_drag_offset: QPointF = QPointF()
        self._minimap_info_rect: QRectF | None = None
        self._graph_stats: dict = {}

        # Animated zoom
        self._zoom_timeline: QTimeLine | None = None
        self._anim_start_center: QPointF = QPointF()
        self._anim_end_center: QPointF = QPointF()
        self._anim_start_zoom: float = 1.0
        self._anim_end_zoom: float = 1.0

        # Progressive zoom state (z key levels)
        self._zoom_z_level: int = 0
        self._zoom_z_rect: QRectF | None = None

        # Sticky creation mode
        self._sticky_mode: bool = False

        # Navigation jumplist (Ctrl+O / Ctrl+I)
        self._nav_stack: list[QRectF] = []
        self._nav_index: int = -1
        self._NAV_STACK_CAP = 50

        # Graph navigation (Alt held)
        self._graph_nav_active = False
        self._graph_nav_labels: list[QGraphicsRectItem | QGraphicsSimpleTextItem] = []
        self._graph_nav_map: dict[str, str] = {}  # label key -> target node id
        self._graph_nav_warning: list[QGraphicsItem] = []

        # Complexity heatmap state
        self._complexity_active: bool = False
        self._complexity_node_heat: dict[str, float] = {}
        self._complexity_saved: list[tuple] = []

        # Subgraph focus filter state
        self._focus_active: bool = False
        self._focus_node_id: str | None = None
        self._focus_direction: str = "all"   # "all", "forward", "backward"
        self._focus_depth: int = 0           # 0 = unlimited, 1 = 1-hop

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
        grid_color = HEATMAP_GRID_COLOR if self._complexity_active else GRID_COLOR
        border_color = HEATMAP_CONTENT_BORDER if self._complexity_active else CONTENT_BORDER_COLOR
        if self._grid_visible:
            spacing = self.GRID_SPACING
            left = int(rect.left()) - (int(rect.left()) % spacing)
            top = int(rect.top()) - (int(rect.top()) % spacing)
            painter.setPen(QPen(grid_color, 2.0))
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
            pen = QPen(border_color, 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(border_rect, 12, 12)

    def drawForeground(self, painter: QPainter, rect: QRectF):
        super().drawForeground(painter, rect)
        self._draw_complexity_legend(painter)
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
        if mode == Mode.SELECT:
            self._sticky_mode = False
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
        for item in self._note_items.values():
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
        self._exit_graph_nav()
        self._clear_focus_filter()
        if self._complexity_active:
            self._clear_complexity_heatmap()
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

    def _select_arrow(self, arrow: Arrow, keep_mode: bool = False):
        if keep_mode:
            # Lightweight re-select: just refresh graphics items
            self._selected_arrow_items.clear()
            self._selected_arrow = arrow
        else:
            self._deselect_arrow()
            self._selected_arrow = arrow
        self._scene.clearSelection()
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
        self._clear_arrow_mode()
        self._selected_arrow = None
        self._selected_arrow_items.clear()
        self._redraw_arrows()

    def _find_existing_arrow(self, id_a: str, id_b: str) -> Arrow | None:
        """Find an arrow between the unordered pair {id_a, id_b}."""
        if not self._board:
            return None
        for arrow in self._board.arrows:
            if {arrow.from_id, arrow.to_id} == {id_a, id_b}:
                return arrow
        return None

    def _item_id(self, item: BoxItem | NoteItem) -> str:
        if isinstance(item, BoxItem):
            return item.box.id
        return item.note.id

    def _item_center(self, item: BoxItem | NoteItem) -> QPointF:
        if isinstance(item, BoxItem):
            return QPointF(
                item.box.x + item.box.w / 2,
                item.box.y + item.box.h / 2,
            )
        return item.sceneBoundingRect().center()

    def _elem_rect(self, elem: Box | Note) -> tuple[float, float, float, float]:
        """Return (x, y, w, h) for a Box or Note."""
        if isinstance(elem, Box):
            return (elem.x, elem.y, elem.w, elem.h)
        note_item = self._note_items.get(elem.id)
        if note_item:
            r = note_item.sceneBoundingRect()
            return (r.x(), r.y(), r.width(), r.height())
        return (elem.x, elem.y, 40, 20)

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

    def _invalidate_graph_stats(self):
        self._graph_stats = {}

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
        self._highlight_parent = None
        self._highlight_orig_pen = None
        self._focus_active = False
        self._focus_node_id = None
        self._focus_direction = "all"
        self._focus_depth = 0
        self._complexity_active = False
        self._complexity_node_heat.clear()
        self._complexity_saved.clear()
        self._update_focus_status()
        self._update_complexity_status()

        if not self._board:
            return

        dupe_ids: list[str] = []
        for box in self._board.boxes:
            item = BoxItem(box)
            self._scene.addItem(item)
            self._scene.addItem(item._label)
            if box.id in self._box_items:
                self._scene.removeItem(self._box_items[box.id]._label)
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
            self._note_items[note.id] = item

        self._update_z_values()

        # Refresh auto-layout now that all parent-child relationships exist
        for item in self._box_items.values():
            item.refresh_auto_layout()

        self._redraw_arrows()
        self._update_z_values()
        self._update_scene_rect()
        self._invalidate_graph_stats()

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
            from_elem = self._board.box_by_id(from_id) or self._board.note_by_id(from_id)
            to_elem = self._board.box_by_id(to_id) or self._board.note_by_id(to_id)
            if not from_elem or not to_elem:
                continue

            is_annotation = isinstance(from_elem, Note) or isinstance(to_elem, Note)
            both_boxes = isinstance(from_elem, Box) and isinstance(to_elem, Box)

            if is_annotation:
                arrow_color = ANNOTATION_ARROW_COLOR
                arrow_width = ANNOTATION_ARROW_WIDTH
                draw_head_to = False
                draw_head_from = False
            else:
                arrow_color = ARROW_COLOR
                arrow_width = ARROW_WIDTH

            pen = QPen(arrow_color, arrow_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            if fwd.style == "dashed":
                pen.setStyle(Qt.PenStyle.DashLine)
            elif fwd.style == "dotted":
                pen.setStyle(Qt.PenStyle.DotLine)
            elif fwd.style == "thick":
                pen.setWidthF(arrow_width * 2)

            # Calculate start/end points
            if both_boxes:
                aligned = _aligned_edge_points(from_elem, to_elem)
                if aligned:
                    start, end = aligned
                else:
                    from_center = QPointF(
                        from_elem.x + from_elem.w / 2, from_elem.y + from_elem.h / 2
                    )
                    to_center = QPointF(
                        to_elem.x + to_elem.w / 2, to_elem.y + to_elem.h / 2
                    )
                    start = _box_edge_point(from_elem, to_center)
                    end = _box_edge_point(to_elem, from_center)
            else:
                from_r = self._elem_rect(from_elem)
                to_r = self._elem_rect(to_elem)
                from_center = QPointF(from_r[0] + from_r[2] / 2, from_r[1] + from_r[3] / 2)
                to_center = QPointF(to_r[0] + to_r[2] / 2, to_r[1] + to_r[3] / 2)
                start = _rect_edge_point(*from_r, to_center)
                end = _rect_edge_point(*to_r, from_center)

            dx = end.x() - start.x()
            dy = end.y() - start.y()

            # Forward arrowhead (at to_id end)
            if draw_head_to:
                angle = math.atan2(dy, dx)
                head = QGraphicsPolygonItem(_arrowhead_polygon(end, angle))
                head.setPen(QPen(arrow_color, 1))
                head.setBrush(QBrush(arrow_color))
                head.setData(0, fwd)
                self._scene.addItem(head)
                self._arrow_items.append(head)

            # Backward arrowhead (at from_id end)
            if draw_head_from:
                back_angle = math.atan2(-dy, -dx)
                back_head = QGraphicsPolygonItem(
                    _arrowhead_polygon(start, back_angle)
                )
                back_head.setPen(QPen(arrow_color, 1))
                back_head.setBrush(QBrush(arrow_color))
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
                label.setFont(QFont(FONT_FAMILY, ARROW_LABEL_FONT_SIZES.get(fwd.textsize, 10)))
                label.setBrush(QBrush(QColor("#2F3437")))
                label.setData(0, fwd)
                if label_tooltips:
                    label.setToolTip("\n".join(label_tooltips))
                br = label.boundingRect()
                label_x = mid_x - br.width() / 2 + fwd.label_dx
                label_y = mid_y - br.height() / 2 + fwd.label_dy

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
                # If gap doesn't intersect the line, draw one unbroken line
                if ((seg1_end - start).manhattanLength() < 1
                        and (end - seg2_start).manhattanLength() < 1):
                    line = ArrowLineItem(
                        start.x(), start.y(), end.x(), end.y()
                    )
                    line.setPen(pen)
                    line.setData(0, fwd)
                    self._scene.addItem(line)
                    self._arrow_items.append(line)
                else:
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
        self._invalidate_graph_stats()

        if self._focus_active:
            self._apply_focus_filter()
        if self._complexity_active:
            self._apply_complexity_heatmap()

    # ── Subgraph focus filter ──

    def _compute_focus_keep_set(
        self, node_id: str, direction: str, depth: int
    ) -> tuple[set[str], set[str]]:
        """BFS from node_id following arrows per direction/depth.

        Returns (keep_box_ids, keep_note_ids).
        """
        if not self._board:
            return set(), set()

        keep_boxes: set[str] = {node_id}
        frontier: set[str] = {node_id}
        hops = 0

        while frontier:
            if depth > 0 and hops >= depth:
                break
            next_frontier: set[str] = set()
            for arrow in self._board.arrows:
                # Only follow box-to-box arrows
                if not self._board.box_by_id(arrow.from_id):
                    continue
                if not self._board.box_by_id(arrow.to_id):
                    continue
                if direction in ("all", "forward"):
                    if arrow.from_id in frontier and arrow.to_id not in keep_boxes:
                        next_frontier.add(arrow.to_id)
                if direction in ("all", "backward"):
                    if arrow.to_id in frontier and arrow.from_id not in keep_boxes:
                        next_frontier.add(arrow.from_id)
            keep_boxes |= next_frontier
            frontier = next_frontier
            hops += 1

        # Second pass: collect notes connected to any kept box
        keep_notes: set[str] = set()
        for arrow in self._board.arrows:
            note = self._board.note_by_id(arrow.from_id)
            if note and arrow.to_id in keep_boxes:
                keep_notes.add(note.id)
                continue
            note = self._board.note_by_id(arrow.to_id)
            if note and arrow.from_id in keep_boxes:
                keep_notes.add(note.id)

        return keep_boxes, keep_notes

    def _apply_focus_filter(self):
        """Set opacity on all items based on current focus state."""
        if not self._focus_active or not self._focus_node_id:
            return

        keep_boxes, keep_notes = self._compute_focus_keep_set(
            self._focus_node_id, self._focus_direction, self._focus_depth
        )

        # Boxes
        for box_id, item in self._box_items.items():
            opacity = 1.0 if box_id in keep_boxes else 0.08
            item.setOpacity(opacity)
            item._label.setOpacity(opacity)

        # Notes
        for note_id, item in self._note_items.items():
            opacity = 1.0 if note_id in keep_notes else 0.08
            item.setOpacity(opacity)

        # Arrow graphics
        for gfx in self._arrow_items:
            arrow = gfx.data(0)
            if not isinstance(arrow, Arrow):
                continue
            from_in = arrow.from_id in keep_boxes or arrow.from_id in keep_notes
            to_in = arrow.to_id in keep_boxes or arrow.to_id in keep_notes
            if from_in and to_in:
                gfx.setOpacity(1.0)
            elif from_in or to_in:
                gfx.setOpacity(0.25)
            else:
                gfx.setOpacity(0.08)

        self._update_focus_status()

    def _clear_focus_filter(self):
        """Reset focus state and restore all opacity to 1.0."""
        self._focus_active = False
        self._focus_node_id = None
        self._focus_direction = "all"
        self._focus_depth = 0

        for item in self._box_items.values():
            item.setOpacity(1.0)
            item._label.setOpacity(1.0)
        for item in self._note_items.values():
            item.setOpacity(1.0)
        for gfx in self._arrow_items:
            gfx.setOpacity(1.0)

        self._update_focus_status()

    def _update_focus_status(self):
        """Update window._status_focus label."""
        window = self.window()
        if not hasattr(window, '_status_focus'):
            return
        if not self._focus_active:
            window._status_focus.setText("")
            return
        dir_label = {"all": "all", "forward": "fwd", "backward": "bwd"}[self._focus_direction]
        depth_label = "1-hop" if self._focus_depth == 1 else "full"
        window._status_focus.setText(f"FOCUS:{dir_label} {depth_label}")

    # ── Nesting helpers ──

    def _has_children(self, box_id: str) -> bool:
        if not self._board:
            return False
        return (any(b.parent == box_id for b in self._board.boxes)
                or any(n.parent == box_id for n in self._board.notes))

    def _descendants(self, box_id: str) -> list[BoxItem | NoteItem]:
        """Return all BoxItems and NoteItems that are descendants of box_id."""
        result: list[BoxItem | NoteItem] = []
        for bid, item in self._box_items.items():
            if item.box.parent == box_id:
                result.append(item)
                result.extend(self._descendants(bid))
        for nid, item in self._note_items.items():
            if item.note.parent == box_id:
                result.append(item)
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
        # Arrow lines/heads: max_depth + 1
        arrow_line_z = max_depth + 1
        # Notes and arrow labels: max_depth + 2
        note_z = max_depth + 2
        for note_item in self._note_items.values():
            if note_item.note.parent:
                pd = self._box_depth(note_item.note.parent) + 1
                note_item.setZValue(max(pd, note_z))
            else:
                note_item.setZValue(note_z)
        for item in self._arrow_items:
            if isinstance(item, LabelItem):
                item.setZValue(note_z)
            else:
                item.setZValue(arrow_line_z)
        # Box labels: max_depth + 3 (always on top of arrows)
        box_label_z = max_depth + 3
        for box_item in self._box_items.values():
            box_item._label.setZValue(box_label_z)

    def _refresh_auto_layout(self, box_id: str):
        """Refresh auto-layout for a box when its children change."""
        if box_id in self._box_items:
            self._box_items[box_id].refresh_auto_layout()

    def _check_nesting(self, item: BoxItem | NoteItem):
        """Update parent of a box or note after it has been moved or resized."""
        if not self._board:
            return

        is_box = isinstance(item, BoxItem)
        if is_box:
            box = item.box
            item_rect = QRectF(box.x, box.y, box.w, box.h)
            item_id = box.id
            desc_ids = {d.box.id for d in self._descendants(box.id) if isinstance(d, BoxItem)}
        else:
            note = item.note
            sr = item.sceneBoundingRect()
            item_rect = QRectF(sr.x(), sr.y(), sr.width(), sr.height())
            item_id = note.id
            desc_ids = set()

        best_parent = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == item_id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(item_rect):
                area = other.w * other.h
                if area < best_area:
                    best_area = area
                    best_parent = other_id

        elem = item.box if is_box else item.note
        old_parent = elem.parent
        if best_parent:
            elem.parent = best_parent
        elif elem.parent:
            parent_box = self._board.box_by_id(elem.parent)
            if parent_box:
                parent_rect = QRectF(
                    parent_box.x, parent_box.y,
                    parent_box.w, parent_box.h,
                )
                if not parent_rect.contains(item_rect):
                    elem.parent = ""
            else:
                elem.parent = ""

        if elem.parent != old_parent:
            self._update_z_values()
            if old_parent:
                self._refresh_auto_layout(old_parent)
            if elem.parent:
                self._refresh_auto_layout(elem.parent)
            self.mark_dirty()

    def _update_reparent_highlight(self):
        """Highlight potential parent box during drag."""
        selected = [i for i in self._scene.selectedItems() if isinstance(i, (BoxItem, NoteItem))]
        if len(selected) != 1:
            self._clear_reparent_highlight()
            return

        item = selected[0]
        if isinstance(item, BoxItem):
            item_rect = QRectF(item.box.x, item.box.y, item.box.w, item.box.h)
            item_id = item.box.id
            desc_ids = {d.box.id for d in self._descendants(item.box.id) if isinstance(d, BoxItem)}
        else:
            sr = item.sceneBoundingRect()
            item_rect = QRectF(sr.x(), sr.y(), sr.width(), sr.height())
            item_id = item.note.id
            desc_ids = set()

        best_parent = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == item_id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(item_rect):
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
            try:
                self._highlight_parent.setPen(self._highlight_orig_pen)
            except RuntimeError:
                pass  # C++ object already deleted (scene rebuild)
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

    # ── Arrow mode (vim-like style) ──

    def _arrow_label_midpoint(self) -> QPointF | None:
        """Return scene midpoint of the selected arrow's line."""
        arrow = self._selected_arrow
        if not arrow or not self._board:
            return None
        fb = self._board.box_by_id(arrow.from_id)
        tb = self._board.box_by_id(arrow.to_id)
        if not fb or not tb:
            return None
        sx = fb.x + fb.w / 2
        sy = fb.y + fb.h / 2
        ex = tb.x + tb.w / 2
        ey = tb.y + tb.h / 2
        return QPointF((sx + ex) / 2, (sy + ey) / 2)

    def _set_arrow_mode(self, mode: str):
        self._arrow_mode = mode
        # Remove old badge
        if self._mode_badge:
            if self._mode_badge_bg:
                self._scene.removeItem(self._mode_badge_bg)
                self._mode_badge_bg = None
            self._scene.removeItem(self._mode_badge)
            self._mode_badge = None
        if not mode:
            return
        mid = self._arrow_label_midpoint()
        if not mid:
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
        badge = QGraphicsTextItem("STYLE")
        font = QFont(FONT_FAMILY, 9)
        badge.setFont(font)
        badge.setDefaultTextColor(QColor("#FFFFFF"))
        badge.setZValue(9999)
        self._scene.addItem(badge)
        self._mode_badge = badge
        self._update_arrow_mode_badge_pos()

    def _update_arrow_mode_badge_pos(self):
        if not self._mode_badge or not self._arrow_mode:
            return
        mid = self._arrow_label_midpoint()
        if not mid:
            return
        text_br = self._mode_badge.boundingRect()
        bx = mid.x() - text_br.width() / 2
        by = mid.y() - text_br.height() - 12
        self._mode_badge.setPos(bx, by)
        if self._mode_badge_bg:
            pad = 4
            self._mode_badge_bg.setRect(
                bx - pad, by - pad,
                text_br.width() + pad * 2,
                text_br.height() + pad * 2,
            )

    def _clear_arrow_mode(self):
        self._set_arrow_mode("")

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

    def _start_editing_arrow(self, arrow: Arrow):
        self._commit_editor()
        self._edit_target = arrow
        self._clear_arrow_mode()

        mid = self._arrow_label_midpoint()
        if not mid:
            return

        font = QFont(FONT_FAMILY, ARROW_LABEL_FONT_SIZES.get(arrow.textsize, 10))
        editor = QGraphicsTextItem(arrow.label)
        editor.setFont(font)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        editor.setDefaultTextColor(QColor("#2F3437"))
        br = editor.boundingRect()
        editor.setPos(
            mid.x() - br.width() / 2 + arrow.label_dx,
            mid.y() - br.height() / 2 + arrow.label_dy,
        )

        # Hide existing label items for this arrow
        for gfx in self._selected_arrow_items:
            if isinstance(gfx, QGraphicsSimpleTextItem):
                gfx.setVisible(False)

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
        if isinstance(self._edit_target, Arrow):
            self._edit_target.label = text
            self.mark_dirty()
            self._scene.removeItem(self._editor)
            self._editor = None
            arrow = self._edit_target
            self._edit_target = None
            self._redraw_arrows()
            self._select_arrow(arrow)
            return
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
            if isinstance(self._edit_target, Arrow):
                self._scene.removeItem(self._editor)
                self._editor = None
                arrow = self._edit_target
                self._edit_target = None
                self._redraw_arrows()
                self._select_arrow(arrow)
                return
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
                for other in self._board.notes:
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
                self._scene.removeItem(item._label)
                self._scene.removeItem(item)
                deleted = True
            elif isinstance(item, NoteItem):
                note_id = item.note.id
                if item.note.parent:
                    former_parents.add(item.note.parent)
                # Remove connected arrows
                for arrow in list(self._board.arrows):
                    if arrow.from_id == note_id or arrow.to_id == note_id:
                        self._board.remove_arrow(arrow)
                self._board.remove_note(item.note)
                self._note_items.pop(note_id, None)
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
        self._zoom_z_level = 0
        window = self.window()
        if hasattr(window, '_status_sel'):
            count = len(self._scene.selectedItems())
            window._status_sel.setText(f"{count} selected" if count else "")
        self._update_breadcrumb()

        # Recompute focus filter when selection changes
        if self._focus_active and not self._search_active:
            selected = self._scene.selectedItems()
            if len(selected) == 1 and isinstance(selected[0], BoxItem):
                new_id = selected[0].box.id
                if new_id != self._focus_node_id:
                    self._focus_node_id = new_id
                    self._focus_direction = "all"
                    self._focus_depth = 0
                    self._apply_focus_filter()
            elif not selected:
                self._clear_focus_filter()

    def _update_breadcrumb(self):
        """Update status bar breadcrumb showing ancestry path."""
        window = self.window()
        if not hasattr(window, '_status_breadcrumb'):
            return
        selected = self._scene.selectedItems()
        if len(selected) != 1 or not isinstance(selected[0], BoxItem) or not self._board:
            window._status_breadcrumb.setText("")
            return
        box = selected[0].box
        path: list[str] = [box.label or box.id]
        current = box.parent
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            parent_box = self._board.box_by_id(current)
            if not parent_box:
                break
            path.append(parent_box.label or parent_box.id)
            current = parent_box.parent
        path.reverse()
        text = " > ".join(path)
        if len(text) > 60:
            text = "... " + text[-(60 - 4):]
        window._status_breadcrumb.setText(text)

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

        # Minimap click-to-navigate / drag
        if self._minimap_press(event.position()):
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

        # Minimap viewport drag
        if self._minimap_move(event.position()):
            event.accept()
            return

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
            if self._label_drag_arrow and self._label_drag_start:
                delta = scene_pos - self._label_drag_start
                self._label_drag_arrow.label_dx = self._label_drag_orig_offset[0] + delta.x()
                self._label_drag_arrow.label_dy = self._label_drag_orig_offset[1] + delta.y()
                self._redraw_arrows()
                if self._label_drag_arrow is self._selected_arrow:
                    self._select_arrow(self._label_drag_arrow, keep_mode=True)
                event.accept()
                return
            if self._connect_source and self._connect_line:
                center = self._item_center(self._connect_source)
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
        # Minimap drag end
        if self._minimap_release():
            event.accept()
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        if self._mode == Mode.SELECT:
            if self._label_drag_arrow and event.button() == Qt.MouseButton.LeftButton:
                self._label_drag_arrow = None
                self._label_drag_start = None
                self.mark_dirty()
                event.accept()
                return
            if self._connect_source and event.button() == Qt.MouseButton.LeftButton:
                # Finish alt+drag connector
                if self._connect_line:
                    self._scene.removeItem(self._connect_line)
                    self._connect_line = None
                scene_pos = self.mapToScene(event.position().toPoint())
                item = self._scene.itemAt(scene_pos, self.transform())
                if isinstance(item, BoxLabelItem):
                    item = item._box_item
                elif isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), (BoxItem, NoteItem)):
                    item = item.parentItem()
                if (isinstance(item, (BoxItem, NoteItem))
                        and item is not self._connect_source
                        and self._board):
                    src_id = self._item_id(self._connect_source)
                    tgt_id = self._item_id(item)
                    existing = self._find_existing_arrow(src_id, tgt_id)
                    if existing:
                        self._select_arrow(existing)
                    else:
                        self._push_undo()
                        arrow = Arrow(from_id=src_id, to_id=tgt_id)
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
                    if isinstance(item, (BoxItem, NoteItem)):
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
        if isinstance(item, BoxLabelItem):
            item = item._box_item
        elif isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), BoxItem):
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

        # Graph nav mode handling (Alt held)
        if self._graph_nav_active:
            self._handle_graph_nav_key(event)
            event.accept()
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
            if self._complexity_active:
                self._clear_complexity_heatmap()
                event.accept()
                return
            if self._focus_active:
                self._clear_focus_filter()
                event.accept()
                return
            if self._box_mode:
                self._clear_box_mode()
                event.accept()
                return
            if self._arrow_mode:
                self._clear_arrow_mode()
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
                self._clear_arrow_mode()
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

        # Arrow editing when arrow is selected
        if self._selected_arrow:
            mods_a = event.modifiers()
            no_mod_a = not (mods_a & _SIGNIFICANT_MODS)
            key = event.key()

            # e — edit arrow label
            if no_mod_a and key == Qt.Key.Key_E:
                self._start_editing_arrow(self._selected_arrow)
                event.accept()
                return

            # 0 — reset label offset
            if no_mod_a and key == Qt.Key.Key_0:
                if self._selected_arrow.label_dx or self._selected_arrow.label_dy:
                    self._push_undo()
                    self._selected_arrow.label_dx = 0.0
                    self._selected_arrow.label_dy = 0.0
                    self._redraw_arrows()
                    self._select_arrow(self._selected_arrow, keep_mode=True)
                    self.mark_dirty()
                event.accept()
                return

            # s — enter arrow style mode
            if no_mod_a and key == Qt.Key.Key_S:
                self._set_arrow_mode("style")
                event.accept()
                return

            # Style mode keys
            if self._arrow_mode == "style":
                shift_only = (mods_a & _SIGNIFICANT_MODS) == Qt.KeyboardModifier.ShiftModifier
                if (no_mod_a and key in (
                    Qt.Key.Key_H, Qt.Key.Key_L,
                    Qt.Key.Key_J, Qt.Key.Key_K,
                )) or (shift_only and key in (
                    Qt.Key.Key_J, Qt.Key.Key_K,
                )):
                    self._push_undo()
                    arrow = self._selected_arrow
                    if no_mod_a and key == Qt.Key.Key_H:
                        arrow.head_from = not arrow.head_from
                    elif no_mod_a and key == Qt.Key.Key_L:
                        arrow.head_to = not arrow.head_to
                    elif no_mod_a and key == Qt.Key.Key_J:
                        idx = _SIZE_SEQUENCE.index(arrow.textsize) if arrow.textsize in _SIZE_SEQUENCE else 0
                        arrow.textsize = _SIZE_SEQUENCE[min(idx + 1, len(_SIZE_SEQUENCE) - 1)]
                    elif no_mod_a and key == Qt.Key.Key_K:
                        idx = _SIZE_SEQUENCE.index(arrow.textsize) if arrow.textsize in _SIZE_SEQUENCE else 0
                        arrow.textsize = _SIZE_SEQUENCE[max(idx - 1, 0)]
                    elif shift_only and key == Qt.Key.Key_J:
                        idx = _ARROW_STYLE_CYCLE.index(arrow.style) if arrow.style in _ARROW_STYLE_CYCLE else 0
                        arrow.style = _ARROW_STYLE_CYCLE[(idx + 1) % len(_ARROW_STYLE_CYCLE)]
                    elif shift_only and key == Qt.Key.Key_K:
                        idx = _ARROW_STYLE_CYCLE.index(arrow.style) if arrow.style in _ARROW_STYLE_CYCLE else 0
                        arrow.style = _ARROW_STYLE_CYCLE[(idx - 1) % len(_ARROW_STYLE_CYCLE)]
                    self._redraw_arrows()
                    self._select_arrow(arrow, keep_mode=True)
                    self._update_arrow_mode_badge_pos()
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

        # Ctrl+O — nav back
        if event.key() == Qt.Key.Key_O and mods & _CTRL_MOD:
            self._nav_back()
            event.accept()
            return

        # Ctrl+I — nav forward
        if event.key() == Qt.Key.Key_I and mods & _CTRL_MOD:
            self._nav_forward()
            event.accept()
            return

        # Alt — enter graph nav mode (single node selected)
        if event.key() == Qt.Key.Key_Alt:
            sel = self._scene.selectedItems()
            if len(sel) == 1 and isinstance(sel[0], BoxItem):
                self._enter_graph_nav(sel[0])
                event.accept()
                return

        # Ctrl+hkl — create connected box, Ctrl+Shift+hkl — create connected note
        if mods & _CTRL_MOD:
            hjkl_dirs = {
                Qt.Key.Key_H: "left",
                Qt.Key.Key_K: "up",
                Qt.Key.Key_L: "right",
            }
            if event.key() in hjkl_dirs:
                direction = hjkl_dirs[event.key()]
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._create_adjacent_note(direction)
                else:
                    self._create_adjacent_box(direction)
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

        # Tab / Shift+Tab — cycle siblings
        if event.key() == Qt.Key.Key_Tab and has_selection:
            sel = self._scene.selectedItems()
            if len(sel) == 1 and isinstance(sel[0], BoxItem):
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    self._cycle_sibling(-1)
                else:
                    self._cycle_sibling(1)
                event.accept()
                return

        # P — select parent box (zoom if needed)
        if event.key() == Qt.Key.Key_P and no_mod:
            self._select_parent_and_zoom()
            event.accept()
            return

        # F — select first child of current box
        if event.key() == Qt.Key.Key_F and no_mod:
            self._select_first_child()
            event.accept()
            return

        # A — complexity analysis heatmap
        if event.key() == Qt.Key.Key_A and no_mod:
            if self._complexity_active:
                self._clear_complexity_heatmap()
            else:
                if self._focus_active:
                    self._clear_focus_filter()
                self._complexity_active = True
                self._apply_complexity_heatmap()
            event.accept()
            return

        # B — subgraph focus filter
        if event.key() == Qt.Key.Key_B and no_mod:
            selected = self._scene.selectedItems()
            if self._focus_active:
                if len(selected) == 1 and isinstance(selected[0], BoxItem):
                    sel_id = selected[0].box.id
                    if sel_id == self._focus_node_id:
                        # Cycle direction: all -> forward -> backward -> all
                        cycle = {"all": "forward", "forward": "backward", "backward": "all"}
                        self._focus_direction = cycle[self._focus_direction]
                    else:
                        # Recompute for new node
                        self._focus_node_id = sel_id
                        self._focus_direction = "all"
                        self._focus_depth = 0
                    self._apply_focus_filter()
                else:
                    # Nothing selected -> exit
                    self._clear_focus_filter()
            else:
                if len(selected) == 1 and isinstance(selected[0], BoxItem):
                    if self._complexity_active:
                        self._clear_complexity_heatmap()
                    self._focus_active = True
                    self._focus_node_id = selected[0].box.id
                    self._focus_direction = "all"
                    self._focus_depth = 0
                    self._apply_focus_filter()
            event.accept()
            return

        # Shift+B — toggle focus depth (unlimited ↔ 1-hop)
        shift_only = (mods & _SIGNIFICANT_MODS) == Qt.KeyboardModifier.ShiftModifier
        if shift_only and event.key() == Qt.Key.Key_B:
            if self._focus_active:
                self._focus_depth = 0 if self._focus_depth == 1 else 1
                self._apply_focus_filter()
            event.accept()
            return

        # Sticky creation modes (Shift+N, Shift+T)
        if shift_only and event.key() == Qt.Key.Key_N:
            self._sticky_mode = True
            self.set_mode(Mode.RECT)
            event.accept()
            return
        if shift_only and event.key() == Qt.Key.Key_T:
            self._sticky_mode = True
            self.set_mode(Mode.TEXT)
            event.accept()
            return

        # Mode switching shortcuts (no modifiers)
        if no_mod:
            mode_keys = {
                Qt.Key.Key_V: Mode.SELECT,
                Qt.Key.Key_N: Mode.RECT,
                Qt.Key.Key_T: Mode.TEXT,
                Qt.Key.Key_C: Mode.CONNECT,
            }
            if event.key() in mode_keys:
                self._sticky_mode = False
                self.set_mode(mode_keys[event.key()])
                event.accept()
                return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Alt and self._graph_nav_active:
            self._exit_graph_nav()
            event.accept()
            return
        super().keyReleaseEvent(event)

    # ── SELECT mode ──

    def _press_select(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._scene.itemAt(scene_pos, self.transform())
        # Resolve child items to parent BoxItem/NoteItem
        resolved = item
        if isinstance(resolved, BoxLabelItem):
            resolved = resolved._box_item
        elif isinstance(resolved, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(resolved.parentItem(), (BoxItem, NoteItem)):
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

        # Alt+click on a BoxItem/NoteItem starts connector drag
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and isinstance(resolved, (BoxItem, NoteItem)):
            self._connect_source = resolved
            center = self._item_center(resolved)
            pen = QPen(ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
            self._connect_line = self._scene.addLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y(), pen
            )
            event.accept()
            return

        # Alt+click on empty space: paste clipboard at position
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and not isinstance(resolved, (BoxItem, NoteItem)):
            if self._clipboard_boxes or self._clipboard_notes:
                self._paste_at(scene_pos)
                event.accept()
                return

        # Check if clicked on an arrow graphics item
        if isinstance(item, (ArrowLineItem, QGraphicsLineItem, QGraphicsPolygonItem, QGraphicsSimpleTextItem)):
            arrow_data = item.data(0)
            if isinstance(arrow_data, Arrow):
                # Second click on label of already-selected arrow → start label drag
                if (isinstance(item, QGraphicsSimpleTextItem)
                        and arrow_data is self._selected_arrow):
                    self._push_undo()
                    self._label_drag_arrow = arrow_data
                    self._label_drag_start = scene_pos
                    self._label_drag_orig_offset = (arrow_data.label_dx, arrow_data.label_dy)
                    event.accept()
                    return
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
        if self._sticky_mode:
            item.setSelected(True)
        else:
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
        note = Note(id="", x=scene_pos.x(), y=scene_pos.y(), text="Note")
        self._board.add_note(note)

        item = NoteItem(note)
        self._scene.addItem(item)
        self._note_items[note.id] = item
        self.mark_dirty()
        if self._sticky_mode:
            item.setSelected(True)
        else:
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

        # Click on child item → get parent BoxItem/NoteItem
        if isinstance(item, BoxLabelItem):
            item = item._box_item
        elif isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), (BoxItem, NoteItem)):
            item = item.parentItem()

        if not isinstance(item, (BoxItem, NoteItem)):
            # Restore preview line if we had one and missed a target
            if saved_line and self._connect_source:
                self._connect_line = saved_line
                self._scene.addItem(self._connect_line)
            event.accept()
            return

        if not self._connect_source:
            # First click — set source
            self._connect_source = item
            center = self._item_center(item)
            pen = QPen(ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
            self._connect_line = self._scene.addLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y(), pen
            )
        else:
            # Second click — create arrow or select existing
            if item is not self._connect_source:
                src_id = self._item_id(self._connect_source)
                tgt_id = self._item_id(item)
                existing = self._find_existing_arrow(src_id, tgt_id)
                if existing:
                    self.set_mode(Mode.SELECT)
                    self._select_arrow(existing)
                else:
                    self._push_undo()
                    arrow = Arrow(from_id=src_id, to_id=tgt_id)
                    self._board.add_arrow(arrow)
                    self._redraw_arrows()
                    self.mark_dirty()

            self._connect_source = None

        event.accept()

    def _move_connect(self, event):
        if self._connect_line and self._connect_source:
            scene_pos = self.mapToScene(event.position().toPoint())
            center = self._item_center(self._connect_source)
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

        if isinstance(item, BoxLabelItem):
            item = item._box_item
        elif isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), (BoxItem, NoteItem)):
            item = item.parentItem()

        if (isinstance(item, (BoxItem, NoteItem))
                and item is not self._connect_source
                and self._board):
            src_id = self._item_id(self._connect_source)
            tgt_id = self._item_id(item)
            existing = self._find_existing_arrow(src_id, tgt_id)
            if existing:
                self.set_mode(Mode.SELECT)
                self._select_arrow(existing)
            else:
                self._push_undo()
                arrow = Arrow(from_id=src_id, to_id=tgt_id)
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
        vp_center = viewport_rect.center()

        # Collect ALL jump targets, split into visible and off-screen
        visible: list[tuple[BoxItem | NoteItem | Arrow, QPointF]] = []
        offscreen: list[tuple[BoxItem | NoteItem | Arrow, QPointF]] = []

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

        # Assign labels: single letters to visible, two letters to off-screen
        single_letters = [chr(ord("a") + i) for i in range(26)]
        self._jump_map = {}

        # Visible items get single-letter labels first
        vis_labels: list[str] = []
        for i in range(min(len(visible), 26)):
            vis_labels.append(single_letters[i])

        # Off-screen get two-letter labels
        off_labels: list[str] = []
        remaining_first = single_letters[len(vis_labels):]  # unused single letters as first char
        if not remaining_first:
            remaining_first = single_letters  # wrap around if all 26 used
        label_idx = 0
        for _ in range(len(offscreen)):
            first = remaining_first[label_idx // 26 % len(remaining_first)]
            second = single_letters[label_idx % 26]
            off_labels.append(first + second)
            label_idx += 1

        zoom = self._current_zoom()
        base_size = 14
        min_screen_px = 14
        scene_size = min(base_size * 3, max(base_size, min_screen_px / zoom))
        font = QFont(FONT_FAMILY, round(scene_size))
        font.setBold(True)

        # Render visible labels on the canvas
        for label_text, (target, center) in zip(vis_labels, visible):
            self._jump_map[label_text] = target
            self._render_jump_label(label_text, target, center, font, scene_size, base_size)

        # Register off-screen targets (no canvas labels)
        for label_text, (target, _center) in zip(off_labels, offscreen):
            self._jump_map[label_text] = target

        # Show off-screen badge list at viewport bottom
        if offscreen:
            self._render_offscreen_badge(off_labels, offscreen)

        self._jump_active = True
        self._jump_prefix = ""

    def _render_jump_label(self, label_text, target, center, font, scene_size, base_size):
        """Render a single jump label on the canvas."""
        if isinstance(target, (BoxItem, NoteItem)):
            bg_color = target.brush().color()
            if bg_color.alphaF() < 0.1:
                bg_color = QColor("#C1086D")
            else:
                bg_color = bg_color.darker(130)
        else:
            bg_color = QColor("#C1086D")

        lum = bg_color.redF() * 0.299 + bg_color.greenF() * 0.587 + bg_color.blueF() * 0.114
        text_color = "#FFFFFF" if lum < 0.5 else "#2F3437"

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

    def _render_offscreen_badge(self, off_labels, offscreen):
        """Show compact badge list of off-screen targets at viewport bottom."""
        vp = self.viewport().rect()
        scene_bottom = self.mapToScene(QPointF(vp.width() / 2, vp.height() - 30).toPoint())

        parts: list[str] = []
        for label_text, (target, _center) in zip(off_labels, offscreen):
            if isinstance(target, (BoxItem, NoteItem)):
                if isinstance(target, BoxItem):
                    name = target.box.label or target.box.id
                else:
                    name = target.note.text[:15]
            else:
                name = f"{target.from_id}\u2192{target.to_id}"
            parts.append(f"[{label_text}] {name}")
            if len(parts) >= 10:
                remaining = len(offscreen) - 10
                if remaining > 0:
                    parts.append(f"...+{remaining}")
                break

        display = "  ".join(parts)
        badge = QGraphicsTextItem(display)
        font = QFont(FONT_FAMILY, 9)
        badge.setFont(font)
        badge.setDefaultTextColor(QColor("#FFFFFF"))
        badge.setZValue(10001)
        br = badge.boundingRect()

        bg = QGraphicsRectItem()
        bg_color = QColor("#2F3437")
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
        for item in self._note_items.values():
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
            self._push_nav_snapshot()
            target = self._search_matches[self._search_index]
            self._cancel_search()
            self._scene.clearSelection()
            target.setSelected(True)
            if isinstance(target, BoxItem):
                b = target.box
                r = QRectF(b.x, b.y, b.w, b.h)
            else:
                r = target.sceneBoundingRect()
            padding = max(60, r.width() * 0.15, r.height() * 0.15)
            self._animate_to_rect(r.adjusted(-padding, -padding, padding, padding))
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
        self._start_editing(new_item)

    def _create_adjacent_note(self, direction: str):
        """Ctrl+Shift+hkl: create a connected annotation note."""
        if not self._board:
            return
        self._push_undo()

        gap = 40
        anchor_item = None
        for item in self._scene.selectedItems():
            if isinstance(item, (BoxItem, NoteItem)):
                anchor_item = item
                break

        if anchor_item:
            br = anchor_item.sceneBoundingRect()
            if direction == "right":
                x = br.right() + gap
                y = br.y()
            elif direction == "left":
                x = br.left() - gap - 80
                y = br.y()
            elif direction == "up":
                x = br.x()
                y = br.top() - gap - 30
            else:
                x = br.x()
                y = br.bottom() + gap
        else:
            center = self.mapToScene(self.viewport().rect().center())
            x = center.x()
            y = center.y()

        note = Note(id="", x=x, y=y, text="Note")
        self._board.add_note(note)
        note_item = NoteItem(note)
        self._scene.addItem(note_item)
        self._note_items[note.id] = note_item

        if anchor_item:
            src_id = self._item_id(anchor_item)
            arrow = Arrow(from_id=src_id, to_id=note.id)
            self._board.add_arrow(arrow)
            self._redraw_arrows()

        self.mark_dirty()
        self.set_mode(Mode.SELECT)
        self._scene.clearSelection()
        note_item.setSelected(True)
        self._start_editing(note_item)

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
        """z key: progressive zoom — selection → 2x context → fit all."""
        if not self._board:
            return

        self._push_nav_snapshot()
        self._zoom_z_level += 1

        # Level 3: fit all, then cycle back to selection on next press
        if self._zoom_z_level >= 3:
            self._zoom_to_fit()
            self._zoom_z_level = 0
            return

        # Build the base selection rect
        base_rect: QRectF | None = None

        # Check if an arrow is selected
        if self._selected_arrow:
            arrow = self._selected_arrow
            rects = []
            for bid in (arrow.from_id, arrow.to_id):
                if bid in self._box_items:
                    b = self._box_items[bid].box
                    rects.append(QRectF(b.x, b.y, b.w, b.h))
            if rects:
                base_rect = rects[0]
                for r in rects[1:]:
                    base_rect = base_rect.united(r)
        else:
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
                    base_rect = rects[0]
                    for r in rects[1:]:
                        base_rect = base_rect.united(r)

        if not base_rect:
            self._zoom_z_level = 0
            return

        padding = max(60, base_rect.width() * 0.15, base_rect.height() * 0.15)

        # Level 2: double the padding for more context
        if self._zoom_z_level == 2:
            padding *= 2

        self._animate_to_rect(base_rect.adjusted(-padding, -padding, padding, padding))

    def _zoom_to_fit(self):
        """Shift+Z key: zoom to fit entire diagram."""
        if not self._board:
            return
        items_rect = self._scene.itemsBoundingRect()
        if not items_rect.isNull():
            self._animate_to_rect(items_rect.adjusted(-40, -40, 40, 40))

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

    def _enter_graph_nav(self, source_item: BoxItem):
        """Show jump labels on connectors from the selected node."""
        if not self._board:
            return
        self._exit_graph_nav()  # clean up any previous state
        node_id = source_item.box.id
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()

        # Find connectors to other nodes (not annotation notes)
        targets: list[tuple[str, Arrow]] = []  # (target_id, arrow)
        for arrow in self._board.arrows:
            target_id = None
            if arrow.from_id == node_id:
                target_id = arrow.to_id
            elif arrow.to_id == node_id:
                target_id = arrow.from_id
            if target_id is None:
                continue
            # Skip annotation notes — only follow to boxes
            if not self._board.box_by_id(target_id):
                continue
            # Only connectors visible in viewport
            target_item = self._box_items.get(target_id)
            if not target_item:
                continue
            # Check if the connector midpoint is in viewport
            src_box = source_item.box
            tgt_box = target_item.box
            mid = QPointF(
                (src_box.x + src_box.w / 2 + tgt_box.x + tgt_box.w / 2) / 2,
                (src_box.y + src_box.h / 2 + tgt_box.y + tgt_box.h / 2) / 2,
            )
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
            src_box = source_item.box
            tgt_box = self._box_items[target_id].box
            mid = QPointF(
                (src_box.x + src_box.w / 2 + tgt_box.x + tgt_box.w / 2) / 2,
                (src_box.y + src_box.h / 2 + tgt_box.y + tgt_box.h / 2) / 2,
            )

            bg_color = QColor("#C1086D")
            text_item = QGraphicsSimpleTextItem(label_key)
            text_item.setFont(font)
            text_item.setBrush(QBrush(QColor("#FFFFFF")))
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
        text_item.setBrush(QBrush(QColor("#FFFFFF")))
        tr = text_item.boundingRect()

        pad = 6
        bg = QGraphicsRectItem(
            br.center().x() - tr.width() / 2 - pad,
            br.top() - tr.height() - pad * 3,
            tr.width() + 2 * pad,
            tr.height() + 2 * pad,
        )
        bg_color = QColor("#e04040")
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
            target_item = self._box_items.get(target_id)
            if target_item:
                self._push_nav_snapshot()
                self._scene.clearSelection()
                target_item.setSelected(True)
                # Zoom if target not fully visible
                tgt = target_item.box
                target_rect = QRectF(tgt.x, tgt.y, tgt.w, tgt.h)
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

    # ── Cheatsheet (Shift+H) ──

    def _show_cheatsheet(self):
        groups = [
            ("Modes", [
                ("V", "Select mode"),
                ("N / \u21e7N", "Create node (one-shot / sticky)"),
                ("T / \u21e7T", "Create note (one-shot / sticky)"),
                ("C", "Connect arrow (one-shot)"),
            ]),
            ("Navigate", [
                ("Arrow keys", "Pan viewport"),
                ("Middle-drag", "Pan anywhere"),
                ("+ / -", "Zoom in / out"),
                ("Z", "Zoom to selection (progressive)"),
                ("Shift+Z", "Zoom to fit all"),
                ("P", "Select parent (zoom if needed)"),
                ("F", "Select first child"),
                ("Tab / \u21e7Tab", "Cycle siblings"),
                ("Ctrl+J", "Jump to any item (global)"),
                ("Ctrl+O / Ctrl+I", "Nav history back / forward"),
                ("Alt (hold)", "Graph nav: follow connectors"),
            ]),
            ("Edit", [
                ("E / Dbl-click", "Edit selected element"),
                ("Enter", "Accept edit"),
                ("u", "Undo"),
                ("Ctrl+R", "Redo"),
                ("x / Delete", "Delete selected / arrow"),
            ]),
            ("Create", [
                ("o / O", "Create box below / above"),
                ("Ctrl+Arrow", "Create adjacent box"),
                ("Ctrl+hkl", "Create connected box (left/up/right)"),
                ("\u21e7Ctrl+hkl", "Create connected note (left/up/right)"),
                ("Alt+Drag", "Connect boxes (from SELECT)"),
                ("Alt+Click", "Paste at position"),
                ("/", "Search by label"),
            ]),
            ("Style", [
                ("h / l", "Cycle color"),
                ("j / k", "Cycle text size"),
                ("s", "Enter style mode"),
                ("d", "Enter dimension mode"),
                ("Shift+A", "Cycle anchor"),
                ("Shift+G", "Snap to grid"),
            ]),
            ("Focus & Analysis", [
                ("A", "Complexity analysis heatmap"),
                ("B", "Subgraph focus (cycle direction)"),
                ("\u21e7B", "Toggle focus depth (full/1-hop)"),
            ]),
            ("View", [
                ("G", "Toggle grid"),
                ("M", "Toggle minimap"),
            ]),
            ("Arrow", [
                ("e", "Edit arrow label"),
                ("s", "Enter arrow style mode"),
                ("h / l", "Toggle arrowheads"),
                ("j / k", "Arrow label size"),
                ("\u21e7J / \u21e7K", "Cycle arrow style"),
            ]),
            ("Other", [
                ("Shift+Click", "Toggle selection"),
                ("Shift+H", "This cheatsheet"),
                ("Escape", "Cancel / back to SELECT"),
            ]),
        ]

        columns = [
            ["Modes", "Navigate"],
            ["Edit", "Create", "Focus & Analysis", "View"],
            ["Style", "Arrow", "Other"],
        ]
        group_map = {name: entries for name, entries in groups}

        hdr = (
            "color:#6A9FB5;font-weight:bold;"
            "padding-top:8px;padding-bottom:2px"
        )

        def _render_column(group_names):
            rows = []
            for name in group_names:
                rows.append(
                    f"<tr><td colspan='2' style='{hdr}'>"
                    f"{name.upper()}</td></tr>"
                )
                for key, desc in group_map[name]:
                    rows.append(
                        f"<tr>"
                        f"<td style='padding-right:12px;white-space:nowrap'>"
                        f"<b>{key}</b></td>"
                        f"<td>{desc}</td></tr>"
                    )
            return f"<table cellpadding='1'>{''.join(rows)}</table>"

        col_html = "</td><td width='24'></td><td valign='top'>".join(
            _render_column(col) for col in columns
        )
        html = (
            "<table><tr>"
            f"<td valign='top'>{col_html}</td>"
            "</tr></table>"
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        dlg.setFixedWidth(820)

        browser = QTextBrowser(dlg)
        browser.setOpenLinks(False)
        browser.setHtml(html)

        btn = QPushButton("Close", dlg)
        btn.clicked.connect(dlg.accept)

        layout = QVBoxLayout(dlg)
        layout.addWidget(browser)
        layout.addWidget(btn)

        dlg.exec()

    def _show_graph_stats_dialog(self):
        hdr = "color:#6A9FB5;font-weight:bold;font-size:13px"
        cell = "padding:4px 8px"
        html = f"""
        <p style='{hdr}'>GRAPH COMPLEXITY METRICS</p>
        <table cellpadding='2' style='margin-left:8px'>
          <tr>
            <td style='{cell}'><b>N (Nodes)</b></td>
            <td style='{cell}'>Number of boxes in the diagram.</td>
          </tr>
          <tr>
            <td style='{cell}'><b>E (Edges)</b></td>
            <td style='{cell}'>Number of arrows / connections.</td>
          </tr>
          <tr>
            <td style='{cell}'><b>C (Cyclomatic)</b></td>
            <td style='{cell}'>
              E &minus; N + 2P &nbsp;(P = connected components).<br>
              Measures independent paths through the graph;<br>
              higher values indicate more interconnection.
            </td>
          </tr>
        </table>
        <br>
        <p style='{hdr}'>FUZZY LABEL THRESHOLDS</p>
        <table border='1' cellpadding='4' cellspacing='0'
               style='border-collapse:collapse;margin-left:8px;
                      border-color:#555'>
          <tr style='background:#333;color:#ccc'>
            <th style='{cell}'>Label</th>
            <th style='{cell}'>Nodes (N)</th>
            <th style='{cell}'>Cyclomatic (C)</th>
          </tr>
          <tr>
            <td style='{cell};color:#7fb97f'><b>Simple</b></td>
            <td style='{cell}'>&le; 8</td>
            <td style='{cell}'>&le; 3</td>
          </tr>
          <tr>
            <td style='{cell};color:#c9b84e'><b>Moderate</b></td>
            <td style='{cell}'>9 &ndash; 20</td>
            <td style='{cell}'>4 &ndash; 8</td>
          </tr>
          <tr>
            <td style='{cell};color:#d4883a'><b>Intricate</b></td>
            <td style='{cell}'>21 &ndash; 40</td>
            <td style='{cell}'>9 &ndash; 15</td>
          </tr>
          <tr>
            <td style='{cell};color:#c75050'><b>Dense</b></td>
            <td style='{cell}'>&gt; 40</td>
            <td style='{cell}'>&gt; 15</td>
          </tr>
        </table>
        <br>
        <p style='color:#999;font-size:11px;margin-left:8px'>
          The overall label is the <i>maximum</i> tier from N and C.
        </p>
        """

        dlg = QDialog(self)
        dlg.setWindowTitle("Graph Complexity")
        dlg.setFixedWidth(480)

        browser = QTextBrowser(dlg)
        browser.setOpenLinks(False)
        browser.setHtml(html)

        btn = QPushButton("Close", dlg)
        btn.clicked.connect(dlg.accept)

        layout = QVBoxLayout(dlg)
        layout.addWidget(browser)
        layout.addWidget(btn)

        dlg.exec()

