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
from grafli.commands import CommandsMixin
from grafli.complexity import ComplexityMixin
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
from grafli.minimap import MinimapMixin
from grafli.view.navigation import NavigationMixin
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
                 NavigationMixin, ViewportMixin, QGraphicsView):
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
            window._status_lod.setStyleSheet("color: #999999;")
        elif aggregating:
            window._status_lod.setText("◧ LoD")
            window._status_lod.setStyleSheet("color: #C77A52; font-weight: bold;")
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
        from grafli.items import _resolve_color
        hexes = set()
        for m in comp:
            it = self._box_items.get(m)
            if it is not None:
                hexes.add(_resolve_color(it.box.color))
        hexes.discard(None)
        return hexes.pop() if len(hexes) == 1 else self.LOD_NEUTRAL

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

    def _toggle_lod(self):
        self._lod_enabled = not self._lod_enabled
        self._refresh_lod()
        self._record_shortcut(
            "level-of-detail ON" if self._lod_enabled else "level-of-detail OFF")

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

    # ── Presentation overrides (per-step detail / focus) ──

    def _set_presentation_detail(self, detail: str | None):
        """Override the global LoD toggle while a step is shown: "full" keeps
        everything as authored, "summary" collapses containers to tiles, and
        None returns control to the global GUI setting."""
        detail = detail if detail in ("full", "summary") else None
        if detail == self._present_detail:
            return
        self._present_detail = detail
        self._refresh_lod()

    def _set_presentation_focus(self, rect: QRectF | None):
        """Set (or clear, with None) the "complete" focus frame: elements not
        completely inside ``rect`` dim to the standard 0.08 blend level, and a
        connector stays at full opacity only when both its endpoints do."""
        if rect is None and self._present_focus_rect is None:
            return
        self._present_focus_rect = QRectF(rect) if rect is not None else None
        self._apply_presentation_focus()
        self.viewport().update()

    def _presentation_focus_contained(self) -> set[str]:
        """Ids of the visible boxes/notes/images completely inside the focus
        frame. Only meaningful while a focus frame is set."""
        rect = self._present_focus_rect
        contained: set[str] = set()
        if rect is None:
            return contained
        for items in (self._box_items, self._note_items, self._image_items):
            for eid, item in items.items():
                if item.isVisible() and rect.contains(item.sceneBoundingRect()):
                    contained.add(eid)
        return contained

    def _apply_presentation_focus(self):
        """(Re)apply the focus fade — or restore the resting opacities, which
        must respect the standing dim toggles (⇧N notes, "," arrows) and the
        subgraph-focus / complexity filters when clearing."""
        if self._present_focus_rect is None:
            for item in self._box_items.values():
                item.setOpacity(1.0)
                item._label.setOpacity(1.0)
            for item in self._note_items.values():
                item.setOpacity(1.0)
            for item in self._image_items.values():
                item.setOpacity(1.0)
            for gfx in self._arrow_items:
                gfx.setOpacity(1.0)
            if self._focus_active:
                self._apply_focus_filter()
            elif self._complexity_active:
                self._apply_complexity_heatmap()
            else:
                if self._arrows_dimmed:
                    for gfx in self._arrow_items:
                        gfx.setOpacity(0.08)
                if self._notes_hidden:
                    self._apply_notes_hidden()
            return
        contained = self._presentation_focus_contained()
        for bid, item in self._box_items.items():
            opacity = 1.0 if bid in contained else 0.08
            item.setOpacity(opacity)
            item._label.setOpacity(opacity)
        for nid, item in self._note_items.items():
            item.setOpacity(1.0 if nid in contained else 0.08)
        for iid, item in self._image_items.items():
            item.setOpacity(1.0 if iid in contained else 0.08)
        for gfx in self._arrow_items:
            arrow = gfx.data(0)
            if arrow is None:
                continue
            # Endpoints may be re-routed to a collapsed tile under LoD — judge
            # the connector by what is actually drawn on screen.
            from_id = self._lod_reroute(arrow.from_id)
            to_id = self._lod_reroute(arrow.to_id)
            both_in = from_id in contained and to_id in contained
            gfx.setOpacity(1.0 if both_in else 0.08)

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
    def _export_scene_context(self, padding: int = 20, region=None):
        """Prepare the scene for clean export, yield the padded bounding rect.

        Hides unselected items when there is a selection, clears selection
        decorations, and hides the mode badge.  Restores everything on exit.
        A non-null *region* (QRectF, already padded by the caller) overrides
        the default whole-scene bounding rect — used for targeted renders.
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

        if region is not None and not region.isNull():
            rect = QRectF(region)
        else:
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

    def _render_svg_bytes(self, padding: int = 20, region=None) -> QByteArray:
        """Render the current diagram (or selection) to SVG bytes."""
        with self._export_scene_context(padding=padding, region=region) as rect:
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

    def _render_png_image(
        self, scale: int = 2, padding: int = 20, region=None,
    ) -> QImage:
        """Render the current diagram (or selection) to a QImage."""
        with self._export_scene_context(padding=padding, region=region) as rect:
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
        region=None,
    ) -> None:
        """Render the current diagram to a PNG file at *path*.

        If *width* is given, the output is scaled to that width while
        preserving aspect ratio. Otherwise the natural 2× scale is used.
        """
        from PySide6.QtCore import Qt as _Qt
        image = self._render_png_image(padding=padding, region=region)
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
                ("Arrow keys", "Pan viewport (when nothing selected)"),
                ("Middle/Right-drag", "Pan anywhere"),
                ("Two-finger scroll", "Pan (trackpad)"),
                ("Wheel / ⌃scroll / pinch", "Zoom in / out"),
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
                ("⇧D", "Toggle level-of-detail (semantic zoom)"),
                ("Dbl-click tile", "Fly into a collapsed group"),
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
                ("Caption", f"Shown in full, wrapped — keep it ≤ "
                            f"{MAX_DESCRIPTION_CHARS} chars"),
                ("~detail=", "Flow/step LoD: full / summary (file token, "
                             "step overrides flow)"),
                ("~focus=", "Flow/step focus: complete fades partly framed "
                            "elements"),
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
        # The Markdown editor (textli) owns its own help now — press F1 while the
        # zen editor is open to see it. grafli's F1 covers only the diagram.

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
