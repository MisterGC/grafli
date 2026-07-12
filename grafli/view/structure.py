"""Graph structure editing for GrafliView (mixin).

Creating and reshaping the graph's structure: the create-mode ghost preview,
nesting helpers (reparenting, containment checks), encapsulating a selection
in a new parent box, keyboard box creation via Ctrl+Arrow, and inline text
editing of labels. The host GrafliView provides the scene, board model, and
undo machinery.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QStringListModel, Qt
from PySide6.QtGui import QBrush, QFont, QPen
from PySide6.QtWidgets import (
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)
from grafli.constants import (
    BOX_BORDER,
    BOX_FILL,
    BOX_FONT_SIZES,
    DEFAULT_BOX_H,
    DEFAULT_BOX_W,
    FONT_FAMILY,
    LAYOUT_PADDING,
    MIN_BOX_SIZE,
    Mode,
    NOTE_PEN_COLOR,
)
from grafli.format import Arrow, Box, Note
from grafli.items import BoxItem, ImageItem, LabelItem, NoteItem
from pathlib import Path


class StructureMixin:
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
            # A container normally sits behind arrows (it's a backdrop for its
            # children). But a LoD-collapsed container is a solid tile, so it
            # rises above arrows like a leaf — an arrow crossing it passes behind,
            # keeping the tile's headline readable.
            if self._has_children(box_id) and box_id not in self._lod_collapsed:
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

