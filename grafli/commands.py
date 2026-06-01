"""Undo/redo, clipboard, and styling cycle commands (mixin for GrafliView)."""

from __future__ import annotations

import copy
import hashlib

from PySide6.QtCore import QPointF

from grafli.constants import (
    LAYOUT_PADDING,
    _BOX_STYLE_CYCLE,
    _COLOR_VALUES,
    _SIZE_SEQUENCE,
    _UNDO_LIMIT,
)
from grafli.format import Arrow, Box, Image, Note, parse, serialize
from grafli.items import BoxItem, ImageItem, NoteItem
from grafli.layout import compute_layout


class CommandsMixin:
    """Mixin providing undo/redo, clipboard, and styling cycles.

    Expects the host class to have: _board, _undo_stack, _redo_stack,
    _pre_move_snapshot, _clipboard_boxes, _clipboard_notes, _clipboard_arrows,
    _scene, _box_items, _rebuild_scene(), mark_dirty(), arrow_update_needed,
    GRID_SPACING.
    """

    # ── Undo / Redo ──

    def _push_undo(self):
        """Save current board state to undo stack (call before mutation)."""
        if not self._board:
            return
        self._undo_stack.append(serialize(self._board))
        self._redo_stack.clear()
        if len(self._undo_stack) > _UNDO_LIMIT:
            self._undo_stack.pop(0)

    def _save_pre_action_snapshot(self):
        """Save snapshot before a drag/resize gesture."""
        if self._board:
            self._pre_move_snapshot = serialize(self._board)

    def _commit_pre_action_snapshot(self):
        """Push pre-action snapshot to undo stack if state changed."""
        if self._board and self._pre_move_snapshot:
            current = serialize(self._board)
            if current != self._pre_move_snapshot:
                self._undo_stack.append(self._pre_move_snapshot)
                self._redo_stack.clear()
                if len(self._undo_stack) > _UNDO_LIMIT:
                    self._undo_stack.pop(0)
            self._pre_move_snapshot = ""

    def _undo(self):
        if not self._undo_stack or not self._board:
            return
        self._redo_stack.append(serialize(self._board))
        text = self._undo_stack.pop()
        self._board = parse(text)
        self._rebuild_scene()
        self.mark_dirty()

    def _redo(self):
        if not self._redo_stack or not self._board:
            return
        self._undo_stack.append(serialize(self._board))
        text = self._redo_stack.pop()
        self._board = parse(text)
        self._rebuild_scene()
        self.mark_dirty()

    # ── Copy / Paste ──

    @staticmethod
    def _clipboard_image_fp():
        """Fingerprint the system-clipboard image, or None if there isn't one.

        Used to detect whether the clipboard image changed (an external copy)
        relative to when an internal grafli copy was made.
        """
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if not clipboard:
            return None
        img = clipboard.image()
        if img.isNull():
            return None
        try:
            return (img.width(), img.height(),
                    hashlib.md5(bytes(img.constBits())).hexdigest())
        except Exception:
            return (img.width(), img.height(), img.sizeInBytes())

    def _copy_selected(self):
        self._clipboard_boxes.clear()
        self._clipboard_notes.clear()
        self._clipboard_arrows.clear()
        self._clipboard_images.clear()
        # Remember the clipboard image present *now*, so a later paste can tell
        # this internal copy is more recent than that image.
        self._copy_clip_img_fp = self._clipboard_image_fp()

        selected_box_ids = set()
        selected_note_ids = set()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                self._clipboard_boxes.append(copy.deepcopy(item.box))
                selected_box_ids.add(item.box.id)
            elif isinstance(item, NoteItem):
                self._clipboard_notes.append(copy.deepcopy(item.note))
                selected_note_ids.add(item.note.id)
            elif isinstance(item, ImageItem):
                self._clipboard_images.append(copy.deepcopy(item.image))

        selected_ids = selected_box_ids | selected_note_ids
        if self._board:
            for arrow in self._board.arrows:
                if arrow.from_id in selected_ids and arrow.to_id in selected_ids:
                    self._clipboard_arrows.append(copy.deepcopy(arrow))

    def _paste(self):
        cursor_viewport = self.mapFromGlobal(self.cursor().pos())
        cursor_scene = self.mapToScene(cursor_viewport)

        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        has_image = clipboard is not None and not clipboard.image().isNull()
        has_internal = bool(
            self._clipboard_boxes or self._clipboard_notes or self._clipboard_images
        )

        # Prefer whichever is more recent. A system-clipboard image wins when
        # there's no internal copy, or when the image changed since the last
        # internal copy (i.e. it was copied afterwards). Otherwise the internal
        # copy wins. This stops an internal copy from permanently shadowing a
        # freshly copied image.
        if has_image and (not has_internal
                          or self._clipboard_image_fp() != self._copy_clip_img_fp):
            self._paste_clipboard_image(cursor_scene, clipboard.image())
            return
        if has_internal:
            self._paste_at(cursor_scene)

    def _paste_clipboard_image(self, center: QPointF, qimage):
        """Save a QImage from the system clipboard and add it as an image element."""
        from datetime import datetime
        from pathlib import Path
        from PySide6.QtGui import QImage

        if not self._board:
            return
        window = self.window()
        if not hasattr(window, '_file_path') or not window._file_path:
            return

        from grafli.resources import ensure_res_dir
        file_path = window._file_path
        images_dir = ensure_res_dir(file_path)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        img_name = f"img-{timestamp}.png"
        img_path = images_dir / img_name
        qimage.save(str(img_path), "PNG")

        # Compute display size: 320px wide, aspect ratio preserved
        default_w = 320.0
        aspect = qimage.width() / max(qimage.height(), 1)
        default_h = default_w / aspect

        rel_path = f"{images_dir.name}/{img_name}"
        self._push_undo()
        image = Image(
            id="", image_path=rel_path,
            x=center.x() - default_w / 2,
            y=center.y() - default_h / 2,
            w=default_w, h=default_h,
        )
        self._board.add_image(image)
        self._rebuild_scene()

        if image.id in self._image_items:
            self._image_items[image.id].setSelected(True)
        self.mark_dirty()

    def _paste_at(self, center: QPointF):
        if not (self._clipboard_boxes or self._clipboard_notes or self._clipboard_images) or not self._board:
            return
        self._push_undo()

        # Compute bounding box center of clipboard items
        all_xs: list[float] = []
        all_ys: list[float] = []
        for b in self._clipboard_boxes:
            all_xs += [b.x, b.x + b.w]
            all_ys += [b.y, b.y + b.h]
        for n in self._clipboard_notes:
            all_xs.append(n.x)
            all_ys.append(n.y)
        for img in self._clipboard_images:
            all_xs += [img.x, img.x + img.w]
            all_ys += [img.y, img.y + img.h]
        if not all_xs:
            return
        clip_cx = (min(all_xs) + max(all_xs)) / 2
        clip_cy = (min(all_ys) + max(all_ys)) / 2
        dx = center.x() - clip_cx
        dy = center.y() - clip_cy

        id_map: dict[str, str] = {}
        clipboard_box_ids = {b.id for b in self._clipboard_boxes}

        for orig_box in self._clipboard_boxes:
            new_box = copy.deepcopy(orig_box)
            new_id = self._board.next_box_id()
            id_map[orig_box.id] = new_id
            new_box.id = new_id
            new_box.x += dx
            new_box.y += dy
            self._board.add_box(new_box)

        # Fix parent references to use new IDs
        for box in self._board.boxes:
            if box.id in id_map.values() and box.parent in id_map:
                box.parent = id_map[box.parent]
            elif box.id in id_map.values() and box.parent and box.parent not in clipboard_box_ids:
                pass  # Keep original parent if it exists in the board
            elif box.id in id_map.values() and box.parent in clipboard_box_ids:
                box.parent = id_map.get(box.parent, "")

        note_id_map: dict[str, str] = {}
        for orig_note in self._clipboard_notes:
            new_note = copy.deepcopy(orig_note)
            new_nid = self._board.next_note_id()
            note_id_map[orig_note.id] = new_nid
            new_note.id = new_nid
            new_note.x += dx
            new_note.y += dy
            self._board.add_note(new_note)

        image_id_map: dict[str, str] = {}
        for orig_img in self._clipboard_images:
            new_img = copy.deepcopy(orig_img)
            new_iid = self._board.next_image_id()
            image_id_map[orig_img.id] = new_iid
            new_img.id = new_iid
            new_img.x += dx
            new_img.y += dy
            self._board.add_image(new_img)

        combined_map = {**id_map, **note_id_map, **image_id_map}
        for orig_arrow in self._clipboard_arrows:
            new_arrow = copy.deepcopy(orig_arrow)
            new_arrow.from_id = combined_map.get(orig_arrow.from_id, orig_arrow.from_id)
            new_arrow.to_id = combined_map.get(orig_arrow.to_id, orig_arrow.to_id)
            self._board.add_arrow(new_arrow)

        self._rebuild_scene()

        # Select newly pasted items
        new_box_ids = set(id_map.values())
        new_note_ids = set(note_id_map.values())
        new_image_ids = set(image_id_map.values())
        for bid, item in self._box_items.items():
            if bid in new_box_ids:
                item.setSelected(True)
        for nid, item in self._note_items.items():
            if nid in new_note_ids:
                item.setSelected(True)
        for iid, item in self._image_items.items():
            if iid in new_image_ids:
                item.setSelected(True)

        self.mark_dirty()

    # ── Property shortcuts ──

    def _cycle_color(self, direction: int):
        self._push_undo()
        new_color = None
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.color
                idx = _COLOR_VALUES.index(cur) if cur in _COLOR_VALUES else 0
                idx = (idx + direction) % len(_COLOR_VALUES)
                item.set_color(_COLOR_VALUES[idx])
                new_color = _COLOR_VALUES[idx]
        if new_color is not None:
            self._last_box_color = new_color
        self.mark_dirty()

    def _cycle_textsize(self, direction: int):
        """direction: +1 = increase (toward large), -1 = decrease (toward small)."""
        self._push_undo()
        new_textsize = None
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.textsize
                if cur in _SIZE_SEQUENCE:
                    idx = _SIZE_SEQUENCE.index(cur)
                else:
                    idx = 1  # default to medium
                idx = max(0, min(len(_SIZE_SEQUENCE) - 1, idx + direction))
                item.set_textsize(_SIZE_SEQUENCE[idx])
                new_textsize = _SIZE_SEQUENCE[idx]
            elif isinstance(item, NoteItem):
                cur = item.note.textsize
                if cur in _SIZE_SEQUENCE:
                    idx = _SIZE_SEQUENCE.index(cur)
                else:
                    idx = 1
                idx = max(0, min(len(_SIZE_SEQUENCE) - 1, idx + direction))
                item.set_textsize(_SIZE_SEQUENCE[idx])
                self._last_note_textsize = _SIZE_SEQUENCE[idx]
        if new_textsize is not None:
            self._last_box_textsize = new_textsize
        self.mark_dirty()

    def _cycle_style(self):
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.style
                seq = _BOX_STYLE_CYCLE
                idx = seq.index(cur) if cur in seq else 0
                item.set_style(seq[(idx + 1) % len(seq)])
        self.mark_dirty()

    def _snap_to_grid(self):
        self._push_undo()
        spacing = self.GRID_SPACING
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                item.box.x = round(item.box.x / spacing) * spacing
                item.box.y = round(item.box.y / spacing) * spacing
                item.setPos(item.box.x, item.box.y)
            elif isinstance(item, NoteItem):
                item.note.x = round(item.note.x / spacing) * spacing
                item.note.y = round(item.note.y / spacing) * spacing
                item.setPos(item.note.x, item.note.y)
            elif isinstance(item, ImageItem):
                item.image.x = round(item.image.x / spacing) * spacing
                item.image.y = round(item.image.y / spacing) * spacing
                item.setPos(item.image.x, item.image.y)
        self.arrow_update_needed.emit()
        self.mark_dirty()

    # ── Auto-layout ──

    def _layout_selected(self):
        """Auto-layout selected boxes (or all if nothing selected)."""
        if not self._board:
            return

        selected_boxes = [
            item for item in self._scene.selectedItems()
            if isinstance(item, BoxItem)
        ]
        selected_ids = {item.box.id for item in selected_boxes}

        groups = self._compute_layout_groups(selected_ids)
        if not groups:
            return

        self._push_undo()

        # Sort bottom-up: deepest parent first
        def _depth(parent_id: str) -> int:
            d = 0
            pid = parent_id
            while pid:
                box = self._board.box_by_id(pid)
                if not box or not box.parent:
                    break
                pid = box.parent
                d += 1
            return d

        groups.sort(key=lambda g: -_depth(g[0]))

        for parent_id, child_ids in groups:
            self._layout_group(parent_id, child_ids)

        self._rebuild_scene()
        self.mark_dirty()

    def _compute_layout_groups(
        self, selected_ids: set[str],
    ) -> list[tuple[str, set[str]]]:
        """Determine which groups of boxes to layout.

        Returns list of (parent_id, child_ids) tuples.
        """
        if not self._board:
            return []

        if not selected_ids:
            # Nothing selected → recursive from root
            return self._recursive_layout_groups("")

        # Check if single parent selected (box with children)
        if len(selected_ids) == 1:
            bid = next(iter(selected_ids))
            children = {b.id for b in self._board.boxes if b.parent == bid}
            if children:
                return self._recursive_layout_groups(bid)

        # Multiple boxes — group by parent
        parent_groups: dict[str, set[str]] = {}
        for bid in selected_ids:
            box = self._board.box_by_id(bid)
            if not box:
                continue
            parent = box.parent or ""
            parent_groups.setdefault(parent, set()).add(bid)

        result: list[tuple[str, set[str]]] = []
        for parent_id, child_ids in parent_groups.items():
            result.append((parent_id, child_ids))
            # Recurse into children of grouped boxes
            for cid in child_ids:
                result.extend(self._recursive_layout_groups(cid))

        return result

    def _recursive_layout_groups(
        self, parent_id: str,
    ) -> list[tuple[str, set[str]]]:
        """Build layout groups recursively from parent_id down."""
        if not self._board:
            return []

        children = {b.id for b in self._board.boxes if b.parent == parent_id}
        if not children:
            return []

        result: list[tuple[str, set[str]]] = [(parent_id, children)]
        for cid in children:
            result.extend(self._recursive_layout_groups(cid))
        return result

    def _layout_group(self, parent_id: str, child_ids: set[str]):
        """Layout a single group of children within parent."""
        if not self._board:
            return

        # Compute label_height from parent BoxItem
        label_height = 0.0
        if parent_id and parent_id in self._box_items:
            parent_item = self._box_items[parent_id]
            label_br = parent_item._label.boundingRect()
            if parent_item._get_effective_anchor() in ("topleft", "topcenter"):
                label_height = label_br.height() + 8  # 8px label padding

        box_sizes: dict[str, tuple[float, float]] = {}
        for cid in child_ids:
            box = self._board.box_by_id(cid)
            if box:
                box_sizes[cid] = (box.w, box.h)

        new_positions = compute_layout(
            self._board,
            child_ids,
            parent_id,
            None,
            self.GRID_SPACING,
            label_height,
            box_sizes,
        )

        # Grow parent to fit naturally-spaced children
        if parent_id and new_positions:
            parent = self._board.box_by_id(parent_id)
            if parent:
                max_right = max(
                    nx + box_sizes[bid][0]
                    for bid, (nx, ny) in new_positions.items()
                )
                max_bottom = max(
                    ny + box_sizes[bid][1]
                    for bid, (nx, ny) in new_positions.items()
                )
                needed_w = max_right + LAYOUT_PADDING - parent.x
                needed_h = max_bottom + LAYOUT_PADDING - parent.y
                grid = self.GRID_SPACING
                if needed_w > parent.w:
                    parent.w = round(needed_w / grid) * grid
                if needed_h > parent.h:
                    parent.h = round(needed_h / grid) * grid

        # Apply positions and propagate deltas to descendants/notes
        for bid, (nx, ny) in new_positions.items():
            box = self._board.box_by_id(bid)
            if not box:
                continue
            dx = nx - box.x
            dy = ny - box.y
            box.x = nx
            box.y = ny

            # Propagate delta to all descendants and their notes
            self._propagate_delta(bid, dx, dy)

    def _propagate_delta(self, box_id: str, dx: float, dy: float):
        """Move all descendants and parented notes by (dx, dy)."""
        if not self._board:
            return
        # Move child boxes
        for box in self._board.boxes:
            if box.parent == box_id:
                box.x += dx
                box.y += dy
                self._propagate_delta(box.id, dx, dy)
        # Move parented notes
        for note in self._board.notes:
            if note.parent == box_id:
                note.x += dx
                note.y += dy
