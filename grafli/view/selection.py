"""Selection handling for GrafliView (mixin).

Everything that defines and acts on "what is selected": arrow multi-select
with shift+click, the subgraph focus filter, corner-drag scaling of a
selection about a shared pivot, and deleting the selected elements as one
undo step. The host GrafliView provides the scene, board model, and undo
machinery.
"""

from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsSimpleTextItem,
)
from grafli import theme
from grafli.arrows import (
    _aligned_edge_points,
    _arrowhead_polygon,
    _box_edge_point,
    _line_rect_clip,
    _rect_edge_point,
    ANCHOR_MIN_SEP,
    ANCHOR_SPREAD_MODE,
    ROUTED_CENTRE_BIAS,
    anchor_side,
    perimeter_length,
    perimeter_pos,
    point_at_perimeter,
    relax_circular,
    path_end_angle,
    point_on_side,
    relax_positions,
    routed_path,
    side_of_point,
    split_path_at_rect,
    spread_offsets,
    t_of_point,
)
from grafli.buffers import ViewState
from grafli.constants import (
    ANNOTATION_ARROW_WIDTH,
    ARROWHEAD_SIZE,
    ARROW_LABEL_FONT_SIZES,
    ARROW_WIDTH,
    CONNECTOR_REF_SIZE,
    CONNECTOR_WIDTH_MAX,
    CONNECTOR_WIDTH_MIN,
    FONT_FAMILY,
    MIN_BOX_SIZE,
)
from grafli.edge_label import edge_kind_color, parse_edge_label
from grafli.format import Arrow, Board, Box, Image, Note
from grafli.items import (
    ArrowLineItem,
    BoxItem,
    ImageItem,
    LabelItem,
    MIN_SCALE_FONT_PT,
    NoteItem,
    ResizeForeshadow,
)
from grafli.lod import LodModel
from pathlib import Path


