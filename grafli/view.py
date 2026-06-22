"""GrafliView — the main canvas view for the whiteboard app."""

from __future__ import annotations

import math
import re as _re
import time
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEasingCurve,
    QIODevice,
    QPoint,
    QPointF,
    QRectF,
    QSettings,
    Qt,
    QTimeLine,
    QTimer,
    QStringListModel,
    QVariantAnimation,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QTextCursor,
    QTransform,
    QWheelEvent,
)
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from grafli.arrows import _aligned_edge_points, _arrowhead_polygon, _box_edge_point, _line_rect_clip, _rect_edge_point
from grafli.buffers import ViewState
from grafli.commands import CommandsMixin
from grafli.complexity import ComplexityMixin
from grafli.editor import InlineVimEditor
from grafli.constants import (
    ANNOTATION_ARROW_COLOR,
    ANNOTATION_ARROW_WIDTH,
    ARROW_COLOR,
    ARROW_LABEL_FONT_SIZES,
    ARROW_WIDTH,
    ARROWHEAD_SIZE,
    BOX_BORDER,
    BOX_FILL,
    BOX_FONT_SIZES,
    resolve_textsize_px,
    COLOR_PALETTE,
    CONNECTOR_REF_SIZE,
    CONNECTOR_WIDTH_MAX,
    CONNECTOR_WIDTH_MIN,
    CONTENT_BORDER_COLOR,
    DEFAULT_BOX_H,
    DEFAULT_BOX_W,
    FONT_FAMILY,
    NOTE_PEN_COLOR,
    GRID_COLOR,
    MINIMAP_MARGIN,
    HEATMAP_CONTENT_BORDER,
    HEATMAP_GRID_COLOR,
    LAYOUT_PADDING,
    MIN_BOX_SIZE,
    SCENE_BG,
    Mode,
    _ARROW_STYLE_CYCLE,
    _CTRL_MOD,
    _SIGNIFICANT_MODS,
    _SIZE_SEQUENCE,
    _resolve_color,
)
from grafli.edge_label import EDGE_KIND_COLORS, parse_edge_label
from grafli.format import Arrow, Board, Bookmark, Box, Flow, FlowStep, Image, Note, emphasis_from_flags, parse, serialize
from grafli.flows import FlowPlayer
from grafli.glyphs import GlyphPicker, ensure_text_presentation
from grafli.iconset import ICON_NAMES, icon_pixmap
from grafli.items import ArrowLineItem, BoxItem, BoxLabelItem, ImageItem, LabelItem, MIN_SCALE_FONT_PT, NoteItem, ResizeForeshadow, ResizeHandle
from grafli.md_note import note_is_md, toggle_task
from grafli.minimap import MinimapMixin
from grafli.zen import ZenOverlay
from grafli.zen_md import ZenMarkdownEditor


_JUMP_KEYS = "asdfjklghqweruioptyzxcvbnm"


