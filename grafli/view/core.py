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
    QEvent,
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
from grafli.view.commands import CommandsMixin
from grafli.view.complexity import ComplexityMixin
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
from grafli.format import MAX_DESCRIPTION_CHARS, Arrow, Board, Bookmark, Box, Flow, FlowStep, Image, Note, emphasis_from_flags, parse, serialize
from grafli.flows import FlowPlayer
from grafli.glyphs import GlyphPicker, ensure_text_presentation
from grafli.iconset import ICON_NAMES, icon_pixmap
from grafli.items import ArrowLineItem, BoxItem, BoxLabelItem, ClusterHullItem, ImageItem, LabelItem, MIN_SCALE_FONT_PT, NoteItem, ResizeForeshadow, ResizeHandle
from grafli.lod import CHILD_COLLAPSE_PX, LodModel, should_collapse, should_collapse_container
from grafli.md_note import note_is_md, toggle_task
from grafli.view.minimap import MinimapMixin
from grafli.view.export import ExportMixin
from grafli.view.flows import FlowsMixin
from grafli.view.navigation import NavigationMixin
from grafli.view.overlays import OverlaysMixin
from grafli.view.resources import ResourcesMixin
from grafli.view.selection import SelectionMixin
from grafli.view.structure import StructureMixin
from grafli.view.style_mode import StyleModeMixin
from grafli.view.viewport import ViewportMixin
from grafli.zen import ZenOverlay
from textli import InlineVimEditor, ZenMarkdownEditor


# ── Canvas view ─────────────────────────────────────────────────