class SelectionMixin:
    # ── Arrow selection ──

    @property
    def _selected_arrow(self) -> "Arrow | None":
        """The primary (last-clicked) connector, or None. Single-target ops
        use this; bulk ops iterate ``_selected_arrows``."""
        return self._selected_arrows[-1] if self._selected_arrows else None

    def _select_arrow(self, arrow: Arrow, keep_mode: bool = False,
                      additive: bool = False):
        if keep_mode:
            # Lightweight re-highlight of the current selection's graphics.
            self._selected_arrow_items.clear()
        elif additive:
            # Shift+click: toggle this connector in/out of the selection. A
            # re-clicked connector drops out; the selection survives as long as
            # one connector remains. Identity, not ==, since equal-valued
            # Arrow dataclasses must stay distinct.
            if any(a is arrow for a in self._selected_arrows):
                self._selected_arrows = [a for a in self._selected_arrows
                                         if a is not arrow]
                if not self._selected_arrows:
                    self._deselect_arrow()
                    return
            else:
                self._selected_arrows.append(arrow)
            self._selected_arrow_items.clear()
        else:
            self._deselect_arrow()
            self._selected_arrows = [arrow]
        self._scene.clearSelection()
        self._highlight_selected_arrows()

    def _highlight_selected_arrows(self):
        """Repaint every selected connector's graphics in the selection blue."""
        self._selected_arrow_items.clear()
        selected = self._selected_arrows
        sel_color = QColor(theme.SELECT_MARQUEE)
        for gfx in self._arrow_items:
            if any(gfx.data(0) is a for a in selected):
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
        if not self._selected_arrows:
            return
        self._clear_arrow_mode()
        self._selected_arrows = []
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
        self._invalidate_lod()

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

    def _invalidate_lod(self) -> None:
        """Mark the structural LoD model stale and schedule a coalesced refresh.

        Hung off mark_dirty (the universal edit funnel) so every present and
        future mutation path keeps LoD in sync without per-call-site wiring.
        Per-frame cost is one bool + a timer restart; the O(V+E) rebuild runs
        once after edits settle (or on the next zoom), in _refresh_lod.
        """
        self._lod_dirty = True
        timer = getattr(self, "_lod_refresh_timer", None)
        if timer is not None:
            timer.start()  # restart: a continuous drag keeps deferring

    def _rebuild_lod_model(self) -> None:
        """Re-derive the structural model from the live board (cheap, O(V+E)).

        Deliberately non-incremental: a full from_board on any edit, bounded by
        grafli's scale (sub-graflis handle larger systems). Matches the
        derive-from-truth style used across the codebase and has no delta
        surface to go stale. See mgc/groundwork/lod-stale-model-2026-06-29.md.
        """
        if self._board is None:
            self._lod = None
            self._lod_dirty = False
            return
        self._lod = LodModel.from_board(self._board)
        self._feed_lod_note_extents()
        self._lod_dirty = False

    def _feed_lod_note_extents(self) -> None:
        """Replace notes' placeholder extents with their rendered footprints so
        a notes-only container collapses on size like any box container."""
        if self._lod is None:
            return
        self._lod.set_note_extents({
            nid: (it.boundingRect().width(), it.boundingRect().height())
            for nid, it in self._note_items.items()
        })

    def load_board(self, board: Board):
        self._board = board
        self._lod = LodModel.from_board(board)
        self._lod_simplified = set()
        self._lod_collapsed = set()
        self._lod_hidden_notes = set()
        self._lod_note_shells = set()
        self._lod_arrow_labels_hidden = set()
        self._lod_hulls = {}          # items live in the about-to-be-rebuilt scene
        self._lod_hull_member = {}
        self._lod_state = None
        # A fresh board invalidates any in-flight flow recording/playback.
        self._recording_flow = None
        if self._flow_player is not None:
            self._flow_player.stop()
        self._rebuild_scene()
        # Feed real note footprints to the model now the items exist, so a
        # notes-only container can collapse on size like any box container.
        self._feed_lod_note_extents()
        self._lod_dirty = False  # fresh model; ignore any mark_dirty during load
        self._refresh_lod()
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
        # The scene clear above deleted any LoD hull/overlay items; drop the now
        # dangling references and force the next _refresh_lod to fully reapply
        # (mirrors load_board). Otherwise a scene rebuild while zoomed into a
        # hull — undo/redo, paste, layout — would reroute arrows onto a deleted
        # ClusterHullItem in the _redraw_arrows below.
        self._lod_hulls = {}
        self._lod_hull_member = {}
        self._lod_state = None
        self._editor = None
        self._edit_target = None
        self._note_proxy = None
        self._note_widget = None
        self._rect_preview = None
        self._connect_line = None
        self._connect_source = None
        self._selected_arrows = []
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

    def _connector_anchors(self, render_list) -> dict:
        """Where every connector attaches — routed and direct in one pass.

        A box side is shared, so allocating it twice cannot work: a routed
        connector choosing the side midpoint on its own lands on top of a direct
        connector already arriving there, and neither knows to order itself
        against the other (#138 follow-up).

        Every endpoint therefore starts from the same natural position — where
        the centre-to-centre ray crosses the edge, which is what a direct
        connector has always used — and is nudged along its side only when a
        neighbour comes too close, keeping natural order. Natural order is what
        makes a connector heading right sit to the right of one arriving from
        above-left, instead of crossing it.

        Returns ``idx -> (start, start_side, end, end_side, moved)``, where
        ``moved`` is False for a direct connector that kept its natural
        position — the caller leaves those on the untouched code path.
        """
        natural: dict[int, list] = {}
        groups: dict[tuple[str, str], list] = {}

        for idx, (from_id, to_id, _ht, _hf, fwd, _rev) in enumerate(render_list):
            f_id = self._lod_reroute(from_id)
            t_id = self._lod_reroute(to_id)
            if f_id == t_id:
                continue
            if (self._lod_hull_member.get(f_id) is not None
                    or self._lod_hull_member.get(t_id) is not None):
                continue                     # hull boundary, not a box side
            f_elem = self._board.box_by_id(f_id) or self._board.note_by_id(f_id)
            t_elem = self._board.box_by_id(t_id) or self._board.note_by_id(t_id)
            if not f_elem or not t_elem:
                continue
            f_rect = self._elem_rect(f_elem)
            t_rect = self._elem_rect(t_elem)

            aligned = (_aligned_edge_points(f_elem, t_elem)
                       if isinstance(f_elem, Box) and isinstance(t_elem, Box)
                       else None)
            if aligned:
                s_pt, e_pt = aligned
            else:
                f_mid = QPointF(f_rect[0] + f_rect[2] / 2,
                                f_rect[1] + f_rect[3] / 2)
                t_mid = QPointF(t_rect[0] + t_rect[2] / 2,
                                t_rect[1] + t_rect[3] / 2)
                s_pt = _rect_edge_point(*f_rect, t_mid)
                e_pt = _rect_edge_point(*t_rect, f_mid)

            s_side = side_of_point(f_rect, s_pt)
            e_side = side_of_point(t_rect, e_pt)
            s_t = t_of_point(f_rect, s_side, s_pt)
            e_t = t_of_point(t_rect, e_side, e_pt)
            # Rank by where the target puts the anchor, place by where it
            # wants to sit. A routed anchor is held near the middle of its side
            # — it leaves perpendicular and needs room to turn — but ranking by
            # that pulled value could drop it below a neighbour and invert the
            # pair into a crossing.
            s_want, e_want = s_t, e_t
            if fwd.routing:
                s_want = 0.5 + (s_t - 0.5) * ROUTED_CENTRE_BIAS
                e_want = 0.5 + (e_t - 0.5) * ROUTED_CENTRE_BIAS
            natural[idx] = [f_rect, s_side, s_want,
                            t_rect, e_side, e_want,
                            bool(fwd.routing), s_t, e_t]
            groups.setdefault((f_id, s_side), []).append((idx, 0))
            groups.setdefault((t_id, e_side), []).append((idx, 1))

        slots: dict[tuple[int, int], float] = {}
        for (_elem_id, side), members in groups.items():
            if len(members) < 2:
                continue
            idx0, which0 = members[0]
            rect = natural[idx0][0] if which0 == 0 else natural[idx0][3]
            span = rect[2] if side in ("n", "s") else rect[3]
            min_sep = ANCHOR_MIN_SEP / span if span > 0 else 0.2
            values = [natural[i][2 if w == 0 else 5] for i, w in members]
            ranks = [natural[i][7 if w == 0 else 8] for i, w in members]
            for member, value in zip(
                    members, relax_positions(values, min_sep, ranks)):
                slots[member] = value

        anchors = {}
        for idx, (f_rect, s_side, s_t, t_rect, e_side, e_t, routed,
                  _rs, _re) in natural.items():
            new_s = slots.get((idx, 0), s_t)
            new_e = slots.get((idx, 1), e_t)
            moved = abs(new_s - s_t) > 1e-6 or abs(new_e - e_t) > 1e-6
            if not routed and not moved:
                continue                     # untouched: keep the old path
            anchors[idx] = (point_on_side(f_rect, s_side, new_s), s_side,
                            point_on_side(t_rect, e_side, new_e), e_side,
                            moved)
        return anchors

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

        conn_anchors = self._connector_anchors(render_list)

        for idx, (from_id, to_id, draw_head_to, draw_head_from, fwd, rev) in enumerate(
                render_list):
            # Level-of-Detail: an endpoint inside a collapsed container re-routes
            # to that container's tile; an edge that becomes internal to a single
            # tile (both ends resolve to it) is dropped.
            from_id = self._lod_reroute(from_id)
            to_id = self._lod_reroute(to_id)
            if from_id == to_id:
                continue
            from_hull = self._lod_hull_member.get(from_id)
            to_hull = self._lod_hull_member.get(to_id)
            if from_hull is not None and from_hull is to_hull:
                continue  # internal to one cluster — drop it
            from_elem = self._board.box_by_id(from_id) or self._board.note_by_id(from_id)
            to_elem = self._board.box_by_id(to_id) or self._board.note_by_id(to_id)
            if not from_elem or not to_elem:
                continue

            # Kind drives styling now, not endpoint type: a note joined by a
            # graph edge renders as a normal directional arrow.
            is_annotation = self._is_annotation_link(fwd)
            both_boxes = isinstance(from_elem, Box) and isinstance(to_elem, Box)

            if is_annotation:
                arrow_color = theme.ANNOTATION_ARROW_COLOR
                arrow_width = ANNOTATION_ARROW_WIDTH
                draw_head_to = False
                draw_head_from = False
            else:
                edge_kind = parse_edge_label(fwd.label).kind
                if not edge_kind and rev:
                    edge_kind = parse_edge_label(rev.label).kind
                arrow_color = edge_kind_color(edge_kind, theme.ARROW_COLOR)
                # Thickness tracks the size of the linked nodes (visual hierarchy).
                arrow_width = self._connector_width(from_elem, to_elem)

            # A per-connector colour overrides the kind-derived default.
            if fwd.color:
                resolved = theme.resolve_color(fwd.color)
                if resolved:
                    arrow_color = QColor(resolved)

            # Arrowheads grow with the line, but gently, so they stay tasteful.
            # Sized off the base width so an explicit thickness doesn't bloat them.
            head_size = ARROWHEAD_SIZE * (arrow_width / ARROW_WIDTH) ** 0.6

            pen = QPen(arrow_color, arrow_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            if fwd.style == "dashed":
                pen.setStyle(Qt.PenStyle.DashLine)
            elif fwd.style == "dotted":
                pen.setStyle(Qt.PenStyle.DotLine)
            if fwd.thickness == "thick":
                pen.setWidthF(arrow_width * 2)
            elif fwd.thickness == "thin":
                pen.setWidthF(max(0.5, arrow_width * 0.5))

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

            # An endpoint hidden inside a cluster re-attaches to its hull outline.
            if from_hull is not None or to_hull is not None:
                ref_start, ref_end = QPointF(start), QPointF(end)
                if from_hull is not None:
                    start = from_hull.boundary_point(ref_end)
                if to_hull is not None:
                    end = to_hull.boundary_point(ref_start)

            # A routed connector swaps the centre-ray anchors for side anchors
            # and draws a path between them. Skipped when an endpoint has been
            # re-attached to a cluster hull: that boundary point isn't a box
            # side, so there is no side to leave perpendicular to.
            conn_path = None
            anchors = conn_anchors.get(idx)
            if anchors and from_hull is None and to_hull is None:
                a_start, a_start_side, a_end, a_end_side, _moved = anchors
                start, end = a_start, a_end
                if fwd.routing:
                    conn_path = routed_path(
                        fwd.routing, start, a_start_side, end, a_end_side)

            dx = end.x() - start.x()
            dy = end.y() - start.y()

            # Forward arrowhead (at to_id end)
            if draw_head_to:
                angle = (path_end_angle(conn_path, True) if conn_path is not None
                         else math.atan2(dy, dx))
                head = QGraphicsPolygonItem(_arrowhead_polygon(end, angle, head_size))
                head.setPen(QPen(arrow_color, 1))
                head.setBrush(QBrush(arrow_color))
                head.setData(0, fwd)
                self._scene.addItem(head)
                self._arrow_items.append(head)

            # Backward arrowhead (at from_id end)
            if draw_head_from:
                back_angle = (path_end_angle(conn_path, False)
                              if conn_path is not None else math.atan2(-dy, -dx))
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
            # Drop the connector label when either end is a LoD-collapsed node
            # (tile or hull) — its authored size would render as illegible
            # clutter on a rerouted edge.
            endpoint_collapsed = (
                from_hull is not None or to_hull is not None
                or from_id in self._lod_collapsed or to_id in self._lod_collapsed)
            # Illegible at this zoom (set by _refresh_lod): the label is kept in
            # the scene (hidden) so it's still tracked, but the line draws
            # unbroken — no leftover gap where the caption sat.
            label_too_small = (fwd.from_id, fwd.to_id) in self._lod_arrow_labels_hidden
            has_label = False
            if label_texts and total_len > 0 and not endpoint_collapsed:
                # The label rides the connector, so on a routed one it follows
                # the path's midpoint — the chord midpoint of an L-bend sits off
                # in empty space, nowhere near the line it is labelling.
                if conn_path is not None:
                    mid = conn_path.pointAtPercent(0.5)
                    mid_x, mid_y = mid.x(), mid.y()
                else:
                    mid_x = (start.x() + end.x()) / 2
                    mid_y = (start.y() + end.y()) / 2

                combined = "\n".join(label_texts)
                label = LabelItem(combined)
                label.setFont(QFont(FONT_FAMILY, ARROW_LABEL_FONT_SIZES.get(fwd.textsize, 10)))
                label.setBrush(QBrush(QColor(theme.INK)))
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
                label.setVisible(not label_too_small)
                self._scene.addItem(label)
                self._arrow_items.append(label)
                has_label = not label_too_small

            # Draw line (split around label gap if needed)
            if conn_path is not None:
                # A path has no single parametric line to clip, so the label
                # gap is walked out of it instead — one piece when the label
                # misses the connector, two when it interrupts it.
                pieces = (split_path_at_rect(conn_path, gap) if has_label
                          else [conn_path])
                tooltip_parts = [a.annotation for a in (fwd, rev)
                                 if a is not None and a.annotation]
                for piece in pieces:
                    line = ArrowLineItem(piece)
                    line.setPen(pen)
                    line.setData(0, fwd)
                    if tooltip_parts and not has_label:
                        line.setToolTip("\n".join(tooltip_parts))
                    self._scene.addItem(line)
                    self._arrow_items.append(line)
            elif has_label:
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
        if self._present_focus_rect is not None:
            # Rebuilt arrow gfx start at full opacity — refresh the focus fade.
            self._apply_presentation_focus()

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
            pen = QPen(QColor(theme.ACCENT_TEAL), 3, Qt.PenStyle.DashLine)
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
        if self._refuse_locked_edit():   # can't delete a collapsed aggregate
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