class _ResourcePicker(QPushButton):
    """Inline popup letting the user pick a resource type to create."""

    resource_selected = Signal(str)

    _STYLE = (
        "QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {border};"
        " border-radius: 6px; padding: 6px 10px; font-family: {font}; font-size: 12px; }}"
        "QPushButton:hover {{ background: {hover}; }}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setText("  [m]arkdown    [g]rafli    [f]ile  ")
        self.setStyleSheet(self._STYLE.format(
            bg="#2A2D2E", fg="#D4D4D4", border="#555",
            hover="#3A3D3E", font=FONT_FAMILY,
        ))

    def sizeHint(self):
        return super().sizeHint()

    def keyPressEvent(self, event):
        key = event.text().lower()
        if key == "m":
            self.resource_selected.emit("markdown")
            self.close()
        elif key == "g":
            self.resource_selected.emit("grafli")
            self.close()
        elif key == "f":
            self.resource_selected.emit("file")
            self.close()
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


# ── Canvas view ─────────────────────────────────────────────────

class GrafliView(CommandsMixin, ComplexityMixin, MinimapMixin, QGraphicsView):
    """QGraphicsView with pan/zoom and file-backed board rendering."""

    arrow_update_needed = Signal()
    mode_changed = Signal(Mode)
    selection_changed_for_panel = Signal(bool)
    flows_changed = Signal()
    playback_ended = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QBrush(SCENE_BG))
        self.setScene(self._scene)

        # TextAntialiasing sharpens the Nerd Font glyphs / labels; SmoothPixmap
        # keeps scaled images and the minimap crisp instead of jagged.
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        # No context menu — the right button is used for panning.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        # Grid mode: "off" (no dots, free move), "visual" (dots, free move),
        # "snap" (dots + snapping). Remembered across restarts via QSettings.
        mode = QSettings("Grafli", "Grafli").value("grid/mode", "snap", type=str)
        self._grid_mode: str = mode if mode in self._GRID_CYCLE else "snap"
        self.GRID_SPACING = 20

        self._board: Board | None = None
        self._box_items: dict[str, BoxItem] = {}
        self._arrow_items: list[QGraphicsLineItem | QGraphicsPolygonItem | QGraphicsSimpleTextItem] = []
        self._note_items: dict[str, NoteItem] = {}
        self._image_items: dict[str, ImageItem] = {}
        self._dirty = False

        # Pan state (middle-click always works)
        self._panning = False
        self._pan_start = QPointF()

        # Auto-scroll state
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(16)  # ~60fps
        self._autoscroll_timer.timeout.connect(self._autoscroll_tick)

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
        # Notes use a vim-capable widget hosted in a proxy (boxes/arrows
        # keep the plain QGraphicsTextItem above).
        self._note_proxy: QGraphicsProxyWidget | None = None
        self._note_widget: InlineVimEditor | None = None

        # Zen annotation editor
        self._zen_editor: ZenOverlay | None = None
        self._zen_target = None  # BoxItem | NoteItem | Arrow

        # Fuzzy overlay (file/buffer picker)
        self._fuzzy_overlay = None

        # Nesting: guard against recursive position propagation
        self._propagating_move = False
        self._suppress_child_updates = False
        self._batch_move_updates = False

        # Undo / Redo
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._pre_move_snapshot: str = ""

        # Copy / Paste clipboard
        self._clipboard_boxes: list[Box] = []
        self._clipboard_notes: list[Note] = []
        self._clipboard_arrows: list[Arrow] = []
        self._clipboard_images: list[Image] = []
        # Fingerprint of the system-clipboard image/text at the last internal
        # copy, so paste can tell whether they were copied *after* it (and should
        # win) or were already there (internal copy wins) — latest copy wins.
        self._copy_clip_img_fp: tuple | None = None
        self._copy_clip_text: str = ""

        # Reparenting drag highlight: a dashed rectangle previewing the target
        # parent's auto-grown bounds (or None when the drop would detach).
        self._grow_preview: QGraphicsRectItem | None = None

        # Resize/scale foreshadow overlay (target frame + content area).
        self._resize_foreshadow = None

        # Jump-to mode state
        self._jump_active = False
        self._jump_labels: list[QGraphicsItem] = []
        self._jump_map: dict[str, BoxItem | NoteItem | Arrow] = {}
        self._jump_label_items: dict[str, list[QGraphicsItem]] = {}
        self._jump_prefix = ""
        self._jump_two_letter = False

        # Arrow selection state
        self._selected_arrow: Arrow | None = None
        self._selected_arrow_items: list[QGraphicsItem] = []

        # Arrow label drag state
        self._label_drag_arrow: Arrow | None = None
        self._label_drag_start: QPointF | None = None
        self._label_drag_orig_offset: tuple[float, float] = (0.0, 0.0)

        # Item drag state: distinguishes a real move (which may reparent) from
        # a plain/shift click that only changes the selection.
        self._mouse_press_pos: QPointF | None = None
        self._drag_moved: bool = False

        # Sticky style defaults for new boxes / notes
        self._last_box_color: str = ""
        self._last_box_textsize: str = ""
        self._last_note_textsize: str = ""
        # Sticky connector kind: once you promote a note/image connector to a
        # graph edge, subsequent note/image connectors default to graph too.
        self._last_connector_kind: str = ""

        # g-prefix two-key sequences
        self._g_pending: bool = False

        # Vim-like box mode (style / dimension)
        self._box_mode: str = ""          # "", "style", "dimension"
        self._arrow_mode: str = ""        # "", "style"
        # Colour-grid picker (style mode -> c): live-preview palette overlay.
        # Boxes pick a palette colour; notes pick a background plate (two
        # options: beige plate / none), so the picker has a small mode flag.
        self._color_picker_active: bool = False
        self._color_picker_index: int = 0
        self._color_picker_original: dict = {}
        self._color_picker_mode: str = "box"   # "box" | "note-bg"
        # Icon-grid picker (style mode -> i): live-preview glyph vocabulary.
        # Tab toggles placement (fill <-> lead). Originals are (name, placement).
        self._icon_picker_active: bool = False
        self._icon_picker_index: int = 0
        self._icon_picker_placement: str = ""
        self._icon_picker_original: dict[str, tuple[str, str]] = {}
        # Type grid (style mode -> s): size rows x emphasis columns, live.
        self._type_picker_active: bool = False
        self._type_picker_size_idx: int = 1   # "" (medium)
        self._type_picker_emph_idx: int = 0
        self._type_picker_font: str = ""      # "" hand / "mono" — notes only
        self._type_picker_outline: bool = False   # display styles — notes only
        self._type_picker_shadow: bool = False
        # id -> (textsize, emphasis, note_style|None); style restored for notes.
        self._type_picker_original: dict[str, tuple] = {}
        self._mode_badge: QGraphicsTextItem | None = None
        self._mode_badge_bg: QGraphicsRectItem | None = None

        # Minimap
        self._minimap_visible: bool = True
        self._minimap_rect: QRectF = QRectF()
        self._minimap_panel_rect: QRectF = QRectF()
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
        # Zoom-limit feedback: a rubber-band bounce + throttled toast when the
        # user tries to zoom past the min/max bounds.
        self._bounce_timeline: QTimeLine | None = None
        self._bounce_active: bool = False
        self._bounce_dir: float = 1.0
        self._bounce_last_s: float = 1.0
        self._bounce_base: QTransform = QTransform()
        self._bounce_prev_anchor = QGraphicsView.ViewportAnchor.AnchorUnderMouse
        self._zoom_limit_toast_at: float = 0.0


        # Hide-notes toggle (Shift+N) — focus on the graph
        self._notes_hidden: bool = False

        # Ghost preview shown at cursor while in RECT / TEXT mode
        self._create_preview: QGraphicsItem | None = None
        self._create_preview_pos: QPointF | None = None

        # Navigation jumplist (Ctrl+O / Ctrl+I)
        self._nav_stack: list[QRectF] = []
        self._nav_index: int = -1
        self._NAV_STACK_CAP = 50

        # Focus-zoom toggle (gz): the viewport to fly back to, and the items we
        # focused on (so re-pressing after changing the selection re-focuses).
        self._focus_return: QRectF | None = None
        self._focus_target_ids: set[str] = set()

        # Bookmarks & flows
        self._flow_player: FlowPlayer | None = None
        self._recording_flow: Flow | None = None
        self._flow_overlay: dict | None = None
        # Flows-panel edit target: a captured bookmark is inserted after the
        # selected step of this flow (instead of just creating a loose one).
        self._active_flow: Flow | None = None
        self._active_step_index: int = -1
        # Transient confirmation overlays (bookmark goto, snap lock-in pulse,
        # delete pop) — each a dict {rect, color, mode, p} eased 0->1 then
        # dropped. Drawn in scene coords so they hug the items.
        self._flashes: list[dict] = []
        # Live smart-alignment guides while dragging a single element. Refs are
        # the peer anchor rects gathered once at drag start; guides are the
        # lines to draw this frame.
        self._drag_guides: list[dict] = []
        self._drag_guide_refs: list[dict] | None = None
        self._drag_lead_item = None

        # Graph navigation (Alt held)
        self._graph_nav_active = False
        self._graph_nav_labels: list[QGraphicsRectItem | QGraphicsSimpleTextItem] = []
        self._graph_nav_map: dict[str, str] = {}  # label key -> target node id
        self._graph_nav_warning: list[QGraphicsItem] = []

        # Debug overlay
        self._debug_overlay: bool = False
        self._debug_last_shortcut: str = ""
        self._debug_fade_timer: QTimer | None = None

        # Toast — a transient HUD pill (bottom-center) confirming user actions.
        # Info/warn auto-fade; errors stick until the next toast so they can't be
        # missed.
        self._toast_text: str = ""
        self._toast_kind: str = "info"   # "info" | "warn" | "error"
        self._toast_timer: QTimer | None = None

        # Live fade animations (kept referenced so they aren't GC'd mid-run).
        self._fade_anims: set = set()

        # Complexity heatmap state
        self._complexity_active: bool = False
        self._complexity_node_heat: dict[str, float] = {}
        self._complexity_saved: list[tuple] = []

        # Arrow dim state
        self._arrows_dimmed: bool = False

        # Note-selection annotation highlight state
        self._note_highlight_active: bool = False

        # Subgraph focus filter state
        self._focus_active: bool = False
        self._focus_node_id: str | None = None
        self._focus_direction: str = "all"   # "all", "forward", "backward"
        self._focus_depth: int = 0           # 0 = unlimited, 1 = 1-hop

        # Search state
        self._search_active = False
        self._search_badge_opacity = 0.0   # 0..1 — fades the input badge in/out
        self._search_text = ""
        self._search_matches: list[BoxItem | NoteItem] = []
        self._search_index = 0
        self._search_filter_active: bool = False
        self._search_dimmed_ids: set[str] = set()

        self.arrow_update_needed.connect(self._redraw_arrows)
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        grid_color = HEATMAP_GRID_COLOR if self._complexity_active else GRID_COLOR
        border_color = HEATMAP_CONTENT_BORDER if self._complexity_active else CONTENT_BORDER_COLOR
        if self._grid_shown:
            spacing = self.GRID_SPACING
            # Skip the grid when zoomed out far enough that it would be a dense
            # smear anyway — drawing a point per cell across a huge visible area
            # is O(area) and makes panning crawl.
            cols = (rect.width() / spacing) + 1
            rows = (rect.height() / spacing) + 1
            if cols * rows <= 20000:
                left = int(rect.left()) - (int(rect.left()) % spacing)
                top = int(rect.top()) - (int(rect.top()) % spacing)
                # Snap mode draws small crosses (snap targets) so it reads
                # distinctly from the plain dots of visual-only mode.
                snap = self._grid_snap
                painter.setPen(QPen(grid_color, 2.0))
                x = left
                while x <= rect.right():
                    y = top
                    while y <= rect.bottom():
                        if snap:
                            painter.drawLine(int(x) - 2, int(y), int(x) + 2, int(y))
                            painter.drawLine(int(x), int(y) - 2, int(x), int(y) + 2)
                        else:
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
        # Scene-coord overlays first (the painter is still in scene space here);
        # the viewport-space HUD below resets the transform.
        self._draw_drag_guides(painter)
        self._draw_flashes(painter)
        self._draw_complexity_legend(painter)
        self._draw_minimap(painter)
        self._draw_search_badge(painter)
        self._draw_flow_overlay(painter)
        self._draw_debug_overlay(painter)
        self._draw_color_picker(painter)
        self._draw_icon_picker(painter)
        self._draw_type_picker(painter)
        self._draw_toast(painter)

    # Grid mode cycle order for the # key / "grid" action.
    _GRID_CYCLE = ("off", "visual", "snap")
    _GRID_LABELS = {"off": "off", "visual": "grid", "snap": "grid + snap"}

    @property
    def _grid_shown(self) -> bool:
        """Whether the grid dots are drawn."""
        return self._grid_mode in ("visual", "snap")

    @property
    def _grid_snap(self) -> bool:
        """Whether movement snaps to the grid."""
        return self._grid_mode == "snap"

    def toggle_grid(self):
        """Cycle the grid mode (off -> visual -> snap) and remember it."""
        idx = self._GRID_CYCLE.index(self._grid_mode)
        self._grid_mode = self._GRID_CYCLE[(idx + 1) % len(self._GRID_CYCLE)]
        QSettings("Grafli", "Grafli").setValue("grid/mode", self._grid_mode)
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

        # Manage create-mode ghost preview
        if mode in (Mode.RECT, Mode.TEXT):
            self._refresh_create_preview()
        else:
            self._clear_create_preview()

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
        self._clear_note_selection_highlight()
        if self._rect_preview:
            self._scene.removeItem(self._rect_preview)
            self._rect_preview = None
            self._rect_origin = None
        if self._connect_line:
            self._scene.removeItem(self._connect_line)
            self._connect_line = None
            self._connect_source = None
        self._commit_editor()
        if self._zen_editor:
            self._zen_editor.close()
            self._zen_editor = None
            self._zen_target = None
        if self._fuzzy_overlay:
            self._fuzzy_overlay.close()
            self._fuzzy_overlay = None

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

    def _item_id(self, item: BoxItem | NoteItem | ImageItem) -> str:
        if isinstance(item, BoxItem):
            return item.box.id
        if isinstance(item, ImageItem):
            return item.image.id
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

    def _elem_min_dim(self, elem) -> float:
        """Smaller side of an element — its visual 'weight' for connectors."""
        if isinstance(elem, (Box, Image)):
            return min(elem.w, elem.h)
        note_item = self._note_items.get(elem.id)
        if note_item:
            r = note_item.sceneBoundingRect()
            return min(r.width(), r.height())
        return CONNECTOR_REF_SIZE

    def _connector_width(self, from_elem, to_elem) -> float:
        """Graph-arrow thickness, scaled to the size of the nodes it links.

        Referenced to a default-sized box and capped by the *smaller* endpoint,
        so a connector is never heavier than the lightest node it touches.
        """
        conn = min(self._elem_min_dim(from_elem), self._elem_min_dim(to_elem))
        width = ARROW_WIDTH * (conn / CONNECTOR_REF_SIZE) ** 0.5
        return max(CONNECTOR_WIDTH_MIN, min(CONNECTOR_WIDTH_MAX, width))

    @property
    def board(self) -> Board | None:
        return self._board

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
        # A fresh board invalidates any in-flight flow recording/playback.
        self._recording_flow = None
        if self._flow_player is not None:
            self._flow_player.stop()
        self._rebuild_scene()
        self.flows_changed.emit()

    def snapshot_state(self) -> ViewState:
        """Capture view state for buffer switching."""
        t = self.transform()
        sel_boxes = [
            bid for bid, item in self._box_items.items() if item.isSelected()
        ]
        sel_notes = [
            nid for nid, item in self._note_items.items() if item.isSelected()
        ]
        return ViewState(
            undo_stack=list(self._undo_stack),
            redo_stack=list(self._redo_stack),
            dirty=self._dirty,
            transform=(t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy()),
            h_scroll=self.horizontalScrollBar().value(),
            v_scroll=self.verticalScrollBar().value(),
            selected_box_ids=sel_boxes,
            selected_note_ids=sel_notes,
        )

    def restore_state(self, vs: ViewState):
        """Apply a previously captured view state."""
        self._undo_stack = list(vs.undo_stack)
        self._redo_stack = list(vs.redo_stack)
        self._dirty = vs.dirty
        if vs.transform:
            m11, m12, m21, m22, dx, dy = vs.transform
            self.setTransform(QTransform(m11, m12, m21, m22, dx, dy))
        self.horizontalScrollBar().setValue(vs.h_scroll)
        self.verticalScrollBar().setValue(vs.v_scroll)
        self._scene.clearSelection()
        for bid in vs.selected_box_ids:
            if bid in self._box_items:
                self._box_items[bid].setSelected(True)
        for nid in vs.selected_note_ids:
            if nid in self._note_items:
                self._note_items[nid].setSelected(True)
        self._update_status_zoom()

    def _rebuild_scene(self):
        self._scene.clear()
        self._box_items.clear()
        self._arrow_items.clear()
        self._note_items.clear()
        self._image_items.clear()
        self._editor = None
        self._edit_target = None
        self._note_proxy = None
        self._note_widget = None
        self._rect_preview = None
        self._connect_line = None
        self._connect_source = None
        self._selected_arrow = None
        self._selected_arrow_items.clear()
        self._grow_preview = None
        self._mode_badge = None
        self._mode_badge_bg = None
        self._box_mode = ""
        self._arrow_mode = ""
        self._focus_active = False
        self._focus_node_id = None
        self._focus_direction = "all"
        self._focus_depth = 0
        self._notes_hidden = False
        self._complexity_active = False
        self._complexity_node_heat.clear()
        self._complexity_saved.clear()
        self._note_highlight_active = False
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

        base_dir = ""
        window = self.window()
        if hasattr(window, '_file_path') and window._file_path:
            base_dir = str(window._file_path.parent)
        for image in self._board.images:
            item = ImageItem(image, base_dir=base_dir)
            self._scene.addItem(item)
            self._image_items[image.id] = item

        self._auto_parent_all()
        for box_id, item in self._box_items.items():
            is_parent = self._has_children(box_id)
            if item._is_parent != is_parent:
                item._is_parent = is_parent
                item._apply_color()
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

            # Kind drives styling now, not endpoint type: a note joined by a
            # graph edge renders as a normal directional arrow.
            is_annotation = self._is_annotation_link(fwd)
            both_boxes = isinstance(from_elem, Box) and isinstance(to_elem, Box)

            if is_annotation:
                arrow_color = ANNOTATION_ARROW_COLOR
                arrow_width = ANNOTATION_ARROW_WIDTH
                draw_head_to = False
                draw_head_from = False
            else:
                edge_kind = parse_edge_label(fwd.label).kind
                if not edge_kind and rev:
                    edge_kind = parse_edge_label(rev.label).kind
                arrow_color = EDGE_KIND_COLORS.get(edge_kind, ARROW_COLOR)
                # Thickness tracks the size of the linked nodes (visual hierarchy).
                arrow_width = self._connector_width(from_elem, to_elem)

            # Arrowheads grow with the line, but gently, so they stay tasteful.
            head_size = ARROWHEAD_SIZE * (arrow_width / ARROW_WIDTH) ** 0.6

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
                head = QGraphicsPolygonItem(_arrowhead_polygon(end, angle, head_size))
                head.setPen(QPen(arrow_color, 1))
                head.setBrush(QBrush(arrow_color))
                head.setData(0, fwd)
                self._scene.addItem(head)
                self._arrow_items.append(head)

            # Backward arrowhead (at from_id end)
            if draw_head_from:
                back_angle = math.atan2(-dy, -dx)
                back_head = QGraphicsPolygonItem(
                    _arrowhead_polygon(start, back_angle, head_size)
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
            if fwd.url:
                label_tooltips.append(fwd.url)
            if rev and rev.label:
                label_texts.append(rev.label)
            if rev and rev.url:
                label_tooltips.append(rev.url)

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
        if self._arrows_dimmed and not self._focus_active and not self._complexity_active:
            for gfx in self._arrow_items:
                gfx.setOpacity(0.08)

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
        arrow_opacity = 0.08 if self._arrows_dimmed else 1.0
        for gfx in self._arrow_items:
            gfx.setOpacity(arrow_opacity)

        self._update_focus_status()

    # ── View toggles ───────────────────────────────────────

    def _toggle_arrows_dimmed(self):
        """Toggle low-opacity dim on all arrows."""
        self._arrows_dimmed = not self._arrows_dimmed
        if not self._focus_active and not self._complexity_active:
            opacity = 0.08 if self._arrows_dimmed else 1.0
            for gfx in self._arrow_items:
                gfx.setOpacity(opacity)
            self.viewport().update()

    def _toggle_complexity(self):
        """Toggle the complexity-analysis heatmap overlay."""
        if self._complexity_active:
            self._clear_complexity_heatmap()
        else:
            if self._focus_active:
                self._clear_focus_filter()
            self._complexity_active = True
            self._apply_complexity_heatmap()

    def _toggle_notes_hidden(self):
        """Toggle low-opacity dim on all notes and their connector arrows.

        Uses the same 0.08 dim level as the arrow-dim toggle (``,``) so
        the diagram reads as the bare graph while keeping notes faintly
        visible (and still selectable for editing).
        """
        self._notes_hidden = not self._notes_hidden
        self._apply_notes_hidden()

    def _apply_notes_hidden(self):
        from grafli.format import Arrow as _Arrow
        opacity = 0.08 if self._notes_hidden else 1.0
        for note_item in self._note_items.values():
            note_item.setOpacity(opacity)
        for gfx in self._arrow_items:
            arrow = gfx.data(0)
            if not isinstance(arrow, _Arrow):
                continue
            touches_note = (
                arrow.from_id in self._note_items
                or arrow.to_id in self._note_items
            )
            if touches_note:
                gfx.setOpacity(opacity)

    # ── Create-mode ghost preview ──────────────────────────

    def _refresh_create_preview(self):
        """Rebuild the cursor ghost for the active create mode."""
        self._clear_create_preview()
        if self._mode == Mode.RECT:
            self._build_box_preview()
        elif self._mode == Mode.TEXT:
            self._build_note_preview()
        if self._create_preview is not None:
            pos = self._create_preview_pos
            if pos is None:
                pos = self.mapToScene(
                    self.viewport().rect().center()
                )
            self._update_create_preview_pos(pos)

    def _clear_create_preview(self):
        if self._create_preview is not None:
            self._scene.removeItem(self._create_preview)
            self._create_preview = None

    def _build_box_preview(self):
        w, h = DEFAULT_BOX_W, DEFAULT_BOX_H
        rect = QRectF(0, 0, w, h)
        item = QGraphicsRectItem(rect)
        pen = QPen(BOX_BORDER, 1, Qt.PenStyle.DashLine)
        item.setPen(pen)
        item.setBrush(QBrush(BOX_FILL))
        label = QGraphicsSimpleTextItem("A Node", item)
        label_font = QFont(FONT_FAMILY, BOX_FONT_SIZES.get("", 13))
        label.setFont(label_font)
        label.setBrush(QBrush(BOX_BORDER))
        lr = label.boundingRect()
        label.setPos((w - lr.width()) / 2, (h - lr.height()) / 2)
        item.setOpacity(0.4)
        item.setZValue(1000)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._scene.addItem(item)
        self._create_preview = item

    def _build_note_preview(self):
        item = QGraphicsSimpleTextItem("Some text ...")
        item.setFont(QFont(FONT_FAMILY, BOX_FONT_SIZES.get("", 13)))
        item.setBrush(QBrush(NOTE_PEN_COLOR))
        item.setOpacity(0.4)
        item.setZValue(1000)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._scene.addItem(item)
        self._create_preview = item

    def _update_create_preview_pos(self, scene_pos: QPointF):
        self._create_preview_pos = scene_pos
        if self._create_preview is None:
            return
        if self._mode == Mode.RECT:
            self._create_preview.setPos(
                scene_pos.x() - DEFAULT_BOX_W / 2,
                scene_pos.y() - DEFAULT_BOX_H / 2,
            )
        elif self._mode == Mode.TEXT:
            self._create_preview.setPos(scene_pos)

    def _update_note_selection_highlight(self):
        """Dim unrelated items when a single connected annotation is selected.

        A note or image is treated as an annotation of the elements it connects
        to via arrows. When exactly one such item is selected and it has at
        least one arrow connection, all other items are dimmed so the annotation
        target becomes visually obvious. Skipped when another opacity-owning
        mode is active (focus filter, complexity heatmap, manual arrow dim).
        """
        if self._focus_active or self._complexity_active or self._arrows_dimmed:
            if self._note_highlight_active:
                self._clear_note_selection_highlight()
            return

        selected = self._scene.selectedItems()
        if not (len(selected) == 1
                and isinstance(selected[0], (NoteItem, ImageItem))
                and self._board):
            if self._note_highlight_active:
                self._clear_note_selection_highlight()
            return

        anchor_id = self._item_id(selected[0])
        # Node-ness wins: an annotation that participates in ANY graph edge is a
        # real node, so it never gets the annotation spotlight — even if it also
        # has annotation links.
        touching = [a for a in self._board.arrows
                    if a.from_id == anchor_id or a.to_id == anchor_id]
        if any(self._is_graph_edge(a) for a in touching):
            if self._note_highlight_active:
                self._clear_note_selection_highlight()
            return

        # Otherwise it's a pure annotation: its annotation-link targets become
        # the spotlight.
        connected: set[str] = set()
        for arrow in touching:
            if not self._is_annotation_link(arrow):
                continue
            if arrow.from_id == anchor_id:
                connected.add(arrow.to_id)
            elif arrow.to_id == anchor_id:
                connected.add(arrow.from_id)

        if not connected:
            if self._note_highlight_active:
                self._clear_note_selection_highlight()
            return

        keep = connected | {anchor_id}
        dim = 0.25

        for box_id, item in self._box_items.items():
            op = 1.0 if box_id in keep else dim
            item.setOpacity(op)
            item._label.setOpacity(op)
        for nid, item in self._note_items.items():
            item.setOpacity(1.0 if nid in keep else dim)
        for iid, item in self._image_items.items():
            item.setOpacity(1.0 if iid in keep else dim)
        for gfx in self._arrow_items:
            arrow = gfx.data(0)
            if not isinstance(arrow, Arrow):
                gfx.setOpacity(dim)
                continue
            touches_anchor = ((arrow.from_id == anchor_id
                               or arrow.to_id == anchor_id)
                              and self._is_annotation_link(arrow))
            gfx.setOpacity(1.0 if touches_anchor else dim)

        self._note_highlight_active = True

    def _clear_note_selection_highlight(self):
        """Restore full opacity after a note-selection highlight."""
        if not self._note_highlight_active:
            return
        for item in self._box_items.values():
            item.setOpacity(1.0)
            item._label.setOpacity(1.0)
        for item in self._note_items.values():
            item.setOpacity(1.0)
        for item in self._image_items.values():
            item.setOpacity(1.0)
        for gfx in self._arrow_items:
            gfx.setOpacity(1.0)
        self._note_highlight_active = False

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
                or any(n.parent == box_id for n in self._board.notes)
                or any(i.parent == box_id for i in self._board.images))

    def _descendants(self, box_id: str) -> list[BoxItem | NoteItem | ImageItem]:
        """Return all BoxItems, NoteItems and ImageItems that are descendants of box_id."""
        result: list[BoxItem | NoteItem | ImageItem] = []
        for bid, item in self._box_items.items():
            if item.box.parent == box_id:
                result.append(item)
                result.extend(self._descendants(bid))
        for nid, item in self._note_items.items():
            if item.note.parent == box_id:
                result.append(item)
        for iid, item in self._image_items.items():
            if item.image.parent == box_id:
                result.append(item)
        return result

    def _descendant_ids(self, box_id: str) -> list[str]:
        """Ids of all boxes/notes/images nested under ``box_id`` (recursive)."""
        out: list[str] = []
        if not self._board:
            return out
        for b in self._board.boxes:
            if b.parent == box_id:
                out.append(b.id)
                out.extend(self._descendant_ids(b.id))
        for n in self._board.notes:
            if n.parent == box_id:
                out.append(n.id)
        for img in self._board.images:
            if img.parent == box_id:
                out.append(img.id)
        return out

    def _expand_focus_to_subtrees(self, ids: list[str]) -> list[str]:
        """Add every parent's descendants to a focus list (order-preserving).

        Isolating a parent box on its own would hide its children and show an
        empty container; including the subtree keeps the contents visible.
        Shared by manual scoped capture and the auto-flow generator.
        """
        seen: set[str] = set()
        out: list[str] = []
        for fid in ids:
            if fid not in seen:
                seen.add(fid)
                out.append(fid)
            if self._board and self._board.box_by_id(fid) and self._has_children(fid):
                for d in self._descendant_ids(fid):
                    if d not in seen:
                        seen.add(d)
                        out.append(d)
        return out

    def _snap_selection_to_slide_ratio(self):
        """Reshape the selected box(es) to the PDF slide content ratio.

        A slide-frame container should match the exported slide's aspect ratio
        so an auto-flow export fills the page without letterboxing. This holds
        each box's width and top-left and sets its height = width / ratio — a
        purely geometric snap: content that no longer fits spills past the box
        (the visible overload cue) rather than the box growing to absorb it.
        Idempotent, so it doubles as the "fix it back" after a drag distorted a
        frame; applies to every selected box for batch reshaping.
        """
        from grafli.pdfexport import slide_content_ratio

        boxes = [i for i in self._scene.selectedItems()
                 if isinstance(i, BoxItem)]
        if not boxes:
            self._record_shortcut("slide-ratio: select a container box first")
            return
        ratio = slide_content_ratio(self._board)
        targets = []
        for item in boxes:
            new_h = max(MIN_BOX_SIZE, round(item.box.w / ratio))
            if abs(new_h - item.box.h) >= 1:
                targets.append((item, new_h))
        if not targets:
            self._record_shortcut(f"already at slide ratio {ratio:.2f}")
            return
        self._push_undo()
        for item, new_h in targets:
            w = item.box.w
            item.box.h = new_h
            item.setRect(0, 0, w, new_h)
            item._label.setTextWidth(w - 16)
            item._position_label()
            item._update_handles()
        self._update_mode_badge_pos()
        self.arrow_update_needed.emit()
        self.mark_dirty()
        self._record_shortcut(
            f"snapped {len(targets)} box(es) to slide ratio {ratio:.2f}")

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
            if d > max_depth:
                max_depth = d
        # Parents (containers) stay at their depth — behind arrows
        # Arrow lines/heads sit above parents
        arrow_line_z = max_depth + 1
        # Leaf boxes (no children) sit above arrows
        leaf_z = max_depth + 2
        # Notes and arrow labels above leaf boxes
        note_z = max_depth + 3
        # Box labels always on top
        box_label_z = max_depth + 4
        for box_id, item in self._box_items.items():
            d = self._box_depth(box_id)
            if self._has_children(box_id):
                item.setZValue(d)
            else:
                item.setZValue(leaf_z + d)
            item._label.setZValue(box_label_z)
        for note_item in self._note_items.values():
            if note_item.note.parent:
                pd = self._box_depth(note_item.note.parent) + 1
                note_item.setZValue(max(pd, note_z))
            else:
                note_item.setZValue(note_z)
        for img_item in self._image_items.values():
            if img_item.image.parent:
                pd = self._box_depth(img_item.image.parent) + 1
                img_item.setZValue(max(pd, note_z))
            else:
                img_item.setZValue(note_z)
        for item in self._arrow_items:
            if isinstance(item, LabelItem):
                item.setZValue(note_z)
            else:
                item.setZValue(arrow_line_z)

    # ── Encapsulate: wrap the selection in a new parent box ──

    def _encapsulate_selection(self):
        """Wrap the selected element(s) in a new parent box that contains them.

        The new box is sized to enclose the selection (with room for a title),
        becomes the parent of the selection's top-level items (inner parent →
        child nesting is preserved), inherits the selection's common parent if
        they all share one, and is selected with its label editor opened.
        """
        if not self._board:
            return
        selected = [i for i in self._scene.selectedItems()
                    if isinstance(i, (BoxItem, NoteItem, ImageItem))]
        if not selected:
            return

        def model_of(item):
            if isinstance(item, BoxItem):
                return item.box
            if isinstance(item, ImageItem):
                return item.image
            return item.note

        def model_rect(item) -> QRectF:
            if isinstance(item, NoteItem):
                r = item.sceneBoundingRect()
                return QRectF(r.x(), r.y(), r.width(), r.height())
            m = model_of(item)
            return QRectF(m.x, m.y, m.w, m.h)

        selected_ids = {self._item_id(i) for i in selected}

        # Bounding box over the selection and everything nested inside it.
        bbox = None
        stack, seen = list(selected), set()
        while stack:
            it = stack.pop()
            iid = self._item_id(it)
            if iid in seen:
                continue
            seen.add(iid)
            r = model_rect(it)
            bbox = r if bbox is None else bbox.united(r)
            if isinstance(it, BoxItem):
                stack.extend(self._descendants(iid))
        if bbox is None:
            return

        # Reparent only the selection's top-level items; keep inner nesting.
        top_level = [i for i in selected
                     if model_of(i).parent not in selected_ids]
        parents = {model_of(i).parent for i in top_level}
        new_parent = parents.pop() if len(parents) == 1 else ""

        self._push_undo()

        pad_x, pad_top, pad_bottom = 24, 44, 24
        box_id = self._board.next_box_id()
        box = Box(
            id=box_id, label="Group",
            x=bbox.left() - pad_x, y=bbox.top() - pad_top,
            w=bbox.width() + 2 * pad_x,
            h=bbox.height() + pad_top + pad_bottom,
            color=self._last_box_color, textsize=self._last_box_textsize,
            parent=new_parent,
        )
        self._board.add_box(box)
        item = BoxItem(box)
        self._scene.addItem(item)
        self._scene.addItem(item._label)
        self._box_items[box_id] = item

        for i in top_level:
            model_of(i).parent = box_id

        # Refresh container styling + stacking now the hierarchy changed.
        for bid, bitem in self._box_items.items():
            is_parent = self._has_children(bid)
            if bitem._is_parent != is_parent:
                bitem._is_parent = is_parent
                bitem._apply_color()
        self._update_z_values()
        item.refresh_auto_layout()
        self._redraw_arrows()
        self._update_scene_rect()
        self._invalidate_graph_stats()
        self.mark_dirty()

        self._scene.clearSelection()
        item.setSelected(True)
        self._start_editing(item)

    def _refresh_auto_layout(self, box_id: str):
        """Refresh auto-layout for a box when its children change."""
        if box_id in self._box_items:
            self._box_items[box_id].refresh_auto_layout()

    def _keep_explicit_parent(self, item_id: str, parent_id: str) -> bool:
        """Whether an authored ``>parent`` should be preserved on load.

        Keep it when it names an existing box and does not form a cycle. This
        respects intent for children that overflow their box (a note wider than
        its container is still authored into it) instead of geometric reparenting
        yanking them up to a grandparent that happens to enclose their bounds.
        """
        if not parent_id or parent_id not in self._box_items:
            return False
        cur, seen = parent_id, set()
        while cur and cur not in seen:
            if cur == item_id:
                return False                # cycle: don't keep
            seen.add(cur)
            cur = self._box_items[cur].box.parent if cur in self._box_items else ""
        return True

    def _auto_parent_all(self):
        """Assign a parent to every box/note geometrically contained in a box.

        An explicit authored ``>parent`` wins — only items with no (or a
        dangling) parent are nested by geometry, so overflowing children keep
        the container they were authored into.
        """
        boxes = list(self._box_items.values())
        # Drop self-references up front so the descendant walk can't recurse.
        for item in boxes:
            if item.box.parent == item.box.id:
                item.box.parent = ""
        for item in boxes:
            b = item.box
            if self._keep_explicit_parent(b.id, b.parent):
                continue
            item_rect = QRectF(b.x, b.y, b.w, b.h)
            desc_ids = {
                d.box.id
                for d in self._descendants(b.id)
                if isinstance(d, BoxItem)
            }
            best, best_area = "", float("inf")
            for oid, oitem in self._box_items.items():
                if oid == b.id or oid in desc_ids:
                    continue
                o = oitem.box
                if QRectF(o.x, o.y, o.w, o.h).contains(item_rect):
                    a = o.w * o.h
                    if a < best_area:
                        best, best_area = oid, a
            b.parent = best
        for nitem in self._note_items.values():
            n = nitem.note
            if self._keep_explicit_parent(n.id, n.parent):
                continue
            sr = nitem.sceneBoundingRect()
            item_rect = QRectF(sr.x(), sr.y(), sr.width(), sr.height())
            best, best_area = "", float("inf")
            for oid, oitem in self._box_items.items():
                o = oitem.box
                if QRectF(o.x, o.y, o.w, o.h).contains(item_rect):
                    a = o.w * o.h
                    if a < best_area:
                        best, best_area = oid, a
            n.parent = best

    @staticmethod
    def _item_elem(item: BoxItem | NoteItem | ImageItem):
        """The underlying dataclass (Box/Note/Image) carried by a scene item."""
        if isinstance(item, BoxItem):
            return item.box
        if isinstance(item, NoteItem):
            return item.note
        return item.image

    def _item_fit_rect(self, item) -> QRectF:
        """Scene rect used for containment fitting, matching ``_fit_parent_rect``.

        Boxes use their exact geometry; notes/images use their scene bounds.
        """
        if isinstance(item, BoxItem):
            b = item.box
            return QRectF(b.x, b.y, b.w, b.h)
        sr = item.sceneBoundingRect()
        return QRectF(sr.x(), sr.y(), sr.width(), sr.height())

    def _check_nesting(self, item: BoxItem | NoteItem | ImageItem, cursor_scene: QPointF | None = None):
        """Update parent of a box, note or image after it has been moved.

        Nesting follows the mouse cursor: the dragged item becomes a child of
        the smallest box the cursor is over, and detaches when the cursor is
        over no box. Falls back to the item's centre if no cursor is given.
        """
        if not self._board:
            return

        elem = self._item_elem(item)
        item_id = elem.id
        if isinstance(item, BoxItem):
            desc_ids = {d.box.id for d in self._descendants(item_id) if isinstance(d, BoxItem)}
        else:
            desc_ids = set()

        if cursor_scene is not None:
            point = cursor_scene
        else:
            point = item.sceneBoundingRect().center()

        best_parent = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == item_id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(point):
                area = other.w * other.h
                if area < best_area:
                    best_area = area
                    best_parent = other_id

        old_parent = elem.parent
        elem.parent = best_parent or ""

        if elem.parent != old_parent:
            self._update_z_values()
            if old_parent and old_parent in self._box_items:
                old_item = self._box_items[old_parent]
                was_parent = old_item._is_parent
                old_item._is_parent = self._has_children(old_parent)
                if old_item._is_parent != was_parent:
                    old_item._apply_color()
                    if not old_item._is_parent:
                        old_item._fit_to_label()
                self._refresh_auto_layout(old_parent)
            if elem.parent and elem.parent in self._box_items:
                new_item = self._box_items[elem.parent]
                was_parent = new_item._is_parent
                new_item._is_parent = self._has_children(elem.parent)
                if new_item._is_parent != was_parent:
                    new_item._apply_color()
                self._refresh_auto_layout(elem.parent)
            self.mark_dirty()

        # Keep the (possibly unchanged) parent large enough to contain the
        # item, even when it was moved/resized within its existing parent.
        if elem.parent and elem.parent in self._box_items:
            self._grow_parent_to_fit_children(elem.parent)

    def _fit_parent_rect(self, parent_id: str, extra_rect: QRectF | None = None) -> QRectF | None:
        """Outer rect a parent must occupy to contain its children (grow-only).

        Unions the parent's direct children (boxes/notes/images) with an
        optional ``extra_rect`` (e.g. a child being dragged but not yet
        reparented), padded, and with the headline band reserved at the top.
        Never shrinks below the parent's current bounds. Returns None when
        there is nothing to fit. Shared by the on-release grow and the live
        drag preview so the two can never drift.
        """
        if not self._board or parent_id not in self._box_items:
            return None
        parent_item = self._box_items[parent_id]
        parent = parent_item.box

        child_rect: QRectF | None = None if extra_rect is None else QRectF(extra_rect)
        for b in self._board.boxes:
            if b.parent == parent_id:
                r = QRectF(b.x, b.y, b.w, b.h)
                child_rect = r if child_rect is None else child_rect.united(r)
        for nitem in self._note_items.values():
            if nitem.note.parent == parent_id:
                child_rect = self._unite_scene_rect(child_rect, nitem)
        for iitem in self._image_items.values():
            if iitem.image.parent == parent_id:
                child_rect = self._unite_scene_rect(child_rect, iitem)
        if child_rect is None:
            return None

        pad = LAYOUT_PADDING
        # Reserve the headline band at the top so children clear the label.
        # Parents default to a top headline unless an explicit anchor says otherwise.
        top_reserve = pad
        top_anchored = (
            parent.anchor in ("topleft", "topcenter")
            or (not parent.anchor and (self._has_children(parent_id) or extra_rect is not None))
        )
        if top_anchored:
            top_reserve = parent_item._label.boundingRect().height() + 16
        left = min(parent.x, child_rect.left() - pad)
        top = min(parent.y, child_rect.top() - top_reserve)
        right = max(parent.x + parent.w, child_rect.right() + pad)
        bottom = max(parent.y + parent.h, child_rect.bottom() + pad)
        return QRectF(left, top, right - left, bottom - top)

    def _grow_parent_to_fit_children(self, parent_id: str):
        """Grow a parent box so it contains all its direct children, plus padding.

        Used after an interactive drop, where a node may be nested while still
        sticking out of the parent. Only grows — never shrinks — so existing
        layout is left undisturbed.
        """
        target = self._fit_parent_rect(parent_id)
        if target is None:
            return
        parent = self._box_items[parent_id].box
        if (target.x(), target.y(), target.right(), target.bottom()) != (
            parent.x, parent.y, parent.x + parent.w, parent.y + parent.h
        ):
            self._box_items[parent_id].set_geometry(
                target.x(), target.y(), target.width(), target.height()
            )

    @staticmethod
    def _unite_scene_rect(child_rect: QRectF | None, item) -> QRectF:
        sr = item.sceneBoundingRect()
        r = QRectF(sr.x(), sr.y(), sr.width(), sr.height())
        return r if child_rect is None else child_rect.united(r)

    # ── Scale a selection (corner-drag, about a shared pivot) ──

    def _scale_members(self, members, fx: float, fy: float,
                       font_factor: float, pivot: QPointF) -> None:
        """Scale each (item, start_rect, start_px) about ``pivot``.

        Positions and sizes use the per-axis factors; fonts use ``font_factor``
        (uniform). Child-move propagation is suppressed so a parent and its
        children in the same selection don't get moved twice.
        """
        if not members:
            return
        self._propagating_move = True
        self._suppress_child_updates = True
        try:
            for item, start_rect, start_px in members:
                self._scale_member(item, start_rect, start_px,
                                   fx, fy, font_factor, pivot)
        finally:
            self._suppress_child_updates = False
            self._propagating_move = False
        self.arrow_update_needed.emit()
        self.mark_dirty()

    def _scale_member(self, item, start_rect: QRectF, start_px,
                      fx: float, fy: float, font_factor: float,
                      pivot: QPointF) -> None:
        px, py = pivot.x(), pivot.y()
        nx = px + (start_rect.x() - px) * fx
        ny = py + (start_rect.y() - py) * fy
        if isinstance(item, BoxItem):
            nw = max(MIN_BOX_SIZE, start_rect.width() * fx)
            nh = max(MIN_BOX_SIZE, start_rect.height() * fy)
            if start_px is not None:
                item.box.textsize = str(
                    int(max(MIN_SCALE_FONT_PT, round(start_px * font_factor))))
                item._label.setFont(item._box_font())
            item.set_geometry(nx, ny, nw, nh)
        elif isinstance(item, NoteItem):
            if start_px is not None:
                item.set_textsize(str(
                    int(max(MIN_SCALE_FONT_PT, round(start_px * font_factor)))))
            item.setPos(nx, ny)
        elif isinstance(item, ImageItem):
            im = item.image
            im.x, im.y = nx, ny
            im.w = max(item._MIN_SIZE, start_rect.width() * fx)
            im.h = max(item._MIN_SIZE, start_rect.height() * fy)
            item.setPos(nx, ny)
            item.prepareGeometryChange()
            item._update_handles()
            item.update()

    def _update_reparent_highlight(self, cursor_scene: QPointF | None = None):
        """Preview the auto-grow of the box under the cursor during a drag.

        Draws a dashed rectangle at the target parent's projected grown bounds
        (children plus the dragged item, with padding and headline reserve). No
        rectangle means the drop would detach the item to top level.
        """
        selected = [i for i in self._scene.selectedItems() if isinstance(i, (BoxItem, NoteItem, ImageItem))]
        if len(selected) != 1 or cursor_scene is None:
            self._clear_reparent_highlight()
            return

        item = selected[0]
        item_id = self._item_elem(item).id
        if isinstance(item, BoxItem):
            desc_ids = {d.box.id for d in self._descendants(item_id) if isinstance(d, BoxItem)}
        else:
            desc_ids = set()

        best_parent_id = None
        best_area = float('inf')
        for other_id, other_item in self._box_items.items():
            if other_id == item_id or other_id in desc_ids:
                continue
            other = other_item.box
            other_rect = QRectF(other.x, other.y, other.w, other.h)
            if other_rect.contains(cursor_scene):
                area = other.w * other.h
                if area < best_area:
                    best_area = area
                    best_parent_id = other_id

        if not best_parent_id:
            self._clear_reparent_highlight()
            return

        target = self._fit_parent_rect(best_parent_id, self._item_fit_rect(item))
        if target is None:
            self._clear_reparent_highlight()
            return
        self._show_grow_preview(target)

    def _show_grow_preview(self, rect: QRectF):
        if self._grow_preview is None or self._grow_preview.scene() is None:
            pen = QPen(QColor("#2F5D5C"), 3, Qt.PenStyle.DashLine)
            self._grow_preview = self._scene.addRect(rect, pen)
            self._grow_preview.setZValue(10000)
        else:
            self._grow_preview.setRect(rect)

    def _clear_reparent_highlight(self):
        if self._grow_preview is not None:
            try:
                if self._grow_preview.scene() is not None:
                    self._scene.removeItem(self._grow_preview)
            except RuntimeError:
                pass  # C++ object already deleted (scene rebuild)
        self._grow_preview = None

    def _show_resize_foreshadow(self, frame: QRectF, content=None,
                                locked: bool = False):
        """Preview a resize/scale: target frame + content-occupied area."""
        if self._resize_foreshadow is None or self._resize_foreshadow.scene() is None:
            self._resize_foreshadow = ResizeForeshadow()
            self._scene.addItem(self._resize_foreshadow)
        self._resize_foreshadow.set_preview(frame, content, locked)

    def _clear_resize_foreshadow(self):
        if self._resize_foreshadow is not None:
            try:
                if self._resize_foreshadow.scene() is not None:
                    self._scene.removeItem(self._resize_foreshadow)
            except RuntimeError:
                pass  # C++ object already deleted (scene rebuild)
        self._resize_foreshadow = None

    # ── Box mode (vim-like style / dimension) ──

    def _clear_mode_badge(self, fade: bool = False):
        """Remove the floating mode badge (optionally fading it out first).

        Defensive against scene rebuilds: if the scene was reloaded (e.g.
        on file open) the badge's C++ object has already been deleted
        even though the Python reference survives, so ``removeItem``
        would raise. Suppress that case and just drop the references.

        ``fade`` detaches the live references immediately (so a follow-up
        ``_set_*_mode`` creates fresh items without interference) and eases the
        captured items out before removing them — used on genuine mode exit.
        """
        items = [self._mode_badge_bg, self._mode_badge]
        self._mode_badge_bg = None
        self._mode_badge = None
        items = [it for it in items if it is not None]
        if not items:
            return

        def _remove():
            for it in items:
                try:
                    self._scene.removeItem(it)
                except RuntimeError:
                    pass  # C++ object already deleted (scene rebuild)

        if not fade:
            _remove()
            return

        def _set_op(v):
            for it in items:
                try:
                    it.setOpacity(v)
                except RuntimeError:
                    pass
        try:
            start = items[0].opacity()
        except RuntimeError:
            return
        self._animate_fade(start, 0.0, _set_op, on_finished=_remove)

    def _fade_in_mode_badge(self):
        items = [it for it in (self._mode_badge_bg, self._mode_badge)
                 if it is not None]
        if not items:
            return
        for it in items:
            it.setOpacity(0.0)

        def _set_op(v):
            for it in items:
                try:
                    it.setOpacity(v)
                except RuntimeError:
                    pass
        self._animate_fade(0.0, 1.0, _set_op)
        # Stance-change 'pop' on entry — reads as a deliberate mode switch.
        self._animate_scale(items, 0.86, 1.0)

    def _set_box_mode(self, mode: str):
        self._box_mode = mode
        if not mode:
            self._clear_mode_badge(fade=True)
            return
        self._clear_mode_badge()
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
        self._fade_in_mode_badge()

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

    # ── Colour-grid picker (style mode -> c) ──

    _COLOR_GRID_COLS = 5
    # Note background plate options shown when the colour picker targets a
    # note: a beige plate (default) or none (text on the canvas).
    _NOTE_BG_OPTIONS = (("Plate", False), ("None", True))

    def _color_picker_boxes(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, BoxItem)]

    def _color_picker_notes(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, NoteItem)]

    def _open_color_picker(self):
        boxes = self._color_picker_boxes()
        if boxes:
            self._color_picker_mode = "box"
            self._color_picker_original = {it.box.id: it.box.color
                                           for it in boxes}
            values = [v for _, v in COLOR_PALETTE]
            cur = boxes[0].box.color
            self._color_picker_index = values.index(cur) if cur in values else 0
            self._color_picker_active = True
            self.viewport().update()
            return
        notes = self._color_picker_notes()
        if notes:
            self._color_picker_mode = "note-bg"
            self._color_picker_original = {it.note.id: it.note.flat
                                           for it in notes}
            self._color_picker_index = 1 if notes[0].note.flat else 0
            self._color_picker_active = True
            self.viewport().update()
            return
        self.toast("Select a box or note", kind="warn")

    def _apply_color_picker_live(self):
        """Preview the highlighted choice on the selection (no undo/dirty)."""
        if self._color_picker_mode == "note-bg":
            flat = self._NOTE_BG_OPTIONS[self._color_picker_index][1]
            for it in self._color_picker_notes():
                it.set_flat(flat)
            return
        value = COLOR_PALETTE[self._color_picker_index][1]
        for it in self._color_picker_boxes():
            it.set_color(value)

    def _color_picker_move(self, dcol: int, drow: int):
        if self._color_picker_mode == "note-bg":
            n = len(self._NOTE_BG_OPTIONS)
            idx = max(0, min(n - 1, self._color_picker_index + dcol))
            if idx != self._color_picker_index:
                self._color_picker_index = idx
                self._apply_color_picker_live()
            self.viewport().update()
            return
        cols = self._COLOR_GRID_COLS
        n = len(COLOR_PALETTE)
        rows = (n + cols - 1) // cols
        col = self._color_picker_index % cols
        row = self._color_picker_index // cols
        col = max(0, min(cols - 1, col + dcol))
        row = max(0, min(rows - 1, row + drow))
        idx = min(row * cols + col, n - 1)
        if idx != self._color_picker_index:
            self._color_picker_index = idx
            self._apply_color_picker_live()
        self.viewport().update()

    def _handle_color_picker_key(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_color_picker()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_color_picker()
        elif key == Qt.Key.Key_H:
            self._color_picker_move(-1, 0)
        elif key == Qt.Key.Key_L:
            self._color_picker_move(1, 0)
        elif key == Qt.Key.Key_K:
            self._color_picker_move(0, -1)
        elif key == Qt.Key.Key_J:
            self._color_picker_move(0, 1)

    def _commit_color_picker(self):
        if self._color_picker_mode == "note-bg":
            notes = self._color_picker_notes()
            flat = self._NOTE_BG_OPTIONS[self._color_picker_index][1]
            for it in notes:
                it.set_flat(self._color_picker_original.get(it.note.id,
                                                            it.note.flat))
            self._push_undo()
            for it in notes:
                it.set_flat(flat)
            self.mark_dirty()
            self._close_color_picker()
            return
        boxes = self._color_picker_boxes()
        value = COLOR_PALETTE[self._color_picker_index][1]
        # Restore the pre-picker colours so the undo snapshot captures the
        # original state, then apply the chosen colour as one undoable step.
        for it in boxes:
            it.set_color(self._color_picker_original.get(it.box.id, it.box.color))
        self._push_undo()
        for it in boxes:
            it.set_color(value)
        self._last_box_color = value
        self.mark_dirty()
        self._close_color_picker()

    def _cancel_color_picker(self):
        if self._color_picker_mode == "note-bg":
            for it in self._color_picker_notes():
                if it.note.id in self._color_picker_original:
                    it.set_flat(self._color_picker_original[it.note.id])
            self._close_color_picker()
            return
        for it in self._color_picker_boxes():
            if it.box.id in self._color_picker_original:
                it.set_color(self._color_picker_original[it.box.id])
        self._close_color_picker()

    def _close_color_picker(self):
        self._color_picker_active = False
        self._color_picker_original = {}
        self.viewport().update()

    def _draw_color_picker(self, painter: QPainter):
        """A small palette grid anchored beside the selection, with the live
        choice ringed in cyan. Static (no animation), viewport coords."""
        if not self._color_picker_active:
            return
        if self._color_picker_mode == "note-bg":
            self._draw_note_bg_picker(painter)
            return
        boxes = self._color_picker_boxes()
        if not boxes:
            return
        scene_rect = boxes[0].sceneBoundingRect()
        for it in boxes[1:]:
            scene_rect = scene_rect.united(it.sceneBoundingRect())
        anchor = self.mapFromScene(scene_rect).boundingRect()

        cols = self._COLOR_GRID_COLS
        rows = (len(COLOR_PALETTE) + cols - 1) // cols
        sw, gap, pad, label_h = 26, 6, 10, 18
        grid_w = cols * sw + (cols - 1) * gap
        grid_h = rows * sw + (rows - 1) * gap
        panel_w = grid_w + pad * 2
        panel_h = grid_h + pad * 2 + label_h
        margin = 14
        vw, vh = self.viewport().width(), self.viewport().height()
        px = anchor.right() + margin
        if px + panel_w > vw - 4:
            px = anchor.left() - margin - panel_w   # flip to the other side
        px = max(4, min(px, vw - panel_w - 4))
        py = anchor.center().y() - panel_h / 2
        py = max(4, min(py, vh - panel_h - 4))

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor("#2F3437")
        bg.setAlphaF(0.96)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(px, py, panel_w, panel_h), 8, 8)

        gx0, gy0 = px + pad, py + pad
        cyan = QColor(0, 209, 224)
        for i, (_name, value) in enumerate(COLOR_PALETTE):
            sx = gx0 + (i % cols) * (sw + gap)
            sy = gy0 + (i // cols) * (sw + gap)
            cell = QRectF(sx, sy, sw, sw)
            hexv = _resolve_color(value)
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
            painter.setBrush(QBrush(QColor(hexv) if hexv else QColor("#E8E4DD")))
            painter.drawRoundedRect(cell, 4, 4)
            if not hexv:
                # "Default" / auto swatch: a diagonal slash marks "no colour".
                painter.setPen(QPen(QColor(150, 60, 60), 1.5))
                painter.drawLine(QPointF(cell.left() + 4, cell.bottom() - 4),
                                 QPointF(cell.right() - 4, cell.top() + 4))
            if i == self._color_picker_index:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(cyan, 2))
                painter.drawRoundedRect(cell.adjusted(-2, -2, 2, 2), 5, 5)

        painter.setPen(QPen(QColor(235, 235, 235)))
        painter.setFont(QFont(FONT_FAMILY, 9))
        painter.drawText(QRectF(px, gy0 + grid_h + 4, panel_w, label_h),
                         Qt.AlignmentFlag.AlignCenter,
                         COLOR_PALETTE[self._color_picker_index][0])
        painter.restore()

    def _draw_note_bg_picker(self, painter: QPainter):
        """Two-option background chooser for a note selection — beige plate or
        none (text on the canvas), the live choice ringed in cyan."""
        notes = self._color_picker_notes()
        if not notes:
            return
        scene_rect = notes[0].sceneBoundingRect()
        for it in notes[1:]:
            scene_rect = scene_rect.united(it.sceneBoundingRect())
        anchor = self.mapFromScene(scene_rect).boundingRect()

        opts = self._NOTE_BG_OPTIONS
        sw, gap, pad, label_h = 30, 8, 10, 18
        grid_w = len(opts) * sw + (len(opts) - 1) * gap
        panel_w = grid_w + pad * 2
        panel_h = sw + pad * 2 + label_h
        margin = 14
        vw, vh = self.viewport().width(), self.viewport().height()
        px = anchor.right() + margin
        if px + panel_w > vw - 4:
            px = anchor.left() - margin - panel_w
        px = max(4, min(px, vw - panel_w - 4))
        py = anchor.center().y() - panel_h / 2
        py = max(4, min(py, vh - panel_h - 4))

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor("#2F3437")
        bg.setAlphaF(0.96)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(px, py, panel_w, panel_h), 8, 8)

        gx0, gy0 = px + pad, py + pad
        cyan = QColor(0, 209, 224)
        for i, (_name, flat) in enumerate(opts):
            cell = QRectF(gx0 + i * (sw + gap), gy0, sw, sw)
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
            if flat:
                # "None": canvas-coloured swatch with a diagonal slash.
                painter.setBrush(QBrush(QColor("#E8E4DD")))
                painter.drawRoundedRect(cell, 4, 4)
                painter.setPen(QPen(QColor(150, 60, 60), 1.5))
                painter.drawLine(QPointF(cell.left() + 5, cell.bottom() - 5),
                                 QPointF(cell.right() - 5, cell.top() + 5))
            else:
                # "Plate": the beige note plate.
                painter.setBrush(QBrush(QColor("#F2F0EB")))
                painter.drawRoundedRect(cell, 4, 4)
            if i == self._color_picker_index:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(cyan, 2))
                painter.drawRoundedRect(cell.adjusted(-2, -2, 2, 2), 5, 5)

        painter.setPen(QPen(QColor(235, 235, 235)))
        painter.setFont(QFont(FONT_FAMILY, 9))
        painter.drawText(QRectF(px, gy0 + sw + 4, panel_w, label_h),
                         Qt.AlignmentFlag.AlignCenter,
                         opts[self._color_picker_index][0])
        painter.restore()

    # ── Icon-grid picker (style mode -> i), boxes and notes ──

    _ICON_GRID_COLS = 6
    _ICON_ENTRIES = [""] + ICON_NAMES   # "" = clear/none

    def _icon_picker_targets(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, (BoxItem, NoteItem))]

    @staticmethod
    def _el_icon(item) -> str:
        return item.box.icon if isinstance(item, BoxItem) else item.note.icon

    @staticmethod
    def _el_placement(item) -> str:
        return (item.box.icon_placement if isinstance(item, BoxItem)
                else item.note.icon_placement)

    @staticmethod
    def _el_id(item) -> str:
        return item.box.id if isinstance(item, BoxItem) else item.note.id

    def _open_icon_picker(self):
        targets = self._icon_picker_targets()
        if not targets:
            self.toast("Select a box or note to add an icon", kind="warn")
            return
        self._icon_picker_original = {
            self._el_id(it): (self._el_icon(it), self._el_placement(it))
            for it in targets}
        cur = self._el_icon(targets[0])
        self._icon_picker_index = (self._ICON_ENTRIES.index(cur)
                                   if cur in self._ICON_ENTRIES else 0)
        self._icon_picker_placement = self._el_placement(targets[0])
        self._icon_picker_active = True
        self.viewport().update()

    def _apply_icon_picker_live(self):
        name = self._ICON_ENTRIES[self._icon_picker_index]
        for it in self._icon_picker_targets():
            it.set_icon(name, self._icon_picker_placement)

    def _icon_picker_move(self, dcol: int, drow: int):
        cols = self._ICON_GRID_COLS
        n = len(self._ICON_ENTRIES)
        rows = (n + cols - 1) // cols
        col = self._icon_picker_index % cols
        row = self._icon_picker_index // cols
        col = max(0, min(cols - 1, col + dcol))
        row = max(0, min(rows - 1, row + drow))
        idx = min(row * cols + col, n - 1)
        if idx != self._icon_picker_index:
            self._icon_picker_index = idx
            self._apply_icon_picker_live()
        self.viewport().update()

    def _toggle_icon_placement(self):
        # fill ("") <-> lead; live-preview the change.
        self._icon_picker_placement = (
            "lead" if self._icon_picker_placement == "" else "")
        self._apply_icon_picker_live()
        self.viewport().update()

    def _handle_icon_picker_key(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_icon_picker()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_icon_picker()
        elif key == Qt.Key.Key_Tab:
            self._toggle_icon_placement()
        elif key == Qt.Key.Key_H:
            self._icon_picker_move(-1, 0)
        elif key == Qt.Key.Key_L:
            self._icon_picker_move(1, 0)
        elif key == Qt.Key.Key_K:
            self._icon_picker_move(0, -1)
        elif key == Qt.Key.Key_J:
            self._icon_picker_move(0, 1)

    def _commit_icon_picker(self):
        targets = self._icon_picker_targets()
        name = self._ICON_ENTRIES[self._icon_picker_index]
        place = self._icon_picker_placement
        for it in targets:
            on, op = self._icon_picker_original.get(self._el_id(it), ("", ""))
            it.set_icon(on, op)
        self._push_undo()
        for it in targets:
            it.set_icon(name, place)
        self.mark_dirty()
        self._close_icon_picker()

    def _cancel_icon_picker(self):
        for it in self._icon_picker_targets():
            tid = self._el_id(it)
            if tid in self._icon_picker_original:
                it.set_icon(*self._icon_picker_original[tid])
        self._close_icon_picker()

    def _close_icon_picker(self):
        self._icon_picker_active = False
        self._icon_picker_original = {}
        self.viewport().update()

    def _draw_icon_picker(self, painter: QPainter):
        """An icon grid anchored beside the selection, with the live choice
        ringed in cyan. Static (no animation), viewport coords."""
        if not self._icon_picker_active:
            return
        targets = self._icon_picker_targets()
        if not targets:
            return
        scene_rect = targets[0].sceneBoundingRect()
        for it in targets[1:]:
            scene_rect = scene_rect.united(it.sceneBoundingRect())
        anchor = self.mapFromScene(scene_rect).boundingRect()

        cols = self._ICON_GRID_COLS
        n = len(self._ICON_ENTRIES)
        rows = (n + cols - 1) // cols
        sw, gap, pad, label_h = 30, 6, 10, 18
        grid_w = cols * sw + (cols - 1) * gap
        grid_h = rows * sw + (rows - 1) * gap
        panel_w = grid_w + pad * 2
        panel_h = grid_h + pad * 2 + label_h
        margin = 14
        vw, vh = self.viewport().width(), self.viewport().height()
        px = anchor.right() + margin
        if px + panel_w > vw - 4:
            px = anchor.left() - margin - panel_w
        px = max(4, min(px, vw - panel_w - 4))
        py = anchor.center().y() - panel_h / 2
        py = max(4, min(py, vh - panel_h - 4))

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor("#2F3437")
        bg.setAlphaF(0.96)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(px, py, panel_w, panel_h), 8, 8)

        gx0, gy0 = px + pad, py + pad
        cyan = QColor(0, 209, 224)
        ink = QColor(220, 220, 216)
        dpr = self.devicePixelRatioF() or 1.0
        for i, name in enumerate(self._ICON_ENTRIES):
            sx = gx0 + (i % cols) * (sw + gap)
            sy = gy0 + (i // cols) * (sw + gap)
            cell = QRectF(sx, sy, sw, sw)
            if name:
                pm = icon_pixmap(name, ink, sw - 8, dpr)
                if pm is not None:
                    painter.drawPixmap(QPointF(sx + 4, sy + 4), pm)
            else:
                # "none" cell: a slash marks "no icon".
                painter.setPen(QPen(QColor(150, 60, 60), 1.5))
                painter.drawLine(QPointF(sx + 7, sy + sw - 7),
                                 QPointF(sx + sw - 7, sy + 7))
            if i == self._icon_picker_index:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(cyan, 2))
                painter.drawRoundedRect(cell.adjusted(-1, -1, 1, 1), 5, 5)

        painter.setPen(QPen(QColor(235, 235, 235)))
        painter.setFont(QFont(FONT_FAMILY, 9))
        name = self._ICON_ENTRIES[self._icon_picker_index]
        if name:
            place = self._icon_picker_placement or "fill"
            cur = f"{name} · {place}   ⇥ placement"
        else:
            cur = "none"
        painter.drawText(QRectF(px, gy0 + grid_h + 4, panel_w, label_h),
                         Qt.AlignmentFlag.AlignCenter, cur)
        painter.restore()

    # ── Type grid (style mode -> s): size rows x emphasis columns ──

    _TYPE_SIZES = ["small", "", "large", "xlarge", "xxlarge", "xxxlarge", "4xl"]
    _TYPE_SIZE_LABELS = {"small": "S", "": "M", "large": "L",
                         "xlarge": "XL", "xxlarge": "2XL", "xxxlarge": "3XL",
                         "4xl": "4XL"}
    # Map alias tokens to the grid's canonical size strings (so opening the
    # grid on a hand-written ``~2xl`` / ``~xxxxlarge`` lands on the right row).
    _TYPE_SIZE_NORMALIZE = {"2xl": "xxlarge", "3xl": "xxxlarge",
                            "xxxxlarge": "4xl"}
    _TYPE_EMPH = ["", "bold", "italic", "bold italic"]
    _TYPE_EMPH_LABELS = ["regular", "bold", "italic", "bold italic"]

    def _type_picker_targets(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, (BoxItem, NoteItem))]

    @staticmethod
    def _el_textsize(item) -> str:
        return (item.box.textsize if isinstance(item, BoxItem)
                else item.note.textsize)

    @staticmethod
    def _el_emphasis(item) -> str:
        return (item.box.emphasis if isinstance(item, BoxItem)
                else item.note.emphasis)

    def _open_type_picker(self):
        targets = self._type_picker_targets()
        if not targets:
            self.toast("Select a box or note", kind="warn")
            return
        self._type_picker_original = {
            self._el_id(it): (
                self._el_textsize(it), self._el_emphasis(it),
                it.note.style if isinstance(it, NoteItem) else None)
            for it in targets}
        size = self._el_textsize(targets[0])
        size = self._TYPE_SIZE_NORMALIZE.get(size, size)
        self._type_picker_size_idx = (self._TYPE_SIZES.index(size)
                                      if size in self._TYPE_SIZES else 1)
        # Emphasis splits into the grid's bold/italic axis plus the
        # independent display toggles (outline / shadow, notes only).
        toks = self._el_emphasis(targets[0]).split()
        base = emphasis_from_flags({t for t in toks if t in ("bold", "italic")})
        self._type_picker_emph_idx = (self._TYPE_EMPH.index(base)
                                      if base in self._TYPE_EMPH else 0)
        notes = [it for it in targets if isinstance(it, NoteItem)]
        self._type_picker_font = notes[0].note.style if notes else ""
        first_emph = notes[0].note.emphasis if notes else ""
        self._type_picker_outline = "outline" in first_emph
        self._type_picker_shadow = "shadow" in first_emph
        self._type_picker_active = True
        self.viewport().update()

    def _type_picker_has_note(self) -> bool:
        return any(isinstance(it, NoteItem)
                   for it in self._type_picker_targets())

    def _compose_note_emphasis(self, base: str) -> str:
        """Combine the grid's bold/italic ``base`` with the note-only display
        toggles (outline / shadow), in canonical order."""
        flags = set(base.split())
        if self._type_picker_outline:
            flags.add("outline")
        if self._type_picker_shadow:
            flags.add("shadow")
        return emphasis_from_flags(flags)

    def _apply_type_picker_live(self):
        size = self._TYPE_SIZES[self._type_picker_size_idx]
        emph = self._TYPE_EMPH[self._type_picker_emph_idx]
        for it in self._type_picker_targets():
            it.set_textsize(size)
            if isinstance(it, NoteItem):
                it.set_emphasis(self._compose_note_emphasis(emph))
                it.set_text_mono(self._type_picker_font == "mono")
            else:
                it.set_emphasis(emph)

    def _type_picker_move(self, dcol: int, drow: int):
        self._type_picker_emph_idx = max(
            0, min(len(self._TYPE_EMPH) - 1, self._type_picker_emph_idx + dcol))
        self._type_picker_size_idx = max(
            0, min(len(self._TYPE_SIZES) - 1, self._type_picker_size_idx + drow))
        self._apply_type_picker_live()
        self.viewport().update()

    def _toggle_type_font(self):
        # hand ("") <-> mono; only meaningful for notes.
        self._type_picker_font = "mono" if self._type_picker_font == "" else ""
        self._apply_type_picker_live()
        self.viewport().update()

    def _toggle_type_outline(self):
        # Hollow display letters — notes only, like the font toggle.
        if not self._type_picker_has_note():
            return
        self._type_picker_outline = not self._type_picker_outline
        self._apply_type_picker_live()
        self.viewport().update()

    def _toggle_type_shadow(self):
        # Drop-shadow depth — notes only.
        if not self._type_picker_has_note():
            return
        self._type_picker_shadow = not self._type_picker_shadow
        self._apply_type_picker_live()
        self.viewport().update()

    def _handle_type_picker_key(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_type_picker()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_type_picker()
        elif key == Qt.Key.Key_Tab:
            self._toggle_type_font()
        elif key == Qt.Key.Key_O:
            self._toggle_type_outline()
        elif key == Qt.Key.Key_S:
            self._toggle_type_shadow()
        elif key == Qt.Key.Key_H:
            self._type_picker_move(-1, 0)
        elif key == Qt.Key.Key_L:
            self._type_picker_move(1, 0)
        elif key == Qt.Key.Key_K:
            self._type_picker_move(0, -1)
        elif key == Qt.Key.Key_J:
            self._type_picker_move(0, 1)

    def _restore_type_original(self, it):
        orig = self._type_picker_original.get(self._el_id(it))
        if orig is None:
            return
        it.set_textsize(orig[0])
        it.set_emphasis(orig[1])
        if isinstance(it, NoteItem) and orig[2] is not None:
            it.set_text_mono(orig[2] == "mono")

    def _commit_type_picker(self):
        targets = self._type_picker_targets()
        size = self._TYPE_SIZES[self._type_picker_size_idx]
        emph = self._TYPE_EMPH[self._type_picker_emph_idx]
        for it in targets:
            self._restore_type_original(it)
        self._push_undo()
        for it in targets:
            it.set_textsize(size)
            if isinstance(it, NoteItem):
                it.set_emphasis(self._compose_note_emphasis(emph))
                it.set_text_mono(self._type_picker_font == "mono")
            else:
                it.set_emphasis(emph)
        self.mark_dirty()
        self._close_type_picker()

    def _cancel_type_picker(self):
        for it in self._type_picker_targets():
            self._restore_type_original(it)
        self._close_type_picker()

    def _close_type_picker(self):
        self._type_picker_active = False
        self._type_picker_original = {}
        self.viewport().update()

    def _draw_type_picker(self, painter: QPainter):
        """Size (rows) x emphasis (columns) grid; each cell previews 'Ag' at
        that size (capped) and weight. Live preview on the element."""
        if not self._type_picker_active:
            return
        targets = self._type_picker_targets()
        if not targets:
            return
        scene_rect = targets[0].sceneBoundingRect()
        for it in targets[1:]:
            scene_rect = scene_rect.united(it.sceneBoundingRect())
        anchor = self.mapFromScene(scene_rect).boundingRect()

        has_note = self._type_picker_has_note()
        rows, cols = len(self._TYPE_SIZES), len(self._TYPE_EMPH)
        cell_w, cell_h, rowlab_w, pad, label_h = 52, 38, 30, 10, 18
        grid_w = rowlab_w + cols * cell_w
        grid_h = rows * cell_h
        panel_w = grid_w + pad * 2
        # Notes get a second line for the outline / shadow / font toggle hints.
        panel_h = grid_h + pad * 2 + label_h + (label_h if has_note else 0)
        margin = 14
        vw, vh = self.viewport().width(), self.viewport().height()
        px = anchor.right() + margin
        if px + panel_w > vw - 4:
            px = anchor.left() - margin - panel_w
        px = max(4, min(px, vw - panel_w - 4))
        py = anchor.center().y() - panel_h / 2
        py = max(4, min(py, vh - panel_h - 4))

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        bg = QColor("#2F3437")
        bg.setAlphaF(0.96)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(px, py, panel_w, panel_h), 8, 8)

        gx0, gy0 = px + pad, py + pad
        cyan = QColor(0, 209, 224)
        ink = QColor(225, 225, 221)
        for r, size in enumerate(self._TYPE_SIZES):
            cy = gy0 + r * cell_h
            painter.setPen(QPen(QColor(150, 150, 146)))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(QRectF(gx0, cy, rowlab_w - 4, cell_h),
                             Qt.AlignmentFlag.AlignVCenter
                             | Qt.AlignmentFlag.AlignRight,
                             self._TYPE_SIZE_LABELS[size])
            prev_px = min(resolve_textsize_px(size, ""), 24)
            for c, emph in enumerate(self._TYPE_EMPH):
                cx = gx0 + rowlab_w + c * cell_w
                cell = QRectF(cx, cy, cell_w, cell_h)
                f = QFont(FONT_FAMILY, prev_px)
                f.setBold("bold" in emph)
                f.setItalic("italic" in emph)
                painter.setFont(f)
                painter.setPen(QPen(ink))
                painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, "Ag")
                if (r == self._type_picker_size_idx
                        and c == self._type_picker_emph_idx):
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(cyan, 2))
                    painter.drawRoundedRect(cell.adjusted(1, 1, -1, -1), 5, 5)

        painter.setPen(QPen(QColor(235, 235, 235)))
        painter.setFont(QFont(FONT_FAMILY, 9))
        sl = self._TYPE_SIZE_LABELS[self._TYPE_SIZES[self._type_picker_size_idx]]
        el = self._TYPE_EMPH_LABELS[self._type_picker_emph_idx]
        status = f"{sl} · {el}"
        status_y = gy0 + grid_h + 4
        if has_note:
            font = "mono" if self._type_picker_font == "mono" else "hand"
            status += f" · {font}"
            for name, on in (("outline", self._type_picker_outline),
                             ("shadow", self._type_picker_shadow)):
                if on:
                    status += f" · {name}"
        painter.drawText(QRectF(px, status_y, panel_w, label_h),
                         Qt.AlignmentFlag.AlignCenter, status)
        if has_note:
            painter.setPen(QPen(QColor(150, 150, 146)))
            painter.setFont(QFont(FONT_FAMILY, 8))
            painter.drawText(QRectF(px, status_y + label_h, panel_w, label_h),
                             Qt.AlignmentFlag.AlignCenter,
                             "⇥ font   o outline   s shadow")
        painter.restore()

    # ── Arrow mode (vim-like style) ──

    def _arrow_label_midpoint(self) -> QPointF | None:
        """Return scene midpoint of the selected arrow's line.

        Resolves any endpoint type (box, note, image) via its graphics item, so
        the style-mode badge appears on note/image connectors too.
        """
        arrow = self._selected_arrow
        if not arrow or not self._board:
            return None
        fi = (self._box_items.get(arrow.from_id)
              or self._note_items.get(arrow.from_id)
              or self._image_items.get(arrow.from_id))
        ti = (self._box_items.get(arrow.to_id)
              or self._note_items.get(arrow.to_id)
              or self._image_items.get(arrow.to_id))
        if fi is None or ti is None:
            return None
        sc = fi.sceneBoundingRect().center()
        ec = ti.sceneBoundingRect().center()
        return QPointF((sc.x() + ec.x()) / 2, (sc.y() + ec.y()) / 2)

    def _set_arrow_mode(self, mode: str):
        self._arrow_mode = mode
        if not mode:
            self._clear_mode_badge(fade=True)
            return
        self._clear_mode_badge()
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
        self._fade_in_mode_badge()

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

    def _grafli_dir(self) -> Path | None:
        """Return the directory of the current .grafli file, or None."""
        window = self.window()
        if hasattr(window, '_file_path') and window._file_path:
            return Path(window._file_path).parent
        return None

    def _url_dialog(self, current: str) -> tuple[str, bool]:
        """Show a URL/path input dialog with filesystem completion."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Set URL or Path")
        dlg.setMinimumWidth(480)

        layout = QVBoxLayout(dlg)
        label = QLabel("URL or local path (relative paths resolve from .grafli location):")
        layout.addWidget(label)

        line = QLineEdit(dlg)
        line.setText(current)
        layout.addWidget(line)

        grafli_dir = self._grafli_dir()
        list_model = QStringListModel(dlg)
        completer = QCompleter(list_model, dlg)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        line.setCompleter(completer)

        def _update_completions(text: str):
            stripped = text.strip()
            if not stripped or "/" not in stripped:
                return
            # Split on last slash to get directory prefix and partial name
            last_slash = stripped.rfind("/")
            dir_text = stripped[:last_slash + 1]
            # Resolve the directory to an absolute path
            dir_path = Path(dir_text).expanduser()
            if not dir_path.is_absolute() and grafli_dir:
                abs_dir = (grafli_dir / dir_path).resolve()
            else:
                abs_dir = dir_path.resolve()
            if not abs_dir.is_dir():
                return
            # Build completions preserving the user's typed prefix
            entries = []
            try:
                for entry in sorted(abs_dir.iterdir()):
                    if entry.name.startswith('.'):
                        continue
                    suffix = "/" if entry.is_dir() else ""
                    entries.append(f"{dir_text}{entry.name}{suffix}")
            except PermissionError:
                return
            list_model.setStringList(entries)

        line.textChanged.connect(_update_completions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        line.setFocus()
        line.selectAll()

        ok = dlg.exec() == QDialog.DialogCode.Accepted
        return line.text().strip(), ok

    @staticmethod
    def _attach_display(el) -> str:
        """The editable text form of an element's attachment (dialog prefill)."""
        if el.attach_kind in ("doc", "graph"):
            return (f"{el.attach_kind}:{el.url}" if el.url
                    else el.attach_kind)
        return el.url

    def _assign_attachment(self, item, el, raw: str):
        """Apply a typed-or-plain attachment string from the url dialog.

        ``doc:<name>`` / ``graph:<name>`` / bare ``doc`` set vault kinds;
        anything else is a link. Pointing a note at an existing doc adopts
        the file's body (the vault is authoritative); pointing it at a new
        name keeps the current text as the seed — the next save writes it.
        """
        from grafli.format import doc_name, split_attach
        from grafli.resources import doc_path
        raw = raw.strip()
        kind, value = split_attach(raw) if raw else ("", "")
        if kind == "" and value:
            kind = "link"
        self._push_undo()
        el.attach_kind, el.url = kind, value
        if kind == "doc" and isinstance(item, NoteItem):
            window = self.window()
            grafli_path = getattr(window, "_file_path", None)
            if grafli_path:
                p = doc_path(Path(grafli_path), doc_name(el))
                if p.exists():
                    el.text = p.read_text(encoding="utf-8")
        item._update_url_indicator()
        item.update()
        self.mark_dirty()

    def _set_url(self):
        """Set/edit the attachment on the first selected box, note, or image."""
        for item in self._scene.selectedItems():
            el = (item.box if isinstance(item, BoxItem)
                  else item.note if isinstance(item, NoteItem)
                  else item.image if isinstance(item, ImageItem) else None)
            if el is None:
                continue
            raw, ok = self._url_dialog(self._attach_display(el))
            if ok:
                self._assign_attachment(item, el, raw)
            return

    # ── Resource handling ────────────────────────────────────────

    @staticmethod
    def _has_attachment(el) -> bool:
        # A doc-bodied note may carry the bare ``&doc`` form (empty url).
        return bool(el.url) or el.attach_kind == "doc"

    def _open_attachment(self, el):
        """Open an element's attachment by its kind: a vault doc in the zen
        editor, a vault sub-board in the app, anything else (links, legacy
        untyped urls) through the url path."""
        window = self.window()
        grafli_path = getattr(window, "_file_path", None)
        if el.attach_kind == "doc" and grafli_path:
            from grafli.format import doc_name
            from grafli.resources import doc_path
            self._open_md_zen(doc_path(Path(grafli_path), doc_name(el)))
            return
        if el.attach_kind == "graph" and grafli_path:
            from grafli.resources import graph_path
            if hasattr(window, "_open_file"):
                window._open_file(graph_path(Path(grafli_path), el.url))
            return
        if el.url:
            self._open_url_string(el.url)

    def _open_resource(self):
        """Open resource for the selected element, or show picker if none."""
        if self._selected_arrow:
            arrow = self._selected_arrow
            if self._has_attachment(arrow):
                self._open_attachment(arrow)
            else:
                self._open_resource_picker_for_arrow(arrow)
            return
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                if self._has_attachment(item.box):
                    self._open_attachment(item.box)
                else:
                    self._open_resource_picker(item, item.box.id)
                return
            if isinstance(item, NoteItem):
                if self._has_attachment(item.note):
                    self._open_attachment(item.note)
                else:
                    self._open_resource_picker(item, item.note.id)
                return
            if isinstance(item, ImageItem):
                if self._has_attachment(item.image):
                    self._open_attachment(item.image)
                else:
                    self._open_resource_picker(item, item.image.id)
                return

    def _open_code_ref(self, ref: str):
        """Open an ``@path[:line]`` reference from a code-mode note.

        Resolution order: configured editor command from QSettings,
        then auto-detected ``code``/``cursor``/``subl``, finally OS open.
        Relative paths are resolved against the .grafli file's directory.
        """
        target = ref[1:] if ref.startswith("@") else ref
        line_no: int | None = None
        m = _re.match(r"^(.+):(\d+)$", target)
        if m:
            target = m.group(1)
            line_no = int(m.group(2))

        path = Path(target).expanduser()
        if not path.is_absolute():
            window = self.window()
            if hasattr(window, "_file_path") and window._file_path:
                path = Path(window._file_path).parent / path
        path = path.resolve()

        cmd_template = QSettings("Grafli", "Grafli").value(
            "editor/command", "", type=str,
        ) or ""
        if not cmd_template:
            for candidate in ("code", "cursor", "subl"):
                if shutil.which(candidate):
                    cmd_template = (
                        f"{candidate} -g {{path}}:{{line}}"
                        if candidate != "subl"
                        else "subl {path}:{line}"
                    )
                    break

        if cmd_template:
            try:
                rendered = cmd_template.format(
                    path=str(path),
                    line=line_no if line_no is not None else 1,
                )
                subprocess.Popen(shlex.split(rendered), start_new_session=True)
                return
            except (OSError, ValueError, KeyError):
                pass

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_url_string(self, url_str: str):
        """Open a URL string, handling .md and .grafli files specially."""
        resolved = self._resolve_url(url_str)
        if resolved.isLocalFile():
            local = resolved.toLocalFile()
            if local.endswith(".md"):
                self._open_md_zen(
                    Path(local), anchor=resolved.fragment() or "",
                )
                return
            if local.endswith(".grafli"):
                window = self.window()
                if hasattr(window, '_open_file'):
                    window._open_file(Path(local))
                return
        QDesktopServices.openUrl(resolved)

    def _open_resource_picker(self, item, element_id: str):
        """Show the inline resource picker near the given item."""
        window = self.window()
        if not hasattr(window, '_file_path') or not window._file_path:
            return
        picker = _ResourcePicker(self.viewport())
        item_rect = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
        pw = picker.sizeHint().width()
        ph = picker.sizeHint().height()
        px = int(item_rect.center().x()) - pw // 2
        py = int(item_rect.top()) - ph - 8
        if py < 0:
            py = int(item_rect.bottom()) + 8
        vp = self.viewport().rect()
        px = max(0, min(px, vp.width() - pw))
        picker.move(self.viewport().mapToGlobal(QPoint(px, py)))
        picker.resource_selected.connect(
            lambda kind: self._create_resource(item, element_id, kind)
        )
        picker.show()

    def _open_resource_picker_for_arrow(self, arrow):
        """Show inline resource picker for an arrow."""
        window = self.window()
        if not hasattr(window, '_file_path') or not window._file_path:
            return
        aid = f"{arrow.from_id}--{arrow.to_id}"
        # Position near arrow label or midpoint
        picker = _ResourcePicker(self.viewport())
        center = self.viewport().rect().center()
        for it in self._arrow_items:
            if isinstance(it, LabelItem) and it.data(0) is arrow:
                center = self.mapFromScene(it.pos()).toPoint()
                break
        pw = picker.sizeHint().width()
        ph = picker.sizeHint().height()
        px = center.x() - pw // 2
        py = center.y() - ph - 8
        vp = self.viewport().rect()
        px = max(0, min(px, vp.width() - pw))
        py = max(0, py)
        picker.move(self.viewport().mapToGlobal(QPoint(int(px), int(py))))
        picker.resource_selected.connect(
            lambda kind: self._create_arrow_resource(arrow, aid, kind)
        )
        picker.show()

    def _create_resource(self, item, element_id: str, kind: str):
        """Create a vault attachment for a node and set its typed reference."""
        from grafli.md_note import is_md_note, md_body
        from grafli.resources import ensure_res_dir
        window = self.window()
        grafli_path = window._file_path
        rd = ensure_res_dir(grafli_path)

        if kind == "markdown":
            md_path = rd / f"{element_id}.md"
            if isinstance(item, NoteItem):
                # On a note, "attach markdown" means: become doc-bodied — the
                # doc IS the body, seeded with the note's current text.
                note = item.note
                if not md_path.exists():
                    body = md_body(note.text) if is_md_note(note.text) \
                        else note.text
                    md_path.write_text(body, encoding="utf-8")
                self._push_undo()
                note.text = md_path.read_text(encoding="utf-8")
                note.attach_kind, note.url = "doc", ""
                item._update_url_indicator()
                item.update()
                self.mark_dirty()
            else:
                if not md_path.exists():
                    label = self._element_label(item)
                    md_path.write_text(f"# {label}\n\n", encoding="utf-8")
                self._set_element_attachment(item, "doc", element_id)
            self._open_md_zen(md_path)
        elif kind == "grafli":
            sub_path = rd / f"{element_id}.grafli"
            if not sub_path.exists():
                label = self._element_label(item)
                sub_path.write_text(
                    f"#!grafli v1\n# {label}\n", encoding="utf-8",
                )
            self._set_element_attachment(item, "graph", element_id)
            window._open_file(sub_path)
        elif kind == "file":
            self._set_url()

    def _create_arrow_resource(self, arrow, aid: str, kind: str):
        """Create a vault attachment for an arrow and set its typed reference."""
        from grafli.resources import ensure_res_dir
        window = self.window()
        grafli_path = window._file_path
        rd = ensure_res_dir(grafli_path)

        if kind == "markdown":
            md_path = rd / f"{aid}.md"
            if not md_path.exists():
                title = arrow.label or f"{arrow.from_id} \u2192 {arrow.to_id}"
                md_path.write_text(f"# {title}\n\n", encoding="utf-8")
            self._push_undo()
            arrow.attach_kind, arrow.url = "doc", aid
            self._redraw_arrows()
            self.mark_dirty()
            self._open_md_zen(md_path)
        elif kind == "grafli":
            sub_path = rd / f"{aid}.grafli"
            if not sub_path.exists():
                title = arrow.label or f"{arrow.from_id} \u2192 {arrow.to_id}"
                sub_path.write_text(
                    f"#!grafli v1\n# {title}\n", encoding="utf-8",
                )
            self._push_undo()
            arrow.attach_kind, arrow.url = "graph", aid
            self._redraw_arrows()
            self.mark_dirty()
            window._open_file(sub_path)
        elif kind == "file":
            self._set_url()

    def _element_label(self, item) -> str:
        """Extract a label string from a graphics item."""
        if isinstance(item, BoxItem):
            return item.box.label.replace("\n", " ")
        if isinstance(item, NoteItem):
            return item.note.text.replace("\n", " ")[:40]
        if isinstance(item, ImageItem):
            return item.image.id
        return ""

    def _set_element_attachment(self, item, kind: str, value: str):
        """Set a typed attachment on a graphics item, push undo, refresh."""
        el = (item.box if isinstance(item, BoxItem)
              else item.note if isinstance(item, NoteItem)
              else item.image if isinstance(item, ImageItem) else None)
        if el is None:
            return
        self._push_undo()
        el.attach_kind, el.url = kind, value
        item._update_url_indicator()
        item.update()
        self.mark_dirty()

    def _quick_edit_markdown(self):
        """Quick-create/open markdown resource for the selected element."""
        if self._zen_editor:
            return

        # A note is its own text — edit it in the zen editor in memory.
        # This works even on an unsaved diagram (no resource file needed),
        # so it runs before the grafli-file guard below.
        if not self._selected_arrow:
            for item in self._scene.selectedItems():
                if isinstance(item, NoteItem):
                    self._zen_edit_note(item)
                    return

        window = self.window()
        if not hasattr(window, '_file_path') or not window._file_path:
            return
        grafli_path = window._file_path

        if self._selected_arrow:
            arrow = self._selected_arrow
            aid = f"{arrow.from_id}--{arrow.to_id}"
            if arrow.url and arrow.url.endswith(".md"):
                resolved = self._resolve_url(arrow.url)
                self._open_md_zen(Path(resolved.toLocalFile()))
                return
            from grafli.resources import ensure_res_dir
            rd = ensure_res_dir(grafli_path)
            md_path = rd / f"{aid}.md"
            if not md_path.exists():
                title = arrow.label or f"{arrow.from_id} \u2192 {arrow.to_id}"
                md_path.write_text(f"# {title}\n\n", encoding="utf-8")
            rel = f"{rd.name}/{md_path.name}"
            self._push_undo()
            arrow.url = rel
            self._redraw_arrows()
            self.mark_dirty()
            self._open_md_zen(md_path)
            return

        for item in self._scene.selectedItems():
            if isinstance(item, (BoxItem, ImageItem)):
                url = ""
                element_id = ""
                if isinstance(item, BoxItem):
                    url = item.box.url
                    element_id = item.box.id
                elif isinstance(item, ImageItem):
                    url = item.image.url
                    element_id = item.image.id
                if url and url.endswith(".md"):
                    resolved = self._resolve_url(url)
                    self._open_md_zen(Path(resolved.toLocalFile()))
                    return
                if not url:
                    self._create_resource(item, element_id, "markdown")
                return

    def _cancel_zen_edit(self):
        """Discard zen editor."""
        self._zen_editor = None
        self._zen_target = None

    def _resolve_url(self, raw: str) -> QUrl:
        """Resolve a raw URL or local path to a QUrl for opening."""
        url = QUrl(raw)
        if url.isValid() and url.scheme() in ("http", "https", "ftp", "mailto"):
            return url
        # Split off #fragment before path resolution
        fragment = ""
        if "#" in raw:
            raw, fragment = raw.rsplit("#", 1)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            window = self.window()
            if hasattr(window, '_file_path') and window._file_path:
                path = Path(window._file_path).parent / path
        path = path.resolve()
        result = QUrl.fromLocalFile(str(path))
        if fragment:
            result.setFragment(fragment)
        return result

    def _open_url(self):
        """Open URL or local file of the first selected box or note."""
        for item in self._scene.selectedItems():
            url_str = None
            if isinstance(item, BoxItem) and item.box.url:
                url_str = item.box.url
            elif isinstance(item, NoteItem) and item.note.url:
                url_str = item.note.url
            if url_str:
                resolved = self._resolve_url(url_str)
                if resolved.isLocalFile() and resolved.toLocalFile().endswith(".md"):
                    self._open_md_zen(
                        Path(resolved.toLocalFile()),
                        anchor=resolved.fragment() or "",
                    )
                    return
                QDesktopServices.openUrl(resolved)
                return

    def _open_md_zen(self, path: Path, anchor: str = ""):
        """Open a local markdown file in the zen editor."""
        if self._zen_editor:
            return
        if not path.exists():
            path.write_text(f"# {path.stem}\n\n", encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        self._zen_editor = ZenMarkdownEditor(
            parent=self.window(), text=text, title=path.name,
            file_path=path, anchor=anchor, canvas=self,
        )
        self._zen_editor.cancelled.connect(self._cancel_zen_edit)

    def _zen_edit_note(self, item: NoteItem):
        """Edit a note's own text in the full-window zen editor.

        Unlike boxes/images, a note *is* its text — so the zen experience
        edits the note in memory rather than spawning an attached markdown
        file. Saved text is written straight back to the note.
        """
        if self._zen_editor:
            return
        self._zen_target = item
        self._zen_editor = ZenMarkdownEditor(
            parent=self.window(), text=item.note.text, title=item.note.id,
            file_path=None, canvas=self,
        )
        self._zen_editor.finished.connect(self._commit_zen_note)
        self._zen_editor.cancelled.connect(self._cancel_zen_edit)

    def _commit_zen_note(self, text: str):
        item = self._zen_target
        self._zen_editor = None
        self._zen_target = None
        if not isinstance(item, NoteItem):
            return
        new_text = text.strip()
        if new_text and new_text != item.note.text:
            self._push_undo()
            item.update_text(new_text)
            self.mark_dirty()

    def _edit_selected(self):
        for item in self._scene.selectedItems():
            if isinstance(item, (BoxItem, NoteItem)):
                self._start_editing(item)
                return

    def _toggle_minimap(self):
        self._minimap_visible = not self._minimap_visible
        self.viewport().update()

    def _minimap_selected_ids(self) -> set[str]:
        """Ids of the currently selected boxes, notes and images — the set
        the minimap rings with a glow."""
        ids = {bid for bid, it in self._box_items.items() if it.isSelected()}
        ids |= {nid for nid, it in self._note_items.items() if it.isSelected()}
        ids |= {iid for iid, it in self._image_items.items() if it.isSelected()}
        return ids

    def _refresh_minimap(self):
        """Repaint just the minimap panel (e.g. after a selection change) so
        its highlight updates without redrawing the whole board."""
        if not self._minimap_visible:
            return
        r = self._minimap_panel_rect
        if r is not None and not r.isNull():
            self.viewport().update(r.toRect().adjusted(-2, -2, 2, 2))
        else:
            self.viewport().update()

    def _start_editing(self, target: BoxItem | NoteItem):
        self._commit_editor()
        self._edit_target = target

        if isinstance(target, NoteItem):
            self._start_note_editing(target)
            return

        text = target.box.label
        pos = target.scenePos()
        rect = target.rect()
        font = target._box_font()
        target._label.setVisible(False)

        editor = QGraphicsTextItem(text)
        editor.setFont(font)
        editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        editor.setDefaultTextColor(QColor("#2F3437"))
        editor.setTextWidth(rect.width() - 16)
        br = editor.boundingRect()

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

        self._scene.addItem(editor)
        editor.setZValue(1000)
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        editor.setTextCursor(cursor)
        self._editor = editor

    def _start_note_editing(self, target: NoteItem):
        """Edit a note in place with the vim-capable inline editor.

        The editor is a plain `QPlainTextEdit` (vim keys, no grafli
        coupling) hosted in a proxy so it scales/pans with the canvas. It
        opens in INSERT mode; Esc drops to NORMAL, a second Esc commits,
        Shift+Esc discards. Markdown notes get syntax highlighting.
        """
        text = target.note.text
        font = target._note_font()

        widget = InlineVimEditor(text, markdown=note_is_md(target.note),
                                 font=font)
        widget.setStyleSheet(
            "QPlainTextEdit {"
            " background: #FBFAF7; color: #2F3437;"
            " border: 1px solid #2F5D5C; border-radius: 4px; padding: 4px;"
            " selection-background-color: #B8D4E8;"
            "}"
        )

        # Width tracks the widest line (bounded by the wrap budget); the
        # widget grows its own height to fit the text as you type.
        fm = QFontMetricsF(font)
        pad = 14
        lines = text.split("\n") or [""]
        content_w = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
        width_px = int(min(
            max(content_w + 2 * pad + 16, 140),
            target._wrap_width_px(font) + 2 * pad,
        ))

        proxy = QGraphicsProxyWidget()
        proxy.setWidget(widget)
        proxy.setZValue(1000)
        proxy.setPos(target.scenePos())
        self._scene.addItem(proxy)
        target.setVisible(False)

        widget.fit_to_width(width_px)

        widget.committed.connect(self._commit_note_editor)
        widget.cancelled.connect(self._cancel_note_editor)
        self._note_proxy = proxy
        self._note_widget = widget

        # The view must hold Qt focus and route to the proxy as the scene's
        # focus item; the proxy then forwards focus to the embedded editor.
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        proxy.setFocus(Qt.FocusReason.OtherFocusReason)

    def _commit_note_editor(self, text: str):
        target = self._edit_target
        if not isinstance(target, NoteItem):
            return
        new_text = text.strip()
        if new_text and new_text != target.note.text:
            self._push_undo()
            target.update_text(new_text)
            self.mark_dirty()
        self._teardown_note_editor()

    def _toggle_md_task(self, item, idx: int):
        """Flip the *idx*-th task checkbox in a markdown note and persist —
        a one-character source edit, one undo step, no editor."""
        new_text, changed = toggle_task(item.note.text, idx)
        if not changed:
            return
        self._push_undo()
        item.update_text(new_text)
        self.mark_dirty()

    def _cancel_note_editor(self):
        self._teardown_note_editor()

    def _teardown_note_editor(self):
        target = self._edit_target
        proxy = self._note_proxy
        self._note_proxy = None
        self._note_widget = None
        self._edit_target = None
        if isinstance(target, NoteItem):
            target.setVisible(True)
        if proxy is not None:
            # We may be inside the widget's own key handler (Esc commits),
            # so defer removal — destroying the widget synchronously under
            # its running event handler would crash.
            proxy.setVisible(False)
            QTimer.singleShot(0, lambda p=proxy: self._safe_remove_item(p))

    def _safe_remove_item(self, item):
        if item.scene() is self._scene:
            self._scene.removeItem(item)

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
        if self._note_widget is not None:
            self._commit_note_editor(self._note_widget.toPlainText())
            return
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
        # Empty commits are normally ignored (guards against a stray edit
        # wiping a label), but a glyph element may legitimately want no
        # caption so the icon fills the node — allow clearing then.
        target = self._edit_target
        has_icon = ((isinstance(target, BoxItem) and target.box.icon)
                    or (isinstance(target, NoteItem) and target.note.icon))
        if text or has_icon:
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
        if self._note_widget is not None:
            self._cancel_note_editor()
            return
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

    def _delete_selected(self, with_docs: bool = False):
        """Delete the selected elements. Vault docs survive by default (an
        unreferenced doc is a legitimate state); ``with_docs`` — the explicit
        Shift+Delete command — removes a deleted element's doc too, unless
        another element still references it. Undo restores the element with
        its body (snapshots embed it), and the next autosave lazily recreates
        the file — so doc deletion is undoable without stashing files."""
        if not self._board:
            return
        self._push_undo()
        deleted = False
        former_parents: set[str] = set()
        doc_names: set[str] = set()
        # Capture rects before removal so the 'pop' overlay marks where each
        # element was.
        pop_rects = [self._align_rect_for(it)
                     for it in self._scene.selectedItems()
                     if isinstance(it, (BoxItem, NoteItem, ImageItem))]

        def _track_doc(el):
            if el.attach_kind == "doc":
                from grafli.format import doc_name
                doc_names.add(doc_name(el))

        for item in list(self._scene.selectedItems()):
            if isinstance(item, BoxItem):
                box_id = item.box.id
                _track_doc(item.box)
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
                _track_doc(item.note)
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
            elif isinstance(item, ImageItem):
                img_id = item.image.id
                _track_doc(item.image)
                if item.image.parent:
                    former_parents.add(item.image.parent)
                for arrow in list(self._board.arrows):
                    if arrow.from_id == img_id or arrow.to_id == img_id:
                        self._board.remove_arrow(arrow)
                self._board.remove_image(item.image)
                self._image_items.pop(img_id, None)
                self._scene.removeItem(item)
                deleted = True
        if deleted:
            self._update_z_values()
            self._redraw_arrows()
            for pid in former_parents:
                if pid in self._box_items:
                    p_item = self._box_items[pid]
                    was_parent = p_item._is_parent
                    p_item._is_parent = self._has_children(pid)
                    if p_item._is_parent != was_parent:
                        p_item._apply_color()
                self._refresh_auto_layout(pid)
            self._handle_deleted_docs(doc_names, with_docs)
            for r in pop_rects:
                self._spawn_flash(r, color=self._FLASH_RED, mode="shrink",
                                  dur=160)
            self.mark_dirty()

    def _handle_deleted_docs(self, names: set[str], with_docs: bool) -> None:
        """After deleting doc-attached elements: keep their vault docs by
        default (with a hint), or — explicitly — delete the files of docs no
        remaining element references."""
        window = self.window()
        grafli_path = getattr(window, "_file_path", None)
        if not names or not grafli_path or not self._board:
            return
        from grafli.format import doc_name
        from grafli.resources import doc_path
        still = {doc_name(el)
                 for el in (*self._board.boxes, *self._board.notes,
                            *self._board.images, *self._board.arrows)
                 if el.attach_kind == "doc"}
        orphaned = sorted(n for n in names if n not in still)
        if not with_docs:
            if orphaned:
                self.toast("Kept in vault: "
                           + ", ".join(f"{n}.md" for n in orphaned)
                           + "  (Shift+Del deletes the doc too)")
            return
        removed, shared = [], sorted(n for n in names if n in still)
        for n in orphaned:
            try:
                doc_path(Path(grafli_path), n).unlink(missing_ok=True)
                removed.append(n)
            except OSError:
                pass
        if removed and hasattr(window, "_watch_docs"):
            window._watch_docs()   # re-baseline so the unlink doesn't echo back
        msg = ""
        if removed:
            msg = "Deleted from vault: " + ", ".join(f"{n}.md" for n in removed)
        if shared:
            msg += (" · " if msg else "") + "kept (still referenced): " \
                + ", ".join(f"{n}.md" for n in shared)
        if msg:
            self.toast(msg, "warn" if shared else "info")

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
        if self._selected_arrow and self._scene.selectedItems():
            self._deselect_arrow()
        window = self.window()
        if hasattr(window, '_status_sel'):
            count = len(self._scene.selectedItems())
            window._status_sel.setText(f"{count} selected" if count else "")
        self._update_breadcrumb()
        self._update_note_selection_highlight()
        self._refresh_minimap()
        self.selection_changed_for_panel.emit(bool(self._scene.selectedItems()))

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

    # Zoom-out is content-aware (stop before the board becomes a speck);
    # zoom-in is a fixed cap (so a few glyphs can't fill the screen).
    MIN_ZOOM_ABS = 0.02
    MAX_ZOOM = 5.0

    def _fit_zoom(self):
        """Scale at which the whole board (plus margin) just fits the viewport,
        or None when there's nothing to fit."""
        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            return None
        rect = rect.adjusted(-40, -40, 40, 40)
        vp = self.viewport().rect()
        if rect.width() <= 0 or rect.height() <= 0 or vp.width() <= 0 or vp.height() <= 0:
            return None
        return min(vp.width() / rect.width(), vp.height() / rect.height())

    def _zoom_bounds(self) -> tuple[float, float]:
        """(min, max) zoom. Min lets you zoom out until the board fills ~30%
        of the viewport — never forced above 100% — so small boards can't
        shrink to a dot; max is the fixed in-cap."""
        fit = self._fit_zoom()
        lo = (self.MIN_ZOOM_ABS if fit is None
              else min(1.0, max(self.MIN_ZOOM_ABS, fit * 0.3)))
        return lo, self.MAX_ZOOM

    def _clamp_zoom_factor(self, factor: float) -> tuple[float, bool]:
        """Adjust a relative zoom ``factor`` so the resulting scale stays in
        bounds. Returns (effective_factor, hit_limit)."""
        cur = self.transform().m11()
        lo, hi = self._zoom_bounds()
        target = max(lo, min(hi, cur * factor))
        eff = target / cur if cur else 1.0
        hit = abs(eff - 1.0) < 1e-9 and abs(factor - 1.0) > 1e-9
        return eff, hit

    def _zoom_limit_feedback(self, zooming_in: bool):
        """A rubber-band bounce plus a throttled toast when a zoom is blocked
        at the min/max bound."""
        self._start_zoom_bounce(zooming_in)
        now = time.monotonic()
        if now - self._zoom_limit_toast_at > 1.2:
            self._zoom_limit_toast_at = now
            self.toast("Max zoom" if zooming_in
                       else "Min zoom — ⇧Z to fit", kind="info")

    def _start_zoom_bounce(self, zooming_in: bool):
        """Spring the canvas ~4% past the limit and settle back. Input is
        briefly consumed (see wheelEvent / _zoom_keyboard) so it can't fight
        a new zoom mid-bounce."""
        if self._bounce_active:
            return
        self._bounce_active = True
        self._bounce_dir = 1.0 if zooming_in else -1.0
        self._bounce_last_s = 1.0
        self._bounce_base = QTransform(self.transform())
        self._bounce_prev_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        tl = QTimeLine(170, self)
        tl.setUpdateInterval(16)
        tl.valueChanged.connect(self._on_bounce_step)
        tl.finished.connect(self._on_bounce_finished)
        self._bounce_timeline = tl
        tl.start()

    def _on_bounce_step(self, v: float):
        s = 1.0 + self._bounce_dir * 0.04 * math.sin(math.pi * v)
        ratio = s / self._bounce_last_s
        self._bounce_last_s = s
        self.scale(ratio, ratio)

    def _on_bounce_finished(self):
        # Restore the exact pre-bounce transform (no float drift).
        self.setTransform(self._bounce_base)
        self.setTransformationAnchor(self._bounce_prev_anchor)
        self._bounce_timeline = None
        self._bounce_active = False
        self._update_status_zoom()

    def wheelEvent(self, event: QWheelEvent):
        if self._bounce_active:
            event.accept()
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        eff, hit = self._clamp_zoom_factor(factor)
        if hit:
            self._zoom_limit_feedback(factor > 1.0)
            event.accept()
            return
        self.scale(eff, eff)
        self._update_status_zoom()

    def _zoom_keyboard(self, factor: float):
        """Zoom for the +/- shortcuts, anchored on what the user cares about.

        With a selection, the combined bounding-rect center of the selected
        items is held fixed on screen; otherwise the viewport center is. Either
        way the focal point stays put while the rest of the canvas scales around
        it. (Wheel zoom keeps its own under-the-mouse anchor.)
        """
        if self._bounce_active:
            return
        eff, hit = self._clamp_zoom_factor(factor)
        if hit:
            self._zoom_limit_feedback(factor > 1.0)
            return
        factor = eff
        items = self._scene.selectedItems()
        if items:
            rect = items[0].sceneBoundingRect()
            for it in items[1:]:
                rect = rect.united(it.sceneBoundingRect())
            anchor_scene = rect.center()
        else:
            anchor_scene = self.mapToScene(self.viewport().rect().center())
        prev_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        before = self.mapFromScene(anchor_scene)
        self.scale(factor, factor)
        delta = self.mapFromScene(anchor_scene) - before
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + delta.y())
        self.setTransformationAnchor(prev_anchor)
        self._update_status_zoom()

    def mousePressEvent(self, event):
        # Middle- or right-click pans from anywhere.
        if event.button() in (Qt.MouseButton.MiddleButton,
                              Qt.MouseButton.RightButton):
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
            self._mouse_press_pos = event.position()
            self._drag_moved = False
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
            if (event.buttons() & Qt.MouseButton.LeftButton
                    and self._mouse_press_pos is not None
                    and (event.position() - self._mouse_press_pos).manhattanLength()
                        >= QApplication.startDragDistance()):
                self._drag_moved = True
            selected = self._scene.selectedItems()
            if selected and not self._autoscroll_timer.isActive() and event.buttons() & Qt.MouseButton.LeftButton:
                self._autoscroll_timer.start()
            if len(selected) > 1:
                self._batch_move_updates = True
                super().mouseMoveEvent(event)
                self._batch_move_updates = False
                self._redraw_arrows()
                self.mark_dirty()
            else:
                super().mouseMoveEvent(event)
            # Preview reparenting only while actually dragging a selection — not
            # on plain hover, which would otherwise flash the grow outline when
            # the cursor merely passes over a box (e.g. while shift-selecting).
            if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_moved:
                self._update_reparent_highlight(scene_pos)
            else:
                self._clear_reparent_highlight()
        elif self._mode == Mode.RECT:
            self._update_create_preview_pos(scene_pos)
            self._move_rect(event)
        elif self._mode == Mode.TEXT:
            self._update_create_preview_pos(scene_pos)
            super().mouseMoveEvent(event)
        elif self._mode == Mode.CONNECT:
            self._move_connect(event)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Minimap drag end
        if self._minimap_release():
            event.accept()
            return

        if event.button() in (Qt.MouseButton.MiddleButton,
                              Qt.MouseButton.RightButton):
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
                elif isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), (BoxItem, NoteItem, ImageItem)):
                    item = item.parentItem()
                if (isinstance(item, (BoxItem, NoteItem, ImageItem))
                        and item is not self._connect_source
                        and self._board):
                    src_id = self._item_id(self._connect_source)
                    tgt_id = self._item_id(item)
                    existing = self._find_existing_arrow(src_id, tgt_id)
                    if existing:
                        self._select_arrow(existing)
                    else:
                        self._push_undo()
                        arrow = self._make_connector(src_id, tgt_id)
                        self._board.add_arrow(arrow)
                        self._redraw_arrows()
                        self.mark_dirty()
                self._connect_source = None
                event.accept()
                return
            self._clear_reparent_highlight()
            self._autoscroll_timer.stop()
            super().mouseReleaseEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                # Only a real drag may reparent — a plain or shift+click just
                # changes the selection and must not nest items under the cursor.
                if self._drag_moved:
                    cursor_scene = self.mapToScene(event.position().toPoint())
                    selected = [
                        i for i in self._scene.selectedItems()
                        if isinstance(i, (BoxItem, NoteItem, ImageItem))
                    ]
                    # Reparent only when a single item is dragged — mirrors the
                    # drag preview (_update_reparent_highlight, single-selection
                    # only). Moving a multi-selection just relocates the items
                    # together; nesting the whole group into whichever member
                    # happens to sit under the cursor is never intended.
                    if len(selected) == 1:
                        self._check_nesting(selected[0], cursor_scene)
                self._commit_pre_action_snapshot()
                self._drag_moved = False
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
        # Fuzzy overlay handles its own input
        if self._fuzzy_overlay:
            return

        # Zen overlay handles its own input
        if self._zen_editor:
            return

        # Inline note editor: the view is the focused Qt widget, so forward
        # keys down to the scene's focus item (the proxy → embedded editor)
        # instead of running canvas shortcuts. Without super() the proxy
        # would never receive any keystrokes.
        if self._note_widget is not None:
            super().keyPressEvent(event)
            return

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
            if event.key() == Qt.Key.Key_G and event.modifiers() & _CTRL_MOD:
                self._open_glyph_picker()
                event.accept()
                return
            # Let the editor handle the key
            super().keyPressEvent(event)
            return

        # Flow playback owns all input while active
        if self._flow_player is not None and self._flow_player.active:
            self._flow_player.handle_key(event)
            event.accept()
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

        # Colour-grid picker owns all input while open
        if self._color_picker_active:
            self._handle_color_picker_key(event)
            event.accept()
            return

        # Icon-grid picker owns all input while open
        if self._icon_picker_active:
            self._handle_icon_picker_key(event)
            event.accept()
            return

        # Type grid owns all input while open
        if self._type_picker_active:
            self._handle_type_picker_key(event)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Escape:
            if self._search_filter_active:
                self._clear_search_filter()
                event.accept()
                return
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
            self._delete_selected(
                with_docs=bool(event.modifiers()
                               & Qt.KeyboardModifier.ShiftModifier))
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
                # a — toggle connector kind (graph edge ⇄ annotation)
                if no_mod_a and key == Qt.Key.Key_A:
                    self._push_undo()
                    arrow = self._selected_arrow
                    arrow.kind = ("graph" if self._is_annotation_link(arrow)
                                  else "annotation")
                    self._last_connector_kind = arrow.kind
                    self._redraw_arrows()
                    self._select_arrow(arrow, keep_mode=True)
                    self._update_arrow_mode_badge_pos()
                    self.mark_dirty()
                    self._record_shortcut(
                        "connector → graph edge" if arrow.kind == "graph"
                        else "connector → annotation")
                    event.accept()
                    return
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
        shift_only = (mods & _SIGNIFICANT_MODS) == Qt.KeyboardModifier.ShiftModifier

        # g-prefix two-key sequences
        if self._g_pending:
            self._g_pending = False
            if event.key() == Qt.Key.Key_P and no_mod:
                self._record_shortcut("gp → parent")
                self._select_parent_and_zoom()
            elif event.key() == Qt.Key.Key_C and no_mod:
                self._record_shortcut("gc → first child")
                self._select_first_child()
            elif event.key() == Qt.Key.Key_B and no_mod:
                self._record_shortcut("gb → bookmark")
                self.capture_bookmark("logical")
            elif event.key() == Qt.Key.Key_B and shift_only:
                self._record_shortcut("gB → viewport bookmark")
                self.capture_bookmark("viewport")
            elif event.key() == Qt.Key.Key_F and no_mod:
                self._record_shortcut("gf → flow rec")
                self.toggle_flow_recording()
            elif event.key() == Qt.Key.Key_F and shift_only:
                self._record_shortcut("gF → auto-flow")
                self.new_auto_flow_from_selection()
            elif event.key() == Qt.Key.Key_Z and no_mod:
                self._record_shortcut("gz → focus zoom")
                self._toggle_focus_zoom()
            event.accept()
            return

        # Q — close buffer (SELECT mode, no selection, no arrow)
        if (event.key() == Qt.Key.Key_Q and no_mod
                and self._mode == Mode.SELECT
                and not has_selection
                and not self._selected_arrow):
            window = self.window()
            if hasattr(window, 'close_buffer'):
                window.close_buffer()
                event.accept()
                return

        # Vim aliases — u (undo), Ctrl+R (redo), x (delete), o/O (adjacent box)
        if event.key() == Qt.Key.Key_U and no_mod:
            self._record_shortcut("u \u2192 undo")
            self._undo()
            event.accept()
            return
        if event.key() == Qt.Key.Key_R and mods & _CTRL_MOD:
            self._record_shortcut("Ctrl+R \u2192 redo")
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
        if event.key() == Qt.Key.Key_E and shift_only and self._selected_arrow:
            self._quick_edit_markdown()
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
        # y — yank (copy), p — paste
        if event.key() == Qt.Key.Key_Y and no_mod:
            self._record_shortcut("y → yank")
            self._copy_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Y and shift_only:
            self._record_shortcut("Y → PNG clipboard")
            self._yank_png_to_clipboard()
            event.accept()
            return
        if event.key() == Qt.Key.Key_P and no_mod:
            self._record_shortcut("p → paste")
            self._paste()
            event.accept()
            return
        # / — search (text-based so Shift+7 on German/EU layouts works)
        if event.text() == "/" and not (mods & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )):
            self._start_search()
            event.accept()
            return

        # = — auto-layout (SELECT mode, text-based for non-US layouts)
        if event.text() == "=" and self._mode == Mode.SELECT:
            self._record_shortcut("= \u2192 layout")
            self._layout_selected()
            event.accept()
            return

        # Zoom with + (Shift+= produces Key_Plus)
        if event.key() == Qt.Key.Key_Plus:
            self._record_shortcut("+ \u2192 zoom in")
            self._zoom_keyboard(1.15)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Minus:
            self._record_shortcut("- \u2192 zoom out")
            self._zoom_keyboard(1 / 1.15)
            event.accept()
            return

        # Ctrl+E — export SVG to file
        if event.key() == Qt.Key.Key_E and mods & _CTRL_MOD:
            self._export_svg_file()
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
            if len(sel) == 1 and isinstance(sel[0], (BoxItem, NoteItem, ImageItem)):
                self._enter_graph_nav(sel[0])
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

        # ` — toggle debug overlay (text-based for non-US layouts)
        if event.text() == "`":
            self._debug_overlay = not self._debug_overlay
            self._record_shortcut("DEBUG ON" if self._debug_overlay else "DEBUG OFF")
            event.accept()
            return

        # F1 — cheatsheet
        if event.key() == Qt.Key.Key_F1:
            self._show_cheatsheet()
            event.accept()
            return

        # Ctrl+G — encapsulate the selection in a new parent box
        if event.key() == Qt.Key.Key_G and mods & _CTRL_MOD and has_selection:
            self._record_shortcut("Ctrl+G → encapsulate")
            self._encapsulate_selection()
            event.accept()
            return

        # Vim-like box modes — SELECT mode with selection
        if self._mode == Mode.SELECT and has_selection:
            shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            only_shift = shift and not (mods & ~Qt.KeyboardModifier.ShiftModifier & _SIGNIFICANT_MODS)

            if self._grid_snap:
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
                    self._ensure_selection_visible()
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

            # ── Style mode: c opens the colour grid, j/k sizes ──
            elif self._box_mode == "style":
                if event.key() == Qt.Key.Key_C and no_mod:
                    self._open_color_picker()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_I and no_mod:
                    self._open_icon_picker()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_T and no_mod:
                    self._open_type_picker()
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
                if event.key() == Qt.Key.Key_R and no_mod:
                    self._snap_selection_to_slide_ratio()
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
                if event.key() == Qt.Key.Key_W:
                    self._clear_box_mode()
                    self._set_url()
                    event.accept()
                    return
                if event.key() == Qt.Key.Key_Return:
                    self._clear_box_mode()
                    self._open_resource()
                    event.accept()
                    return

            # E (Shift+E) — quick-create/open markdown resource
            if event.key() == Qt.Key.Key_E and shift_only:
                self._clear_box_mode()
                self._quick_edit_markdown()
                event.accept()
                return

        # Shift+G — snap to grid (SELECT mode with selection)
        if (event.key() == Qt.Key.Key_G
                and mods & Qt.KeyboardModifier.ShiftModifier
                and self._mode == Mode.SELECT and has_selection):
            self._snap_to_grid()
            event.accept()
            return

        # # — toggle grid
        if event.text() == "#":
            self.toggle_grid()
            self._record_shortcut(f"# \u2192 {self._GRID_LABELS[self._grid_mode]}")
            event.accept()
            return

        # g — start g-prefix sequence
        if event.key() == Qt.Key.Key_G and no_mod:
            self._g_pending = True
            self._record_shortcut("g\u2026")
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

        # hjkl panning (no selection)
        if self._mode == Mode.SELECT and not has_selection:
            shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            only_shift = shift and not (mods & ~Qt.KeyboardModifier.ShiftModifier & _SIGNIFICANT_MODS)
            if no_mod or only_shift:
                PAN_STEP = 50
                FAST_PAN_STEP = 200
                amount = FAST_PAN_STEP if shift else PAN_STEP
                hjkl_pan = {
                    Qt.Key.Key_H: (-amount, 0),
                    Qt.Key.Key_J: (0, amount),
                    Qt.Key.Key_K: (0, -amount),
                    Qt.Key.Key_L: (amount, 0),
                }
                if event.key() in hjkl_pan:
                    dx, dy = hjkl_pan[event.key()]
                    self.horizontalScrollBar().setValue(
                        self.horizontalScrollBar().value() + dx
                    )
                    self.verticalScrollBar().setValue(
                        self.verticalScrollBar().value() + dy
                    )
                    event.accept()
                    return

        # \ — toggle side panel
        if event.text() == "\\":
            window = self.window()
            if hasattr(window, '_toggle_panel'):
                window._toggle_panel()
            event.accept()
            return

        # M — toggle minimap
        if event.key() == Qt.Key.Key_M and no_mod:
            self._toggle_minimap()
            event.accept()
            return

        # Z — zoom to selection (no-op if nothing selected)
        if event.key() == Qt.Key.Key_Z and no_mod:
            self._cycle_zoom_step()
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

        # f — jump mode (alternative to Ctrl+J). First-child now lives on `gc`.
        if event.key() == Qt.Key.Key_F and no_mod:
            self._clear_box_mode()
            self._start_jump_mode()
            event.accept()
            return

        # , — toggle arrow dimming
        if event.key() == Qt.Key.Key_Comma and no_mod:
            self._toggle_arrows_dimmed()
            event.accept()
            return

        # A — complexity analysis heatmap
        if event.key() == Qt.Key.Key_A and no_mod:
            self._toggle_complexity()
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
        if shift_only and event.key() == Qt.Key.Key_B:
            if self._focus_active:
                self._focus_depth = 0 if self._focus_depth == 1 else 1
                self._apply_focus_filter()
            event.accept()
            return

        # Shift+N toggles "notes hidden" — concentrate on the graph.
        if shift_only and event.key() == Qt.Key.Key_N:
            self._toggle_notes_hidden()
            event.accept()
            return

        # Mode switching shortcuts (no modifiers).
        # In RECT / TEXT mode, holding Shift while clicking keeps the mode
        # active for rapid placement; clicking without Shift exits to SELECT.
        if no_mod:
            mode_keys = {
                Qt.Key.Key_V: Mode.SELECT,
                Qt.Key.Key_N: Mode.RECT,
                Qt.Key.Key_T: Mode.TEXT,
                Qt.Key.Key_C: Mode.CONNECT,
            }
            if event.key() in mode_keys:
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
        elif isinstance(resolved, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(resolved.parentItem(), (BoxItem, NoteItem, ImageItem)):
            resolved = resolved.parentItem()

        # Shift+click toggles selection on individual items
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if isinstance(resolved, (BoxItem, NoteItem, ImageItem)):
                # Shift on a resize handle of an already-selected item starts a
                # ratio-locked scale, not a selection toggle — let the item's
                # own mousePressEvent begin the drag.
                if resolved.isSelected() and hasattr(resolved, "_handle_at"):
                    local = resolved.mapFromScene(scene_pos)
                    if resolved._handle_at(local) is not None:
                        super().mousePressEvent(event)
                        return
                resolved.setSelected(not resolved.isSelected())
                event.accept()
                return
            # Shift+click on empty space: preserve current selection
            event.accept()
            return

        # Alt+click on a node (box/note/image) starts connector drag
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and isinstance(resolved, (BoxItem, NoteItem, ImageItem)):
            self._connect_source = resolved
            center = self._item_center(resolved)
            pen = QPen(ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
            self._connect_line = self._scene.addLine(
                center.x(), center.y(), scene_pos.x(), scene_pos.y(), pen
            )
            event.accept()
            return

        # Alt+click on empty space: paste clipboard at position
        if (event.modifiers() & Qt.KeyboardModifier.AltModifier) and not isinstance(resolved, (BoxItem, NoteItem, ImageItem)):
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
        # Hide the cursor ghost while the drag-rectangle is live
        if self._create_preview is not None:
            self._create_preview.setVisible(False)
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
        box = Box(id=box_id, label="A Node", x=x, y=y, w=w, h=h,
                  color=self._last_box_color,
                  textsize=self._last_box_textsize)
        self._board.add_box(box)

        item = BoxItem(box)
        self._scene.addItem(item)
        self._scene.addItem(item._label)
        self._box_items[box_id] = item
        self.mark_dirty()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Shift held — stay in RECT mode for rapid placement
            item.setSelected(True)
            self._refresh_create_preview()
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
        note = Note(id="", x=scene_pos.x(), y=scene_pos.y(),
                    text="Some text ...",
                    textsize=self._last_note_textsize)
        self._board.add_note(note)

        item = NoteItem(note)
        self._scene.addItem(item)
        self._note_items[note.id] = item
        self.mark_dirty()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Shift held — stay in TEXT mode for rapid placement
            item.setSelected(True)
            self._refresh_create_preview()
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
        elif isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), (BoxItem, NoteItem, ImageItem)):
            item = item.parentItem()

        if not isinstance(item, (BoxItem, NoteItem, ImageItem)):
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
                    arrow = self._make_connector(src_id, tgt_id)
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
        elif isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem, ResizeHandle)) and isinstance(item.parentItem(), (BoxItem, NoteItem, ImageItem)):
            item = item.parentItem()

        if (isinstance(item, (BoxItem, NoteItem, ImageItem))
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
                arrow = self._make_connector(src_id, tgt_id)
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

        bg = QColor("#2F3437")
        bg.setAlphaF(0.92 * o)
        painter.setPen(QPen(QColor(255, 255, 255, int(40 * o)), 1))
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
        self._scene.addItem(new_item._label)
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

        note = Note(id="", x=x, y=y, text="Note",
                    textsize=self._last_note_textsize)
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
        # Clamp to reasonable bounds (same in-cap as interactive zoom).
        target_zoom = max(self.MIN_ZOOM_ABS, min(target_zoom, self.MAX_ZOOM))
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

    def _animate_to_zoom_and_center(self, zoom: float, center: QPointF):
        """Smoothly animate to an explicit zoom level centered on a scene
        point. Unlike `_animate_to_rect` (which derives zoom from a fit),
        this preserves an exact scale — used by search cycling so every
        match lands at the same zoom level.
        """
        if self._zoom_timeline is not None:
            self._zoom_timeline.stop()
            self._zoom_timeline = None

        start_zoom = self.transform().m11()
        start_center = self.mapToScene(self.viewport().rect().center())
        target_zoom = max(self.MIN_ZOOM_ABS, min(zoom, self.MAX_ZOOM))

        self._anim_start_zoom = start_zoom
        self._anim_end_zoom = target_zoom
        self._anim_start_center = start_center
        self._anim_end_center = center

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

    _AUTOSCROLL_MARGIN = 40   # px from viewport edge to trigger
    _AUTOSCROLL_SPEED = 8     # px per tick

    def _autoscroll_tick(self) -> None:
        selected = self._scene.selectedItems()
        if not selected:
            self._autoscroll_timer.stop()
            return
        vp = self.viewport().rect()
        cursor_vp = self.viewport().mapFromGlobal(QCursor.pos())
        if not vp.contains(cursor_vp):
            return
        margin = self._AUTOSCROLL_MARGIN
        speed = self._AUTOSCROLL_SPEED
        dx = dy = 0
        if cursor_vp.x() > vp.width() - margin:
            dx = speed
        elif cursor_vp.x() < margin:
            dx = -speed
        if cursor_vp.y() > vp.height() - margin:
            dy = speed
        elif cursor_vp.y() < margin:
            dy = -speed
        if dx or dy:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)

    def _ensure_selection_visible(self) -> None:
        """Scroll viewport if any selected item is near or beyond the edge."""
        selected = self._scene.selectedItems()
        if not selected:
            return
        vp = self.viewport().rect()
        margin = 40
        dx = dy = 0
        for item in selected:
            item_vp = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
            if item_vp.right() > vp.width() - margin:
                dx = max(dx, int(item_vp.right() - (vp.width() - margin)))
            if item_vp.left() < margin:
                dx = min(dx, int(item_vp.left() - margin))
            if item_vp.bottom() > vp.height() - margin:
                dy = max(dy, int(item_vp.bottom() - (vp.height() - margin)))
            if item_vp.top() < margin:
                dy = min(dy, int(item_vp.top() - margin))
        if dx or dy:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)

    _ZOOM_STEPS: tuple[float, ...] = (0.25, 0.5, 1.0, 1.5)

    def _cycle_zoom_step(self):
        """z key: zoom in to the next-larger step in `_ZOOM_STEPS`,
        wrapping back to the smallest after the largest. Always zooms
        *in* relative to current — never sideways or out — so a single
        keypress has a predictable direction. For "fit the whole graph"
        use Shift+Z.
        """
        if not self._board:
            return
        self._push_nav_snapshot()
        current = self.transform().m11()
        # Small tolerance so an "exactly at a step" zoom still advances
        # to the next step instead of getting stuck.
        threshold = current * 1.01
        next_zoom: float | None = None
        for step in self._ZOOM_STEPS:
            if step > threshold:
                next_zoom = step
                break
        if next_zoom is None:
            next_zoom = self._ZOOM_STEPS[0]
        center = self.mapToScene(self.viewport().rect().center())
        self._animate_to_zoom_and_center(next_zoom, center)

    def _zoom_to_fit(self):
        """Shift+Z key: zoom to fit entire diagram."""
        if not self._board:
            return
        items_rect = self._scene.itemsBoundingRect()
        if not items_rect.isNull():
            self._animate_to_rect(items_rect.adjusted(-40, -40, 40, 40))

    # ── Bookmarks & flows ──

    def goto_rect(self, rect: QRectF, animate: bool = True):
        """Frame ``rect`` in the viewport, eased or as an instant cut."""
        if rect.isNull():
            return
        if animate:
            self._animate_to_rect(rect)
            return
        vp = self.viewport().rect()
        zoom = min(vp.width() / max(rect.width(), 1),
                   vp.height() / max(rect.height(), 1))
        zoom = max(0.05, min(zoom, 10.0))
        self.setTransform(QTransform().scale(zoom, zoom))
        self.centerOn(rect.center())
        self._update_status_zoom()

    def goto_bookmark(self, bookmark_id: str, animate: bool = True):
        """Fly the canvas to a bookmark's semantic anchor."""
        if not self._board:
            return
        bm = self._board.bookmark_by_id(bookmark_id)
        if bm is None:
            return
        from grafli.flows import bookmark_target_rect
        target = bookmark_target_rect(self, bm)
        self.goto_rect(target, animate=animate)
        self.flash_anchor(target)

    def play_flow(self, flow_id: str):
        """Enter modal playback for a flow, starting at its first stop."""
        if not self._board:
            return
        flow = self._board.flow_by_id(flow_id)
        if flow is None or not flow.steps:
            return
        if self._flow_player is not None:
            self._flow_player.stop()
        self._flow_player = FlowPlayer(self, flow)
        self._flow_player.start()
        self.setFocus()

    def export_flow(self, flow, fmt: str = "pdf"):
        """Export a specific flow via the main window's save dialog. ``fmt`` is
        'pdf' (default) or 'pptx'."""
        window = self.window()
        method = "_export_flow_pptx" if fmt == "pptx" else "_export_flow_pdf"
        if window is not None and hasattr(window, method):
            getattr(window, method)(flow)

    def capture_bookmark(self, mode: str = "logical"):
        """Snapshot the current view as a bookmark.

        ``logical`` (gb): anchor to what's shown — the current selection, else
        every item visible in the viewport — so the saved view re-fits as the
        layout changes. If nothing is shown (empty space), it transparently
        falls back to storing the exact viewport, so capture never fails.

        ``viewport`` (gB): always store the exact current viewport, for a
        hand-tuned framing you want reproduced pixel-faithfully.

        Notes are valid anchors, so a note-only (node-less) bookmark works.
        """
        if not self._board:
            return
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        focus: list[str] = []
        isolate = False
        if mode == "logical":
            focus = [bid for bid, it in self._box_items.items() if it.isSelected()]
            focus += [nid for nid, it in self._note_items.items() if it.isSelected()]
            focus += [iid for iid, it in self._image_items.items() if it.isSelected()]
            # An explicit selection narrows the step's scope: render only these
            # items in thumbnails/PDF. No selection falls back to the viewport.
            isolate = bool(focus)
            if focus:
                # A selected parent brings its whole subtree, so isolating it
                # shows the contents instead of an empty container.
                focus = self._expand_focus_to_subtrees(focus)
            if not focus:
                for bid, it in self._box_items.items():
                    if it.sceneBoundingRect().intersects(vp_scene):
                        focus.append(bid)
                for nid, it in self._note_items.items():
                    if it.sceneBoundingRect().intersects(vp_scene):
                        focus.append(nid)
                for iid, it in self._image_items.items():
                    if it.sceneBoundingRect().intersects(vp_scene):
                        focus.append(iid)

        view_rect = None if focus else (
            vp_scene.x(), vp_scene.y(), vp_scene.width(), vp_scene.height()
        )

        label, ok = QInputDialog.getText(
            self, "New bookmark", "Label (blank = graph-only slide):")
        if not ok:
            self._record_shortcut("bookmark cancelled — not created")
            return
        label = label.strip()
        # A blank label means "let the graph speak" — no title/caption chrome,
        # so we skip the description prompt too.
        description = ""
        if label:
            desc, ok2 = QInputDialog.getMultiLineText(
                self, "Bookmark", "Description (optional):", "")
            if ok2:
                description = desc.strip()
        bm = Bookmark(
            id=self._board.next_bookmark_id(),
            label=label,
            focus=focus,
            description=description,
            view=view_rect,
            isolate=isolate,
        )
        self._board.add_bookmark(bm)
        if self._recording_flow is not None:
            # Recording is sequential — always append to the tour.
            self._recording_flow.steps.append(FlowStep(ref=bm.id))
            self._update_recording_status()
        elif self._active_flow is not None:
            # A flow is open in the panel — insert right after the selected
            # step (or append), then advance the selection so the next
            # capture continues the chain.
            steps = self._active_flow.steps
            idx = self._active_step_index
            if 0 <= idx < len(steps):
                steps.insert(idx + 1, FlowStep(ref=bm.id))
                self._active_step_index = idx + 1
            else:
                steps.append(FlowStep(ref=bm.id))
                self._active_step_index = len(steps) - 1
        self.mark_dirty()
        self.flows_changed.emit()
        from grafli.flows import bookmark_target_rect, text_slide_note
        if text_slide_note(self, bm) is not None:
            kind = "text slide"
        elif isolate:
            kind = f"scoped: {len(focus)} item{'s' if len(focus) != 1 else ''}"
        else:
            kind = "viewport" if view_rect else "logical"
        self._record_shortcut(f"bookmark “{bm.label}” ({kind})")
        self.flash_anchor(bookmark_target_rect(self, bm))

    def toggle_flow_recording(self):
        """Start a new flow recording, or stop the active one.

        While recording, each captured bookmark is also appended to the
        active flow — so a tour accretes as you explore, no separate
        compose step.
        """
        if not self._board:
            return
        if self._recording_flow is not None:
            flow = self._recording_flow
            self._recording_flow = None
            if not flow.steps:
                # An empty recording is noise — drop it.
                self._board.remove_flow(flow)
            self.mark_dirty()
            self.flows_changed.emit()
            self._update_recording_status()
            self.viewport().update()
            return
        label, ok = QInputDialog.getText(self, "Record flow", "Flow name:")
        if not ok or not label.strip():
            return
        flow = Flow(id=self._board.next_flow_id(), label=label.strip(), steps=[])
        self._board.add_flow(flow)
        self._recording_flow = flow
        self.mark_dirty()
        self.flows_changed.emit()
        self._update_recording_status()
        self.viewport().update()

    def _update_recording_status(self):
        if self._recording_flow is not None:
            n = len(self._recording_flow.steps)
            self._record_shortcut(
                f"REC {self._recording_flow.label} · {n} stop(s) · gb to add"
            )

    # ── Flow / bookmark editing (driven by the Flows panel) ──

    def set_flow_edit_target(self, flow, step_index: int = -1):
        """Remember which flow/step the panel has selected, so a captured
        bookmark is inserted after it."""
        self._active_flow = flow
        self._active_step_index = step_index

    def _commit_flow_edit(self):
        """Persist a flow/bookmark mutation and refresh the panel."""
        self.mark_dirty()
        self.flows_changed.emit()

    def create_flow(self, label: str, description: str = ""):
        if not self._board:
            return None
        flow = Flow(id=self._board.next_flow_id(), label=label,
                    description=description)
        self._board.add_flow(flow)
        self._commit_flow_edit()
        return flow

    # ── Auto-generated flows (walk forward arrows from a start node) ──

    def _is_annotation_link(self, arrow: Arrow) -> bool:
        """Whether ``arrow`` is an annotation link (vs. a real graph edge).

        ``arrow.kind`` overrides when set; otherwise the kind derives from the
        endpoints — a note or image endpoint makes it an annotation, box↔box is
        a graph edge. This resolver is the single source of truth for rendering,
        the note/image-selection spotlight, auto-flow, and graph-nav.
        """
        if arrow.kind == "annotation":
            return True
        if arrow.kind == "graph":
            return False
        if not self._board:
            return False
        return self._involves_note_or_image(arrow.from_id, arrow.to_id)

    def _involves_note_or_image(self, from_id: str, to_id: str) -> bool:
        """Whether either endpoint is a note or image — the non-box elements
        whose connectors default to (and remember) an annotation/graph kind."""
        if not self._board:
            return False
        return bool(self._board.note_by_id(from_id)
                    or self._board.note_by_id(to_id)
                    or self._board.image_by_id(from_id)
                    or self._board.image_by_id(to_id))

    def _is_graph_edge(self, arrow: Arrow) -> bool:
        """Whether ``arrow`` is a real graph edge (the auto-flow/graph-nav seam)."""
        return self._board is not None and not self._is_annotation_link(arrow)

    def _make_connector(self, from_id: str, to_id: str) -> Arrow:
        """A new connector, applying the sticky connector kind when a note or
        image is involved (so a run of connected notes/images inherits your last
        choice)."""
        arrow = Arrow(from_id=from_id, to_id=to_id)
        if self._involves_note_or_image(from_id, to_id) and self._last_connector_kind:
            arrow.kind = self._last_connector_kind
        return arrow

    def _strict_forward_target(self, arrow: Arrow, node_id: str) -> str | None:
        """The node ``arrow`` leads to from ``node_id`` via a strict-forward
        edge, else None. Strict = exactly one arrowhead, pointing away."""
        if arrow.head_to == arrow.head_from:      # both/neither head → not strict
            return None
        if arrow.from_id == node_id and arrow.head_to:
            return arrow.to_id
        if arrow.to_id == node_id and arrow.head_from:
            return arrow.from_id
        return None

    def _forward_targets(self, node_id: str) -> list[str]:
        """Distinct nodes reachable from ``node_id`` by a strict-forward edge."""
        out: list[str] = []
        if not self._board:
            return out
        for arrow in self._board.arrows:
            if not self._is_graph_edge(arrow):
                continue
            t = self._strict_forward_target(arrow, node_id)
            if t is not None and t not in out:
                out.append(t)
        return out

    def _auto_flow_path(self, start_id: str) -> tuple[list[str], str]:
        """Walk strict-forward from ``start_id``: returns (node ids, stop reason).

        Continues while a node has exactly one forward target; stop reason is
        ``end`` (no forward), ``branch`` (several), or ``cycle`` (revisit).
        """
        path = [start_id]
        visited = {start_id}
        reason = "end"
        current = start_id
        while True:
            targets = self._forward_targets(current)
            if not targets:
                reason = "end"
                break
            if len(targets) > 1:
                reason = "branch"
                break
            nxt = targets[0]
            if nxt in visited:
                reason = "cycle"
                break
            path.append(nxt)
            visited.add(nxt)
            current = nxt
        return path, reason

    def _make_auto_bookmark(self, node_id: str) -> Bookmark:
        """An isolated bookmark framing one node (a parent expands to its
        subtree). A box keeps its label (titled slide); a note stays
        label-less so it renders as a pure text slide."""
        box = self._board.box_by_id(node_id)
        label = box.label if box else ""
        focus = self._expand_focus_to_subtrees([node_id])
        bm = Bookmark(id=self._board.next_bookmark_id(), label=label,
                      focus=focus, isolate=True)
        self._board.add_bookmark(bm)
        return bm

    def _populate_auto_flow(self, flow: Flow) -> None:
        path, reason = self._auto_flow_path(flow.auto_start)
        flow.steps = [FlowStep(ref=self._make_auto_bookmark(nid).id)
                      for nid in path]
        n = len(path)
        if reason == "branch":
            box = self._board.box_by_id(path[-1])
            where = (box.label.replace("\n", " ") if box and box.label
                     else path[-1])
            self._record_shortcut(
                f"auto-flow: {n} step(s), stopped at branch '{where}'")
        elif reason == "cycle":
            self._record_shortcut(f"auto-flow: {n} step(s), stopped (cycle)")
        else:
            self._record_shortcut(f"auto-flow: {n} step(s)")

    def _discard_auto_bookmarks(self, flow: Flow) -> None:
        """Remove the bookmarks this flow's steps own (not used by any other
        flow), so re-generating doesn't leave orphans behind."""
        others: set[str] = set()
        for f in self._board.flows:
            if f is flow:
                continue
            others.update(s.ref for s in f.steps)
        for step in list(flow.steps):
            if step.ref not in others:
                bm = self._board.bookmark_by_id(step.ref)
                if bm is not None:
                    self._board.remove_bookmark(bm)
        flow.steps = []

    def _node_exists(self, node_id: str) -> bool:
        """True if ``node_id`` is a real graph node (box, note or image)."""
        return bool(self._board and (self._board.box_by_id(node_id)
                                     or self._board.note_by_id(node_id)
                                     or self._board.image_by_id(node_id)))

    def create_auto_flow(self, start_id: str, label: str):
        """Create a flow by walking forward arrows from ``start_id``."""
        if not self._node_exists(start_id):
            self._record_shortcut("auto-flow needs a node")
            return None
        self._push_undo()
        flow = Flow(id=self._board.next_flow_id(), label=label,
                    auto_start=start_id)
        self._board.add_flow(flow)
        self._populate_auto_flow(flow)
        self._commit_flow_edit()
        return flow

    def regenerate_auto_flow(self, flow):
        """Re-walk from the flow's stored start node: rewrite the steps, keep
        the title page (label/description)."""
        if not self._board or flow is None or not flow.auto_start:
            return
        if not self._node_exists(flow.auto_start):
            self._record_shortcut("auto-flow: start node is gone")
            return
        self._push_undo()
        self._discard_auto_bookmarks(flow)
        self._populate_auto_flow(flow)
        self._commit_flow_edit()

    def new_auto_flow_from_selection(self):
        """gF/panel: auto-flow from the single selected node (box, note or image)."""
        nodes = [i for i in self._scene.selectedItems()
                 if isinstance(i, (BoxItem, NoteItem, ImageItem))]
        if len(nodes) != 1:
            self._record_shortcut("auto-flow: select exactly one node first")
            return None
        item = nodes[0]
        if isinstance(item, BoxItem):
            text = item.box.label
        elif isinstance(item, NoteItem):
            text = item.note.text
        else:  # ImageItem has no text — name the flow after the image file
            text = Path(item.image.image_path).stem
        label = (text.replace("\n", " ").strip() or "Auto flow")[:60]
        return self.create_auto_flow(self._item_id(item), label)

    def delete_flow(self, flow):
        if not self._board or flow is None:
            return
        if self._recording_flow is flow:
            self._recording_flow = None
        if self._active_flow is flow:
            self._active_flow = None
            self._active_step_index = -1
        self._board.remove_flow(flow)
        self._commit_flow_edit()

    def delete_bookmark(self, bookmark):
        """Delete a bookmark and prune any flow steps that referenced it, so
        no flow is left pointing at a missing stop."""
        if not self._board or bookmark is None:
            return
        for flow in self._board.flows:
            flow.steps = [s for s in flow.steps if s.ref != bookmark.id]
        self._board.remove_bookmark(bookmark)
        self._commit_flow_edit()

    def _set_flow_overlay(self, overlay: dict):
        self._flow_overlay = overlay
        self.viewport().update()

    def _clear_flow_overlay(self):
        self._flow_overlay = None
        self.viewport().update()

    # ── Transient confirmation overlays (flashes) ──

    _FLASH_BLUE = (43, 108, 176)     # bookmark goto confirmation
    _FLASH_RED = (199, 80, 80)       # delete pop

    def _spawn_flash(self, rect: QRectF, *, color, mode: str = "pulse",
                     dur: int = 200):
        """Add a transient overlay easing 0->1 then dropping itself.

        ``mode`` picks the look: ``hold`` (blue bookmark outline that holds
        then fades), ``pulse`` (a quick expanding ring — snap lock-in), or
        ``shrink`` (collapses toward its centre — delete pop).
        """
        if rect is None or rect.isNull():
            return
        entry = {"rect": QRectF(rect), "color": color, "mode": mode, "p": 0.0}
        # Cheap runaway guard: keep the overlay list bounded.
        self._flashes.append(entry)
        if len(self._flashes) > 24:
            del self._flashes[:-24]

        def _set(v):
            entry["p"] = v
            self.viewport().update()

        def _done():
            try:
                self._flashes.remove(entry)
            except ValueError:
                pass
            self.viewport().update()

        self._animate_fade(0.0, 1.0, _set, dur=dur, on_finished=_done)

    def flash_anchor(self, rect: QRectF):
        """Briefly outline a scene rect in blue, fading out — a confirmation
        of what a bookmark frames.
        """
        self._spawn_flash(rect, color=self._FLASH_BLUE, mode="hold", dur=700)

    def _draw_flashes(self, painter: QPainter):
        """Drawn while the painter is still in scene coordinates."""
        if not self._flashes:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for f in self._flashes:
            p = f["p"]
            r, g, b = f["color"]
            mode = f["mode"]
            rect = f["rect"]
            if mode == "hold":
                # Hold full strength briefly, then fade across the back half.
                op = 1.0 if p < 0.35 else max(0.0, 1.0 - (p - 0.35) / 0.65)
                grow, radius = 0.0, 8
            elif mode == "shrink":
                op = max(0.0, 1.0 - p)
                grow, radius = -min(rect.width(), rect.height()) * 0.18 * p, 6
            else:   # pulse
                op = max(0.0, 1.0 - p)
                grow, radius = 4.0 * p, 6
            if op <= 0.0:
                continue
            draw_rect = rect.adjusted(-grow, -grow, grow, grow)
            pen = QPen(QColor(r, g, b, int(220 * op)), 0)
            pen.setCosmetic(True)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(r, g, b, int(36 * op))))
            painter.drawRoundedRect(draw_rect, radius, radius)
        painter.restore()

    # ── Smart alignment guides (live during a single-element drag) ──

    _GUIDE_COLOR = (0, 209, 224)   # vivid cyan — reads as "alignment", not chrome

    def _align_rect_for(self, item, top_left: QPointF | None = None) -> QRectF:
        """The item's content rect in scene coords (excluding selection
        chrome), optionally placed at a candidate top-left ``top_left``."""
        if isinstance(item, BoxItem):
            tl = top_left if top_left is not None else QPointF(
                item.box.x, item.box.y)
            return QRectF(tl.x(), tl.y(), item.box.w, item.box.h)
        if isinstance(item, ImageItem):
            tl = top_left if top_left is not None else QPointF(
                item.image.x, item.image.y)
            return QRectF(tl.x(), tl.y(), item.image.w, item.image.h)
        # NoteItem (and any fallback): derive size from the live bounds and
        # the pos->content offset, so a candidate pos maps to a content rect.
        br = item.sceneBoundingRect()
        if top_left is None:
            return br
        off = br.topLeft() - item.pos()
        return QRectF(top_left + off, br.size())

    def begin_drag_guides(self, item):
        """Gather peer anchor rects once, at drag start (kept cheap by culling
        to a margin around the viewport)."""
        self._drag_lead_item = item
        self._drag_guides = []
        refs: list[dict] = []
        exclude = {item}
        if isinstance(item, BoxItem):
            exclude |= set(self._descendants(item.box.id))
        # Only align to elements actually on screen — no guides reaching out
        # to peers the user can't see. (Small margin so an element flush with
        # an edge still counts.)
        vis = self.mapToScene(self.viewport().rect()).boundingRect()
        vis = vis.adjusted(-8, -8, 8, 8)
        for peer in (*self._box_items.values(), *self._note_items.values(),
                     *self._image_items.values()):
            if peer in exclude or not peer.isVisible():
                continue
            r = self._align_rect_for(peer)
            if not vis.intersects(r):
                continue
            refs.append({
                "rect": r,
                "xs": (r.left(), r.center().x(), r.right()),
                "ys": (r.top(), r.center().y(), r.bottom()),
            })
            if len(refs) >= 200:
                break
        self._drag_guide_refs = refs

    def end_drag_guides(self):
        if self._drag_guide_refs is None and not self._drag_guides:
            return
        self._drag_guide_refs = None
        self._drag_lead_item = None
        if self._drag_guides:
            self._drag_guides = []
            self.viewport().update()

    def snap_drag_pos(self, item, proposed: QPointF) -> QPointF:
        """Single hook for every dragged item: smart-alignment snap (the lead
        item of a single-selection drag) with a grid-snap fallback. Returns the
        position the item should take and records the guide lines to draw."""
        # Child propagation / batch moves must follow the lead faithfully —
        # no snapping of the carried-along items.
        if (getattr(self, "_propagating_move", False)
                or self._suppress_child_updates or self._batch_move_updates):
            return proposed

        sel = [i for i in self._scene.selectedItems()
               if isinstance(i, (BoxItem, NoteItem, ImageItem))]
        align_on = (self._drag_guide_refs and item is self._drag_lead_item
                    and len(sel) <= 1)

        nx, ny = proposed.x(), proposed.y()
        ax_line = ay_line = None
        guides: list[dict] = []
        if align_on:
            rect = self._align_rect_for(item, proposed)
            thr = 6.0 / max(1e-6, abs(self.transform().m11()))
            xs = (rect.left(), rect.center().x(), rect.right())
            ys = (rect.top(), rect.center().y(), rect.bottom())
            best_dx = best_dy = None
            ref_x = ref_y = None
            for ref in self._drag_guide_refs:
                for a in xs:
                    for line in ref["xs"]:
                        d = line - a
                        if abs(d) <= thr and (best_dx is None
                                              or abs(d) < abs(best_dx)):
                            best_dx, ax_line, ref_x = d, line, ref
                for a in ys:
                    for line in ref["ys"]:
                        d = line - a
                        if abs(d) <= thr and (best_dy is None
                                              or abs(d) < abs(best_dy)):
                            best_dy, ay_line, ref_y = d, line, ref
            if best_dx is not None:
                nx += best_dx
            if best_dy is not None:
                ny += best_dy
            snapped = self._align_rect_for(item, QPointF(nx, ny))
            if ax_line is not None:
                r2 = ref_x["rect"]
                guides.append({"orient": "v", "pos": ax_line,
                               "a": min(snapped.top(), r2.top()),
                               "b": max(snapped.bottom(), r2.bottom())})
            if ay_line is not None:
                r2 = ref_y["rect"]
                guides.append({"orient": "h", "pos": ay_line,
                               "a": min(snapped.left(), r2.left()),
                               "b": max(snapped.right(), r2.right())})

        # Grid fallback on any axis alignment didn't already pin.
        if self._grid_snap:
            spacing = self.GRID_SPACING
            if ax_line is None:
                nx = round(nx / spacing) * spacing
            if ay_line is None:
                ny = round(ny / spacing) * spacing

        # The guide lines are the snap feedback; deliberately no timed pulse
        # here — a per-frame animation racing Qt's own full-viewport drag
        # repaints flickers the node it's meant to celebrate.
        if guides != self._drag_guides:
            self._drag_guides = guides
            self.viewport().update()
        return QPointF(nx, ny)

    def _draw_drag_guides(self, painter: QPainter):
        """Drawn while the painter is still in scene coordinates.

        Neon-style: a soft glow halo under a crisp bright core, capped with
        small diamond snap-markers at each end. Everything is static (no timed
        animation) so it never races the drag's full-viewport repaints.
        """
        if not self._drag_guides:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        zoom = max(1e-6, abs(self.transform().m11()))
        cap = 4.0 / zoom   # marker half-size in scene units -> ~constant px
        r, g, b = self._GUIDE_COLOR
        halo = QPen(QColor(r, g, b, 70), 0)
        halo.setCosmetic(True)
        halo.setWidth(6)
        halo.setCapStyle(Qt.PenCapStyle.RoundCap)
        core = QPen(QColor(r, g, b, 245), 0)
        core.setCosmetic(True)
        core.setWidthF(1.6)
        core.setCapStyle(Qt.PenCapStyle.RoundCap)
        for guide in self._drag_guides:
            pos, a, bb = guide["pos"], guide["a"], guide["b"]
            if guide["orient"] == "v":
                p1, p2 = QPointF(pos, a), QPointF(pos, bb)
            else:
                p1, p2 = QPointF(a, pos), QPointF(bb, pos)
            painter.setPen(halo)
            painter.drawLine(p1, p2)
            painter.setPen(core)
            painter.drawLine(p1, p2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(r, g, b, 245)))
            for p in (p1, p2):
                painter.drawPolygon(QPolygonF([
                    QPointF(p.x(), p.y() - cap), QPointF(p.x() + cap, p.y()),
                    QPointF(p.x(), p.y() + cap), QPointF(p.x() - cap, p.y())]))
        painter.restore()

    def _draw_flow_overlay(self, painter: QPainter):
        """Recording badge (top-right) and playback caption (bottom-center).

        Drawn in viewport coordinates so it stays fixed while the scene
        pans and zooms underneath.
        """
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        vp = self.viewport().rect()

        if self._recording_flow is not None:
            n = len(self._recording_flow.steps)
            text = f"● REC  {self._recording_flow.label}  ·  {n}"
            font = QFont(FONT_FAMILY, 11)
            painter.setFont(font)
            fm = painter.fontMetrics()
            pad = 8
            w = fm.horizontalAdvance(text) + pad * 2
            h = fm.height() + pad
            x = vp.width() - w - 12
            y = 12
            bg = QColor("#7A1F1F")
            bg.setAlphaF(0.92)
            painter.setPen(QPen(QColor(255, 255, 255, 50), 1))
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(QPointF(x + pad, y + pad / 2 + fm.ascent()), text)

        ov = self._flow_overlay
        if ov is not None:
            title = f"{ov['index'] + 1}/{ov['total']}"
            if ov["label"]:
                title += f"  ·  {ov['label']}"
            transition = "smooth" if ov["smooth"] else "instant"
            play = {"paused": "paused", "playing": "playing",
                    "loop": "playing ⟳"}.get(ov.get("mode", "paused"), "paused")
            hint = (f"Space/→ next · ← prev · "
                    f"t:{transition} · p:{play} · Esc exit")

            title_font = QFont(FONT_FAMILY, 14, QFont.Weight.Bold)
            desc_font = QFont(FONT_FAMILY, 11)
            hint_font = QFont(FONT_FAMILY, 9)

            pad = 12
            gap = 5
            max_w = min(640, vp.width() - 40)

            painter.setFont(title_font)
            tfm = painter.fontMetrics()
            title_disp = tfm.elidedText(title, Qt.TextElideMode.ElideRight, max_w)
            title_w = tfm.horizontalAdvance(title_disp)
            title_h = tfm.height()

            painter.setFont(desc_font)
            dfm = painter.fontMetrics()
            desc = ov["description"] or ""
            desc_disp = dfm.elidedText(desc, Qt.TextElideMode.ElideRight, max_w) if desc else ""
            desc_w = dfm.horizontalAdvance(desc_disp) if desc_disp else 0
            desc_h = dfm.height() if desc_disp else 0

            painter.setFont(hint_font)
            hfm = painter.fontMetrics()
            hint_w = hfm.horizontalAdvance(hint)
            hint_h = hfm.height()

            content_w = max(title_w, desc_w, hint_w)
            panel_w = content_w + pad * 2
            panel_h = title_h + (gap + desc_h if desc_disp else 0) + gap + hint_h + pad * 2
            panel_x = (vp.width() - panel_w) / 2
            panel_y = vp.height() - panel_h - 20

            bg = QColor("#2F3437")
            bg.setAlphaF(0.94)
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
            painter.setBrush(QBrush(bg))
            painter.drawRoundedRect(QRectF(panel_x, panel_y, panel_w, panel_h), 8, 8)

            cy = panel_y + pad
            painter.setFont(title_font)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(QPointF(panel_x + pad, cy + tfm.ascent()), title_disp)
            cy += title_h
            if desc_disp:
                cy += gap
                painter.setFont(desc_font)
                painter.setPen(QPen(QColor(220, 220, 220)))
                painter.drawText(QPointF(panel_x + pad, cy + dfm.ascent()), desc_disp)
                cy += desc_h
            cy += gap
            painter.setFont(hint_font)
            painter.setPen(QPen(QColor(150, 150, 150)))
            painter.drawText(QPointF(panel_x + pad, cy + hfm.ascent()), hint)

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

    # ── Toast (transient action feedback) ──

    def toast(self, text: str, kind: str = "info"):
        """Show a transient HUD pill confirming an action.

        ``info``/``warn`` auto-clear after a couple of seconds; ``error`` sticks
        until the next toast so a failure can't scroll past unseen.
        """
        self._toast_text = text
        self._toast_kind = kind
        if self._toast_timer is not None:
            self._toast_timer.stop()
            self._toast_timer = None
        if kind != "error":
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(2400)
            timer.timeout.connect(self._clear_toast)
            timer.start()
            self._toast_timer = timer
        self.viewport().update()

    def _clear_toast(self):
        self._toast_text = ""
        self._toast_timer = None
        self.viewport().update()

    # ── Fade helper (premium micro-motion for transient overlays) ──

    def _animate_fade(self, start, end, setter, dur: int = 110,
                      on_finished=None):
        """Ease ``setter`` from ``start`` to ``end`` over ``dur`` ms (OutCubic).

        The animation is held in ``_fade_anims`` so Qt doesn't garbage-collect it
        mid-flight, and removed on completion.
        """
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(dur)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: setter(float(v)))

        def _done():
            if on_finished is not None:
                on_finished()
            self._fade_anims.discard(anim)

        anim.finished.connect(_done)
        self._fade_anims.add(anim)
        anim.start()
        return anim

    def _animate_scale(self, items, start, end, dur: int = 160):
        """Ease ``setScale`` from ``start`` to ``end`` over ``dur`` ms with an
        OutBack overshoot — a subtle 'pop' about each item's own centre."""
        live = []
        for it in items:
            try:
                it.setTransformOriginPoint(it.boundingRect().center())
                it.setScale(start)
                live.append(it)
            except RuntimeError:
                pass
        if not live:
            return

        def _set(v):
            for it in live:
                try:
                    it.setScale(v)
                except RuntimeError:
                    pass
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(dur)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)
        anim.valueChanged.connect(lambda v: _set(float(v)))
        anim.finished.connect(lambda: self._fade_anims.discard(anim))
        self._fade_anims.add(anim)
        anim.start()
        return anim

    def _draw_toast(self, painter: QPainter):
        if not self._toast_text:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        is_error = self._toast_kind == "error"
        is_warn = self._toast_kind == "warn"
        glyph = "⚠" if (is_error or is_warn) else "✓"  # ⚠ / ✓
        text = f"{glyph}  {self._toast_text}"

        font = QFont(FONT_FAMILY, 11)
        painter.setFont(font)
        fm = painter.fontMetrics()
        pad_x, pad_y = 14, 8
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        rw = tw + pad_x * 2
        rh = th + pad_y * 2
        vp = self.viewport().rect()
        rx = (vp.width() - rw) / 2
        ry = vp.height() - rh - 24

        bg = QColor("#2F3437")
        bg.setAlphaF(0.94)
        accent = QColor("#C75050") if is_error else (
            QColor("#D4BA6A") if is_warn else QColor("#6BAA8A"))
        painter.setPen(QPen(accent, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 8, 8)
        # Border carries the status color; text stays near-white for readability.
        painter.setPen(QPen(QColor(255, 255, 255, 235)))
        painter.drawText(QRectF(rx, ry, rw, rh), Qt.AlignmentFlag.AlignCenter,
                         text)
        painter.restore()

    # ── Debug overlay ──

    def _record_shortcut(self, label: str):
        """Record a shortcut label for the debug overlay."""
        self._debug_last_shortcut = label
        if self._debug_fade_timer is not None:
            self._debug_fade_timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(1500)
        timer.timeout.connect(self._clear_debug_overlay)
        timer.start()
        self._debug_fade_timer = timer
        self.viewport().update()

    def _clear_debug_overlay(self):
        self._debug_last_shortcut = ""
        self._debug_fade_timer = None
        self.viewport().update()

    def _draw_debug_overlay(self, painter: QPainter):
        if not self._debug_last_shortcut:
            return
        if not self._debug_overlay and not self._debug_last_shortcut.startswith("DEBUG"):
            return
        painter.resetTransform()
        font = QFont(FONT_FAMILY, 11)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text = self._debug_last_shortcut
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad_x, pad_y = 12, 6
        rx = MINIMAP_MARGIN
        ry = MINIMAP_MARGIN
        rw = tw + pad_x * 2
        rh = th + pad_y * 2
        bg = QColor(30, 30, 30, 180)
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(rx, ry, rw, rh), 8, 8)
        painter.setPen(QPen(QColor(255, 255, 255, 220)))
        painter.drawText(
            QRectF(rx, ry, rw, rh),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    # ── Glyph picker ──

    def _open_glyph_picker(self):
        picker = GlyphPicker(self.viewport())
        vp = self.viewport().rect()
        pw = 420
        ph = 460

        # Position near the active item
        anchor = None
        if self._editor and self._editor.parentItem():
            anchor = self._editor.parentItem()
        else:
            sel = self._scene.selectedItems()
            if sel:
                anchor = sel[0]

        if anchor is not None:
            item_rect = self.mapFromScene(anchor.sceneBoundingRect()).boundingRect()
            px = item_rect.center().x() - pw // 2
            py = item_rect.top() - ph - 8
            if py < 0:
                py = item_rect.bottom() + 8
        else:
            px = (vp.width() - pw) // 2
            py = 60

        px = max(0, min(px, vp.width() - pw))
        py = max(0, min(py, vp.height() - ph))
        picker.move(self.viewport().mapToGlobal(QPoint(int(px), int(py))))

        picker.glyph_selected.connect(self._insert_glyph)
        picker.show()

    def _insert_glyph(self, char: str):
        if self._editor:
            char = ensure_text_presentation(char)
            cursor = self._editor.textCursor()
            cursor.insertText(char)
            self._editor.setTextCursor(cursor)
            self._editor.setFocus()

    # ── Export (SVG file / PNG clipboard) ──

    @contextmanager
    def _export_scene_context(self, padding: int = 20):
        """Prepare the scene for clean export, yield the padded bounding rect.

        Hides unselected items when there is a selection, clears selection
        decorations, and hides the mode badge.  Restores everything on exit.
        """
        selected = [
            i for i in self._scene.selectedItems()
            if isinstance(i, (BoxItem, NoteItem, ImageItem))
        ]
        selected_ids: set[str] = set()
        for item in selected:
            if isinstance(item, BoxItem):
                selected_ids.add(item.box.id)
            elif isinstance(item, NoteItem):
                selected_ids.add(item.note.id)
            elif isinstance(item, ImageItem):
                selected_ids.add(item.image.id)

        hidden: list[QGraphicsItem] = []
        was_selected: list[QGraphicsItem] = []
        badge_items: list[QGraphicsItem] = []

        if selected_ids:
            for item in self._scene.items():
                keep = False
                if isinstance(item, (BoxItem, NoteItem, ImageItem)):
                    eid = ""
                    if isinstance(item, BoxItem):
                        eid = item.box.id
                    elif isinstance(item, NoteItem):
                        eid = item.note.id
                    elif isinstance(item, ImageItem):
                        eid = item.image.id
                    keep = eid in selected_ids
                elif isinstance(item, BoxLabelItem):
                    keep = (isinstance(item._box_item, BoxItem)
                            and item._box_item.box.id in selected_ids)
                elif isinstance(item, ResizeHandle):
                    keep = False
                else:
                    arrow = item.data(0)
                    if hasattr(arrow, "from_id") and hasattr(arrow, "to_id"):
                        keep = (arrow.from_id in selected_ids
                                and arrow.to_id in selected_ids)
                if not keep and item.isVisible():
                    item.setVisible(False)
                    hidden.append(item)

        for item in self._scene.selectedItems():
            item.setSelected(False)
            was_selected.append(item)

        if self._mode_badge:
            badge_items.append(self._mode_badge)
            self._mode_badge.setVisible(False)
        if self._mode_badge_bg:
            badge_items.append(self._mode_badge_bg)
            self._mode_badge_bg.setVisible(False)

        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            rect = QRectF(0, 0, 100, 100)
        rect = rect.adjusted(-padding, -padding, padding, padding)

        try:
            yield rect
        finally:
            for item in hidden:
                item.setVisible(True)
            for item in was_selected:
                item.setSelected(True)
            for item in badge_items:
                item.setVisible(True)

    def _render_svg_bytes(self, padding: int = 20) -> QByteArray:
        """Render the current diagram (or selection) to SVG bytes."""
        with self._export_scene_context(padding=padding) as rect:
            buf = QByteArray()
            io = QBuffer(buf)
            io.open(QIODevice.OpenModeFlag.WriteOnly)
            gen = QSvgGenerator()
            gen.setOutputDevice(io)
            gen.setSize(rect.size().toSize())
            gen.setViewBox(rect)
            gen.setTitle("Grafli Diagram")
            painter = QPainter(gen)
            painter.fillRect(rect, QBrush(SCENE_BG))
            self._scene.render(painter, QRectF(), rect)
            painter.end()
            io.close()
        return buf

    def _render_png_image(self, scale: int = 2, padding: int = 20) -> QImage:
        """Render the current diagram (or selection) to a QImage."""
        with self._export_scene_context(padding=padding) as rect:
            size = rect.size().toSize()
            image = QImage(
                size.width() * scale,
                size.height() * scale,
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.fill(SCENE_BG)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            # Always render against an explicit pixel target. Setting DPR
            # before render() with a null target makes Qt drop most of the
            # scene for certain aspect ratios (wide-and-short pipelines).
            self._scene.render(
                painter,
                QRectF(0, 0, image.width(), image.height()),
                rect,
            )
            painter.end()
            image.setDevicePixelRatio(scale)
        return image

    def _render_png_to_path(
        self, path, padding: int = 20, width: int | None = None,
    ) -> None:
        """Render the current diagram to a PNG file at *path*.

        If *width* is given, the output is scaled to that width while
        preserving aspect ratio. Otherwise the natural 2× scale is used.
        """
        from PySide6.QtCore import Qt as _Qt
        image = self._render_png_image(padding=padding)
        if width is not None and width > 0:
            image = image.scaledToWidth(
                width, _Qt.TransformationMode.SmoothTransformation,
            )
            image.setDevicePixelRatio(1.0)
        image.save(str(path), "PNG")

    def _yank_png_to_clipboard(self):
        """Copy the diagram as PNG to the system clipboard."""
        try:
            image = self._render_png_image()
            QApplication.clipboard().setImage(image)
        except Exception as exc:
            self.toast(f"PNG copy failed: {exc}", "error")
            return
        self.toast("PNG copied to clipboard")

    def _export_svg_file(self):
        """Export the diagram as an SVG file."""
        default_name = ""
        window = self.window()
        if hasattr(window, "_file_path") and window._file_path:
            from pathlib import Path
            default_name = str(Path(window._file_path).with_suffix(".svg"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", default_name,
            "SVG files (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            svg_bytes = self._render_svg_bytes()
            with open(path, "wb") as f:
                f.write(svg_bytes.data())
        except Exception as exc:
            self.toast(f"SVG export failed: {exc}", "error")
            return
        self.toast(f"SVG exported · {Path(path).name}")

    # ── Cheatsheet (Shift+H) ──

    def _show_cheatsheet(self):
        groups = [
            ("File", [
                ("\u2318N", "New file"),
                ("\u2318O", "Open file"),
                ("\u2318S", "Save file"),
                ("\u2318Q", "Quit"),
            ]),
            ("Modes", [
                ("V", "Select mode"),
                ("N", "Create node (\u21e7click stays in mode)"),
                ("T", "Create note (\u21e7click stays in mode)"),
                ("C", "Connect arrow (one-shot)"),
            ]),
            ("Navigate", [
                ("Arrow keys", "Pan viewport"),
                ("Middle/Right-drag", "Pan anywhere"),
                ("+ / -", "Zoom in / out"),
                ("z", "Zoom in: 25 → 50 → 100 → 150 % (cycle)"),
                ("⇧Z", "Zoom to fit (whole graph)"),
                ("gz", "Focus: zoom to selection ⇄ back"),
                ("gp", "Select parent (zoom if needed)"),
                ("gc", "Select first child"),
                ("Tab / \u21e7Tab", "Cycle siblings (or search matches)"),
                ("f / Ctrl+J", "Jump to any item (global)"),
                ("Ctrl+O / Ctrl+I", "Nav history back / forward"),
                ("Alt (hold)", "Graph nav: follow connectors"),
                ("/", "Search dim-filter \u2014 Tab/\u21e7Tab cycle, Esc clears"),
            ]),
            ("Edit", [
                ("e / Dbl-click", "Edit selected element (inline)"),
                ("E", "Zen editor — note text / box-image markdown"),
                ("W", "Set URL on selected item"),
                ("Return", "Open URL in browser"),
                ("Enter", "Accept edit"),
                ("y / p", "Yank / Paste"),
                ("u / \u2318Z", "Undo"),
                ("Ctrl+R / \u2318\u21e7Z", "Redo"),
                ("x / Delete", "Delete selected / arrow"),
                ("Ctrl+G", "Insert glyph (while editing)"),
            ]),
            ("Create", [
                ("o / O", "Create box below / above"),
                ("Ctrl+Arrow", "Create adjacent box"),
                ("Ctrl+G", "Encapsulate selection in a new parent box"),
                ("Alt+Drag", "Connect nodes — boxes, notes, images (from SELECT)"),
                ("Alt+Click", "Paste at position"),
            ]),
            ("Notes", [
                ("Drag right edge", "Resize note wrap width (persists as ~width=N)"),
                ("Default wrap", "80 chars — set ~width=N for per-note override"),
            ]),
            ("Style", [
                ("s", "Style mode — then:"),
                ("  c", "Color grid (hjkl pick, live, ⏎ apply)"),
                ("  i", "Icon grid (visual vocab; ⇥ fill/lead)"),
                ("  t", "Text grid: size × bold/italic (⇥ font, o outline, s shadow)"),
                ("  j / k", "Nudge text size"),
                ("  d", "Dimension mode (resize)"),
                ("d then r", "Snap box(es) to the slide aspect ratio (export frame)"),
                ("Drag corner", "Scale the selection (size + font); Shift keeps ratio"),
                ("Shift+G", "Snap to grid"),
                ("=", "Auto-layout selection (or all)"),
            ]),
            ("Focus & Analysis", [
                (",", "Dim arrows"),
                ("\u21e7N", "Dim notes \u2014 concentrate on the graph"),
                ("A", "Complexity analysis heatmap"),
                ("B", "Subgraph focus (cycle direction)"),
                ("\u21e7B", "Toggle focus depth (full/1-hop)"),
            ]),
            ("View", [
                ("#", "Toggle grid"),
                ("M", "Toggle minimap"),
                ("\\", "Toggle tools panel"),
            ]),
            ("Bookmarks & Flows", [
                ("gb", "Bookmark what's shown (logical)"),
                ("Select + gb", "Scope step to selection"),
                ("1 note + gb, no caption", "Text slide (clickable links)"),
                ("gB", "Bookmark exact viewport"),
                ("gf", "Start / stop flow recording"),
                ("gF", "Auto-flow: walk forward arrows from selected node"),
                ("Flows tab (\\)", "Edit flows: reorder, add/remove, dwell, re-generate (↻)"),
                ("Select step + gb", "Insert new bookmark after it"),
                ("Space / →", "Next stop (during playback)"),
                ("←", "Previous stop"),
                ("t", "Toggle smooth / instant"),
                ("p", "Cycle paused / playing / loop"),
                ("F5", "Present flow fullscreen"),
                ("Esc", "Exit playback / present"),
            ]),
            ("Export", [
                ("Y", "Yank diagram as PNG to clipboard"),
                ("Ctrl+E", "Export SVG to file"),
            ]),
            ("Arrow", [
                ("e", "Edit arrow label"),
                ("s", "Enter arrow style mode"),
                ("h / l", "Toggle arrowheads"),
                ("j / k", "Arrow label size"),
                ("\u21e7J / \u21e7K", "Cycle arrow style"),
                ("s then a", "Toggle connector kind: graph edge \u21c4 annotation"),
            ]),
            ("Buffers", [
                ("Ctrl+K", "Open / switch buffer"),
                ("Ctrl+6", "Toggle last buffer"),
                ("Q", "Close buffer (no selection)"),
            ]),
            ("Other", [
                ("Shift+Click", "Toggle selection"),
                ("Click @ref", "Open source from code-mode note"),
                ("F1", "This cheatsheet"),
                ("`", "Toggle debug overlay"),
                ("Escape", "Cancel / back to SELECT"),
            ]),
        ]

        columns = [
            ["File", "Modes", "Navigate"],
            ["Edit", "Create", "Focus & Analysis", "View", "Bookmarks & Flows"],
            ["Style", "Arrow", "Export", "Buffers", "Other"],
        ]
        group_map = {name: entries for name, entries in groups}

        hdr = (
            "color:#6A9FB5;font-weight:bold;"
            "padding-top:8px;padding-bottom:2px"
        )

        def _render_html(filter_text: str) -> str:
            ft = filter_text.lower()

            def _render_column(group_names):
                rows = []
                for name in group_names:
                    entries = group_map[name]
                    if ft:
                        entries = [
                            (k, d) for k, d in entries
                            if ft in k.lower() or ft in d.lower()
                        ]
                    if not entries:
                        continue
                    rows.append(
                        f"<tr><td colspan='2' style='{hdr}'>"
                        f"{name.upper()}</td></tr>"
                    )
                    for key, desc in entries:
                        rows.append(
                            f"<tr>"
                            f"<td style='padding-right:12px;"
                            f"white-space:nowrap'>"
                            f"<b>{key}</b></td>"
                            f"<td style='padding:2px 0'>{desc}</td>"
                            f"</tr>"
                        )
                return f"<table cellpadding='2'>{''.join(rows)}</table>"

            col_html = (
                "</td><td width='24'></td><td valign='top'>".join(
                    _render_column(col) for col in columns
                )
            )
            return (
                "<table><tr>"
                f"<td valign='top'>{col_html}</td>"
                "</tr></table>"
            )

        dlg = QDialog(self)
        dlg.setWindowTitle("Help")

        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            w = min(900, int(geo.width() * 0.75))
            h = int(geo.height() * 0.70)
        else:
            w, h = 900, 600
        dlg.resize(w, h)

        tabs = QTabWidget(dlg)
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #6A9FB5; background: #2A2A2A; }"
            " QTabBar::tab { background: #2A2A2A; color: #E0E0E0;"
            " padding: 6px 14px; border: 1px solid #444; }"
            " QTabBar::tab:selected { background: #3A3A3A;"
            " border-bottom-color: #6A9FB5; }"
        )

        # ── Tab 1: shortcuts ──
        shortcuts_tab = QWidget(tabs)
        filter_input = QLineEdit(shortcuts_tab)
        filter_input.setPlaceholderText("Type to filter shortcuts\u2026")
        filter_input.setStyleSheet(
            "QLineEdit { background: #2A2A2A; color: #E0E0E0;"
            " border: 1px solid #6A9FB5; padding: 4px; }"
        )
        browser = QTextBrowser(shortcuts_tab)
        browser.setOpenLinks(False)
        font = browser.font()
        font.setPointSize(13)
        browser.setFont(font)
        browser.setStyleSheet(
            "QTextBrowser { background: #2A2A2A; color: #E0E0E0; border: none; }"
        )
        browser.setHtml(_render_html(""))
        filter_input.textChanged.connect(
            lambda t: browser.setHtml(_render_html(t))
        )
        sc_layout = QVBoxLayout(shortcuts_tab)
        sc_layout.addWidget(filter_input)
        sc_layout.addWidget(browser, 1)
        tabs.addTab(shortcuts_tab, "Shortcuts")

        # ── Tab 2: text annotation formats ──
        notes_browser = QTextBrowser(tabs)
        notes_browser.setOpenLinks(False)
        notes_browser.setFont(font)
        notes_browser.setStyleSheet(
            "QTextBrowser { background: #2A2A2A; color: #E0E0E0; border: none;"
            " padding: 8px; }"
        )
        notes_browser.setHtml(self._notes_help_html())
        tabs.addTab(notes_browser, "Text Annotations")

        # ── Tab 3: markdown editor ──
        md_browser = QTextBrowser(tabs)
        md_browser.setOpenLinks(False)
        md_browser.setFont(font)
        md_browser.setStyleSheet(
            "QTextBrowser { background: #2A2A2A; color: #E0E0E0; border: none;"
            " padding: 8px; }"
        )
        md_browser.setHtml(self._md_editor_help_html())
        tabs.addTab(md_browser, "Markdown Editor")

        btn = QPushButton("Close", dlg)
        btn.clicked.connect(dlg.accept)

        layout = QVBoxLayout(dlg)
        layout.addWidget(tabs, 1)
        layout.addWidget(btn)

        filter_input.setFocus()
        dlg.exec()

    def _notes_help_html(self) -> str:
        hdr = (
            "color:#6A9FB5;font-weight:bold;"
            "padding-top:10px;padding-bottom:4px"
        )
        kw = "color:#6A9FB5;font-weight:bold"
        code_bg = (
            "background:#1E1E1E;color:#E0E0E0;padding:8px;"
            "font-family:monospace;white-space:pre;display:block;"
            "border-left:3px solid #6A9FB5"
        )
        mono = "font-family:monospace"
        dim = "color:#B8B3AB"
        kw_blue = "color:#2B6CB0;font-weight:bold"
        kw_red = "color:#C53030;font-weight:bold"
        return f"""
        <p style='{hdr}'>TEXT ANNOTATIONS</p>
        <p>Grafli text can annotate nodes, edges, and local logic. Edit mode
        always shows the raw text; display mode adds visual treatment for the
        conventions below.</p>

        <p style='{hdr}'>Informational &mdash; plain text</p>
        <p>Default note. Blue text on a light badge-style background.</p>

        <p style='{hdr}'>Task &mdash; <span style='{mono}'>T:</span> /
           <span style='{mono}'>TODO:</span></p>
        <p>Red badge + body. Also accepts <span style='{mono}'>t:</span> /
        <span style='{mono}'>todo:</span> &mdash; case-insensitive. The
        rendered badge is normalised to <span style='{mono}'>T:</span>.
        Use for todos that an agent can act on.</p>

        <p style='{hdr}'>Question &mdash; <span style='{mono}'>Q:</span> /
           <span style='{mono}'>QUESTION:</span></p>
        <p>Purple badge + body. Also accepts <span style='{mono}'>q:</span> /
        <span style='{mono}'>question:</span>. Normalised to
        <span style='{mono}'>Q:</span>. Use for questions an agent can
        answer inline.</p>

        <p style='{hdr}'>Discussion &mdash;
           <span style='{mono}'>Alice: &hellip; \\n Bob: &hellip;</span></p>
        <p>Two or more speakers render as a threaded conversation with
        per-speaker colored badges. A speaker prefix is a name that starts
        with an uppercase letter, 1&ndash;16 chars of letters/digits/<span
        style='{mono}'>_</span>/<span style='{mono}'>-</span>, followed by
        <span style='{mono}'>:</span> and a space.</p>

        <p style='{hdr}'>Code &mdash; <span style='{mono}'>code:</span></p>
        <p>A note whose first non-empty line is
        <span style='{mono}'>code:</span> renders as a stylized pseudocode
        block. The pseudocode is <b>not</b> real source code &mdash; it's a
        minimal language for summarizing implementations at a glance.</p>
        <ul>
          <li><b>First body line is the function signature</b> &mdash;
              rendered bold with a divider rule beneath.</li>
          <li><b>Indentation carries block structure</b> (2 spaces per
              level). Indent guides are drawn automatically.</li>
          <li>Trailing <span style='{mono}'>:</span> on keywords is
              optional &mdash; <span style='{mono}'>if cond</span> and
              <span style='{mono}'>if: cond</span> render the same.</li>
          <li>Plain assignments need no keyword:
              <span style='{mono}'>out = []</span>.</li>
        </ul>

        <p style='{kw_blue}'>Flow keywords (blue, bold)</p>
        <table cellpadding='4' style='margin-left:8px'>
          <tr><td style='{mono}'>if</td><td>condition</td></tr>
          <tr><td style='{mono}'>else</td><td>alternative branch</td></tr>
          <tr><td style='{mono}'>for</td>
              <td>iteration &mdash;
                  <span style='{mono}'>for x in xs</span></td></tr>
          <tr><td style='{mono}'>while</td><td>loop</td></tr>
          <tr><td style='{mono}'>try</td><td>protected block</td></tr>
          <tr><td style='{mono}'>catch</td><td>error handling</td></tr>
          <tr><td style='{mono}'>return</td><td>exit value</td></tr>
          <tr><td style='{mono}'>call</td><td>important call</td></tr>
          <tr><td style='{mono}'>await</td><td>async wait / blocking op</td></tr>
          <tr><td style='{mono}'>emit</td><td>event / message emission</td></tr>
          <tr><td style='{mono}'>state</td><td>state transition (<span style='{mono}'>from -&gt; to</span>)</td></tr>
        </table>

        <p style='{kw_red}'>Contract keywords (red, bold) &mdash; reviewer&rsquo;s eye lands here first</p>
        <table cellpadding='4' style='margin-left:8px'>
          <tr><td style='{mono}'>pre</td><td>precondition</td></tr>
          <tr><td style='{mono}'>post</td><td>postcondition</td></tr>
          <tr><td style='{mono}'>assert</td><td>invariant / expected fact</td></tr>
          <tr><td style='{mono}'>verify</td><td>test / trace that proves behavior</td></tr>
          <tr><td style='{mono}'>risk</td><td>failure mode / review risk</td></tr>
          <tr><td style='{mono}'>err</td><td>error / raise</td></tr>
        </table>

        <p style='{kw}'>Inline elements</p>
        <table cellpadding='4' style='margin-left:8px'>
          <tr><td style='{mono}'>@path:line</td>
              <td>clickable reference &mdash; opens the file at that line in your editor</td></tr>
          <tr><td style='{mono}'># &hellip;</td>
              <td>comment (italic, muted)</td></tr>
          <tr><td style='{mono}'>"..."  #FFF  42  true</td>
              <td>literal values render as plain text</td></tr>
        </table>

        <p style='{kw}'>Example</p>
        <div style='{code_bg}'>code:
tokenize(raw) -&gt; [Token]
if raw.len &gt; MAX:
  err too-long
out = []
for ch in raw:
  # skip whitespace
  out += make_tok(ch)
return out  @parser.py:44</div>

        <p style='{dim}'>Style guidance: prefer short predicates and named
        operations over long OO chains
        (<span style='{mono}'>blank(line)</span> reads faster than
        <span style='{mono}'>line.stripped.isEmpty</span>) &mdash; the
        snippet should reveal <i>what happens</i>, not literally mirror
        the source.</p>

        <p style='{hdr}'>Edge Labels &mdash; relationship kinds</p>
        <p>Arrow labels can start with a relationship kind such as
        <span style='{mono}'>data: payload</span>,
        <span style='{mono}'>call: validate()</span>, or
        <span style='{mono}'>step: 1</span>. Known prefixes color the edge and
        render as small chips beside the remaining label text. The raw label
        stays directly editable with <span style='{mono}'>e</span>. Supported kinds:
        <span style='{mono}'>call</span>, <span style='{mono}'>data</span>,
        <span style='{mono}'>event</span>, <span style='{mono}'>state</span>,
        <span style='{mono}'>step</span>, <span style='{mono}'>verify</span>,
        <span style='{mono}'>owns</span>, <span style='{mono}'>depends</span>,
        <span style='{mono}'>risk</span>, <span style='{mono}'>note</span>.</p>

        <p style='{hdr}'>Block Text</p>
        <p>Notes can use triple-quoted text in the file format when the text
        contains quotes or should stay readable across multiple lines. In the
        canvas this is still just an ordinary editable note.</p>
        """

    def _md_editor_help_html(self) -> str:
        hdr = (
            "color:#6A9FB5;font-weight:bold;"
            "padding-top:10px;padding-bottom:4px"
        )
        kw = "color:#6A9FB5;font-weight:bold"
        mono = "font-family:monospace"
        cell = "padding:4px 8px;vertical-align:top"
        key_cell = (
            "padding:4px 8px;font-family:monospace;"
            "white-space:nowrap;vertical-align:top"
        )
        return f"""
        <p style='{hdr}'>MARKDOWN EDITOR (ZEN MODE)</p>
        <p>Opens when you follow a link to a local <span style='{mono}'>.md</span>
        file from a node URL, or when you edit an annotation. Pure text, no
        chrome &mdash; the shortcuts below are the controls. Files open
        read-only so browsing never edits by accident; toggle with
        <b>Ctrl+W</b>. Annotation edits start in write mode.</p>

        <p style='{kw}'>Session</p>
        <table cellpadding='2' style='margin-left:8px'>
          <tr><td style='{key_cell}'>Esc</td>
              <td style='{cell}'>Save &amp; close
                  (annotation mode emits the new text; file mode just
                  closes &mdash; writes happen via autosave).</td></tr>
          <tr><td style='{key_cell}'>Shift+Esc</td>
              <td style='{cell}'>Cancel &mdash; discard pending changes
                  in annotation mode.</td></tr>
          <tr><td style='{key_cell}'>Ctrl+W</td>
              <td style='{cell}'>Toggle read-only / write
                  (file mode only). Write mode autosaves after 500&nbsp;ms
                  of idle typing; read-only re-attaches the file watcher
                  so external edits reload.</td></tr>
          <tr><td style='{key_cell}'>Ctrl+P</td>
              <td style='{cell}'>Open the native print dialog.</td></tr>
          <tr><td style='{key_cell}'>Ctrl++ / Ctrl+- / Ctrl+0</td>
              <td style='{cell}'>Bigger / smaller / reset font size
                  (persists across sessions).</td></tr>
          <tr><td style='{key_cell}'>Ctrl+J</td>
              <td style='{cell}'>Activate word-jump overlay
                  (Easymotion-style two-key jump to any visible word).</td></tr>
        </table>

        <p style='{kw}'>Vim Motion (NORMAL mode)</p>
        <table cellpadding='2' style='margin-left:8px'>
          <tr><td style='{key_cell}'>h j k l</td>
              <td style='{cell}'>Left / down / up / right.</td></tr>
          <tr><td style='{key_cell}'>w / b / e</td>
              <td style='{cell}'>Next word start / previous word /
                  word end.</td></tr>
          <tr><td style='{key_cell}'>0 / $</td>
              <td style='{cell}'>Line start / line end.</td></tr>
          <tr><td style='{key_cell}'>gg / G</td>
              <td style='{cell}'>Document start / end.</td></tr>
        </table>

        <p style='{kw}'>Entering INSERT mode</p>
        <table cellpadding='2' style='margin-left:8px'>
          <tr><td style='{key_cell}'>i / a</td>
              <td style='{cell}'>Insert before / after the cursor.</td></tr>
          <tr><td style='{key_cell}'>I / A</td>
              <td style='{cell}'>Insert at line start / line end.</td></tr>
          <tr><td style='{key_cell}'>o / O</td>
              <td style='{cell}'>Open new line below / above.</td></tr>
          <tr><td style='{key_cell}'>Esc</td>
              <td style='{cell}'>Back to NORMAL mode
                  (cursor steps left, vim convention).</td></tr>
        </table>

        <p style='{kw}'>Edits (NORMAL mode)</p>
        <table cellpadding='2' style='margin-left:8px'>
          <tr><td style='{key_cell}'>x</td>
              <td style='{cell}'>Delete character under cursor.</td></tr>
          <tr><td style='{key_cell}'>dd</td>
              <td style='{cell}'>Delete line.</td></tr>
          <tr><td style='{key_cell}'>dw</td>
              <td style='{cell}'>Delete to next word.</td></tr>
        </table>

        <p style='{kw}'>Display</p>
        <p>iA Writer-inspired: the current paragraph stays at full opacity,
        surrounding text is muted to keep focus on what you're writing.
        Headings, lists, links, inline <span style='{mono}'>code</span>,
        and code fences get light syntax highlighting; muted in read-only
        mode (no focus paragraph) so the whole document reads as one piece.</p>

        <p style='{kw}'>Layout</p>
        <p>The editor opens as a centered modal card with a drop shadow.
        The dim wash falls over grafli's chrome (toolbars, side panel,
        minimap) but spares the graph canvas, so the diagram you're
        annotating stays fully saturated behind the card. The card holds
        just the text &mdash; no title, no hint bar, no badges. Card width
        hugs the text column (max ≈700&nbsp;px).</p>
        """

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