class GrafliView(CommandsMixin, ComplexityMixin, MinimapMixin, StyleModeMixin,
                 SelectionMixin, StructureMixin, ResourcesMixin,
                 NavigationMixin, ViewportMixin, FlowsMixin, OverlaysMixin,
                 ExportMixin, QGraphicsView):
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
        # Infinite canvas — pan via drag / trackpad / keyboard / minimap, not
        # scrollbars. Hiding them also keeps `fitInView` deterministic (a
        # scrollbar toggling mid-fit otherwise shrinks the viewport and the
        # fit comes out slightly off — a cause of flaky zoom-to-fit on load).
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

        # Level-of-Detail (semantic zoom). _lod holds the derived structural
        # model; _lod_simplified is the set of box ids currently rendered as
        # bare shells at the current zoom; _lod_enabled is the opt-out toggle.
        self._lod: LodModel | None = None
        self._lod_simplified: set[str] = set()   # boxes drawn as bare shells
        self._lod_collapsed: set[str] = set()    # containers collapsed to tiles
        self._lod_hidden_notes: set[str] = set() # notes hidden under LoD
        self._lod_note_shells: set[str] = set()  # notes drawn as text markers
        self._lod_arrow_labels_hidden: set = set()  # illegible connector labels
        self._lod_hulls: dict[tuple, object] = {}        # cluster key -> hull item
        self._lod_hull_member: dict[str, object] = {}    # member id -> hull item
        self._lod_state = None                   # change-detection snapshot
        self._lod_enabled = True

        # _lod_dirty: the structural model may be stale after an edit; it is
        # consumed (rebuilt) lazily at the top of _refresh_lod. _lod_refresh_timer
        # coalesces a burst of edits (a whole drag) into one rebuild + re-eval
        # once edits settle — the same debounce shape as autosave, so the O(V+E)
        # graph rebuild never lands on the per-frame path.
        self._lod_dirty = False
        self._lod_refresh_timer = QTimer(self)
        self._lod_refresh_timer.setSingleShot(True)
        self._lod_refresh_timer.setInterval(60)
        self._lod_refresh_timer.timeout.connect(self._refresh_lod)

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

        # Arrow selection state. Connectors are their own selection channel
        # (separate from Qt scene selection). ``_selected_arrows`` is the full
        # set; ``_selected_arrow`` (property below) is the primary/last-clicked
        # one that single-target ops (label edit/drag) act on.
        self._selected_arrows: list[Arrow] = []
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
        # Connector option overlay (arrow style mode -> c / t): a multi-row
        # picker over a connector's axes (heads, line, thickness, colour) or its
        # label text, with live preview. Generalises the colour grid to N axes.
        self._conn_overlay_active: bool = False
        self._conn_overlay_axes: list = []
        self._conn_overlay_row: int = 0
        self._conn_overlay_kind: str = "appearance"   # "appearance" | "text"
        self._conn_overlay_original: dict = {}
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
        # Presentation overrides, in force while a flow step (or an export /
        # headless render honouring one) is shown. _present_detail overrides
        # the global LoD toggle ("full" | "summary" | None = follow global);
        # _present_focus_rect, when set, dims every element not completely
        # inside that scene rect ("complete" focus mode).
        self._present_detail: str | None = None
        self._present_focus_rect: QRectF | None = None
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
        self._draw_connector_overlay(painter)
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

    # ── Status bar helpers ──

    def _current_zoom(self) -> float:
        return self.transform().m11()

    def _update_status_zoom(self):
        window = self.window()
        if hasattr(window, '_status_zoom'):
            pct = round(self._current_zoom() * 100)
            window._status_zoom.setText(f"{pct}%")
        self._refresh_lod()
        self._update_status_lod()

    def _selection_has_locked(self) -> bool:
        """True if the selection includes a LoD-collapsed tile — a read-only
        aggregate that stands in for hidden content (you edit at full detail)."""
        if not self._lod_enabled:
            return False
        return any(isinstance(it, BoxItem) and it._lod_tile is not None
                   for it in self._scene.selectedItems())

    def _refuse_locked_edit(self) -> bool:
        """Block a mutation on a collapsed aggregate, nudging toward full detail."""
        if self._selection_has_locked():
            self.toast("Zoom in or ⇧D to edit a collapsed group", "info")
            return True
        return False

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

    def wheelEvent(self, event: QWheelEvent):
        if self._bounce_active:
            event.accept()
            return
        # A trackpad gesture is synthesized by the system and/or carries a
        # scroll phase; a mouse wheel (even a high-res one with pixel deltas)
        # is neither. Only the former pans.
        is_trackpad = (
            event.source() == Qt.MouseEventSource.MouseEventSynthesizedBySystem
            or event.phase() != Qt.ScrollPhase.NoScrollPhase
        )
        action = self._wheel_action(event.pixelDelta(), event.angleDelta(),
                                    event.modifiers(), is_trackpad)
        if action is None:
            event.accept()
            return
        if action[0] == "pan":
            _, dx, dy = action
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - dx)
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - dy)
            event.accept()
            return
        factor = action[1]
        eff, hit = self._clamp_zoom_factor(factor)
        if hit:
            self._zoom_limit_feedback(factor > 1.0)
            event.accept()
            return
        self.scale(eff, eff)   # anchored under the cursor (global anchor)
        self._update_status_zoom()
        event.accept()

    def event(self, e):
        # Trackpad pinch-to-zoom arrives as a native gesture, not a wheel.
        if e.type() == QEvent.Type.NativeGesture and self._handle_native_gesture(e):
            return True
        return super().event(e)

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

        # Double-click a collapsed aggregate to fly into it (the folder *feel*
        # as pure navigation — no persistent state). Editing is blocked until
        # the group is at full detail anyway.
        if isinstance(item, ClusterHullItem) or (
                isinstance(item, BoxItem) and item._lod_tile is not None):
            self._animate_to_rect(
                item.sceneBoundingRect().adjusted(-60, -60, 60, 60))
            event.accept()
            return

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

        # Connector option overlay owns all input while open
        if self._conn_overlay_active:
            self._handle_connector_overlay_key(event)
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
            if self._selected_arrows:
                self._push_undo()
                self._clear_arrow_mode()
                for arrow in self._selected_arrows:
                    self._board.remove_arrow(arrow)
                self._selected_arrows = []
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
                # c — open the appearance overlay (heads / line / thickness / colour)
                if no_mod_a and key == Qt.Key.Key_C:
                    self._open_connector_overlay("appearance")
                    self._record_shortcut("connector style → appearance")
                    event.accept()
                    return
                # t — open the label-text overlay (size)
                if no_mod_a and key == Qt.Key.Key_T:
                    self._open_connector_overlay("text")
                    self._record_shortcut("connector style → text")
                    event.accept()
                    return
                # a — toggle connector kind (graph edge ⇄ annotation); the
                # primary drives the new value, which unifies the whole selection
                if no_mod_a and key == Qt.Key.Key_A:
                    self._push_undo()
                    primary = self._selected_arrow
                    new_kind = ("graph" if self._is_annotation_link(primary)
                                else "annotation")
                    for a in self._selected_arrows:
                        a.kind = new_kind
                    self._last_connector_kind = new_kind
                    self._redraw_arrows()
                    self._select_arrow(self._selected_arrow, keep_mode=True)
                    self._update_arrow_mode_badge_pos()
                    self.mark_dirty()
                    self._record_shortcut(
                        "connector → graph edge" if new_kind == "graph"
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
                    primary = self._selected_arrow
                    if no_mod_a and key == Qt.Key.Key_H:
                        self._set_all_arrows("head_from", not primary.head_from)
                    elif no_mod_a and key == Qt.Key.Key_L:
                        self._set_all_arrows("head_to", not primary.head_to)
                    elif no_mod_a and key == Qt.Key.Key_J:
                        idx = _SIZE_SEQUENCE.index(primary.textsize) if primary.textsize in _SIZE_SEQUENCE else 0
                        self._set_all_arrows("textsize", _SIZE_SEQUENCE[min(idx + 1, len(_SIZE_SEQUENCE) - 1)])
                    elif no_mod_a and key == Qt.Key.Key_K:
                        idx = _SIZE_SEQUENCE.index(primary.textsize) if primary.textsize in _SIZE_SEQUENCE else 0
                        self._set_all_arrows("textsize", _SIZE_SEQUENCE[max(idx - 1, 0)])
                    elif shift_only and key == Qt.Key.Key_J:
                        idx = _ARROW_STYLE_CYCLE.index(primary.style) if primary.style in _ARROW_STYLE_CYCLE else 0
                        self._set_all_arrows("style", _ARROW_STYLE_CYCLE[(idx + 1) % len(_ARROW_STYLE_CYCLE)])
                    elif shift_only and key == Qt.Key.Key_K:
                        idx = _ARROW_STYLE_CYCLE.index(primary.style) if primary.style in _ARROW_STYLE_CYCLE else 0
                        self._set_all_arrows("style", _ARROW_STYLE_CYCLE[(idx - 1) % len(_ARROW_STYLE_CYCLE)])
                    self._redraw_arrows()
                    self._select_arrow(self._selected_arrow, keep_mode=True)
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
            if self._selected_arrows:
                self._push_undo()
                self._clear_arrow_mode()
                for arrow in self._selected_arrows:
                    self._board.remove_arrow(arrow)
                self._selected_arrows = []
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
            # A collapsed aggregate is read-only: block move / style / resize
            # here (navigation keys live outside this block).
            if self._refuse_locked_edit():
                event.accept()
                return
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

        # Shift+D — toggle Level-of-Detail (semantic zoom) on/off
        if event.key() == Qt.Key.Key_D and shift_only:
            self._toggle_lod()
            event.accept()
            return

        # Z — cycle zoom in (25 → 50 → 100 → 150 %, centered on the viewport)
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
            # Shift+click on a connector: accumulate it in the connector
            # selection (its own channel, so bulk-format many at once).
            if isinstance(item, (ArrowLineItem, QGraphicsLineItem,
                                 QGraphicsPolygonItem, QGraphicsSimpleTextItem)):
                arrow_data = item.data(0)
                if isinstance(arrow_data, Arrow):
                    self._select_arrow(arrow_data, additive=True)
                    event.accept()
                    return
            if isinstance(resolved, (BoxItem, NoteItem, ImageItem)):
                # Cross-channel: touching a node clears any connector selection.
                self._deselect_arrow()
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
            # Surface active per-step presentation settings so a viewer can
            # tell why this stop renders summarized / faded.
            for key in ("detail", "focus"):
                if ov.get(key):
                    hint += f" · {key}:{ov[key]}"

            title_font = QFont(FONT_FAMILY, 14, QFont.Weight.Bold)
            desc_font = QFont(FONT_FAMILY, 11)
            hint_font = QFont(FONT_FAMILY, 9)

            pad = 12
            gap = 5
            max_w = min(640, vp.width() - 40)
            # The caption shows its full text, word-wrapped — authoring keeps
            # it within MAX_DESCRIPTION_CHARS, so the card stays a caption.
            # The measurement bound still caps a runaway description so the
            # panel never swallows the whole stage.
            flags = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft)
            bound = QRectF(0, 0, max_w, vp.height() * 0.6)

            painter.setFont(title_font)
            title_rect = painter.boundingRect(bound, flags, title)

            desc = ov["description"] or ""
            painter.setFont(desc_font)
            desc_rect = (painter.boundingRect(bound, flags, desc)
                         if desc else QRectF())

            painter.setFont(hint_font)
            hint_rect = painter.boundingRect(bound, flags, hint)

            content_w = max(title_rect.width(), desc_rect.width(),
                            hint_rect.width())
            panel_w = content_w + pad * 2
            panel_h = (title_rect.height()
                       + (gap + desc_rect.height() if desc else 0)
                       + gap + hint_rect.height() + pad * 2)
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
            painter.drawText(
                QRectF(panel_x + pad, cy, content_w, title_rect.height()),
                flags, title)
            cy += title_rect.height()
            if desc:
                cy += gap
                painter.setFont(desc_font)
                painter.setPen(QPen(QColor(220, 220, 220)))
                painter.drawText(
                    QRectF(panel_x + pad, cy, content_w, desc_rect.height()),
                    flags, desc)
                cy += desc_rect.height()
            cy += gap
            painter.setFont(hint_font)
            painter.setPen(QPen(QColor(150, 150, 150)))
            painter.drawText(
                QRectF(panel_x + pad, cy, content_w, hint_rect.height()),
                flags, hint)

        painter.restore()

