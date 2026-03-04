"""Undo/redo, clipboard, and styling cycle commands (mixin for WhiteboardView)."""

from __future__ import annotations

import copy

from PySide6.QtCore import QPointF

from whiteboard.constants import (
    _ANCHOR_CYCLE,
    _BOX_STYLE_CYCLE,
    _COLOR_VALUES,
    _NOTE_STYLE_CYCLE,
    _SIZE_SEQUENCE,
    _UNDO_LIMIT,
)
from whiteboard.format import Arrow, Box, Note, parse, serialize
from whiteboard.items import BoxItem, NoteItem


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
        window = self.window()
        if hasattr(window, '_board'):
            window._board = self._board
        self.mark_dirty()

    def _redo(self):
        if not self._redo_stack or not self._board:
            return
        self._undo_stack.append(serialize(self._board))
        text = self._redo_stack.pop()
        self._board = parse(text)
        self._rebuild_scene()
        window = self.window()
        if hasattr(window, '_board'):
            window._board = self._board
        self.mark_dirty()

    # ── Copy / Paste ──

    def _copy_selected(self):
        self._clipboard_boxes.clear()
        self._clipboard_notes.clear()
        self._clipboard_arrows.clear()

        selected_box_ids = set()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                self._clipboard_boxes.append(copy.deepcopy(item.box))
                selected_box_ids.add(item.box.id)
            elif isinstance(item, NoteItem):
                self._clipboard_notes.append(copy.deepcopy(item.note))

        if self._board:
            for arrow in self._board.arrows:
                if arrow.from_id in selected_box_ids and arrow.to_id in selected_box_ids:
                    self._clipboard_arrows.append(copy.deepcopy(arrow))

    def _paste(self):
        cursor_viewport = self.mapFromGlobal(self.cursor().pos())
        cursor_scene = self.mapToScene(cursor_viewport)
        self._paste_at(cursor_scene)

    def _paste_at(self, center: QPointF):
        if not (self._clipboard_boxes or self._clipboard_notes) or not self._board:
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

        for orig_note in self._clipboard_notes:
            new_note = copy.deepcopy(orig_note)
            new_note.x += dx
            new_note.y += dy
            self._board.add_note(new_note)

        for orig_arrow in self._clipboard_arrows:
            new_arrow = copy.deepcopy(orig_arrow)
            new_arrow.from_id = id_map.get(orig_arrow.from_id, orig_arrow.from_id)
            new_arrow.to_id = id_map.get(orig_arrow.to_id, orig_arrow.to_id)
            self._board.add_arrow(new_arrow)

        self._rebuild_scene()

        # Select newly pasted items
        new_ids = set(id_map.values())
        for bid, item in self._box_items.items():
            if bid in new_ids:
                item.setSelected(True)

        self.mark_dirty()

    # ── Property shortcuts ──

    def _cycle_color(self, direction: int):
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.color
                idx = _COLOR_VALUES.index(cur) if cur in _COLOR_VALUES else 0
                idx = (idx + direction) % len(_COLOR_VALUES)
                item.set_color(_COLOR_VALUES[idx])
            elif isinstance(item, NoteItem):
                cur = item.note.color
                idx = _COLOR_VALUES.index(cur) if cur in _COLOR_VALUES else 0
                idx = (idx + direction) % len(_COLOR_VALUES)
                item.set_color(_COLOR_VALUES[idx])
        self.mark_dirty()

    def _cycle_textsize(self, direction: int):
        """direction: +1 = increase (toward large), -1 = decrease (toward small)."""
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.textsize
                if cur in _SIZE_SEQUENCE:
                    idx = _SIZE_SEQUENCE.index(cur)
                else:
                    idx = 1  # default to medium
                idx = max(0, min(len(_SIZE_SEQUENCE) - 1, idx + direction))
                item.set_textsize(_SIZE_SEQUENCE[idx])
            elif isinstance(item, NoteItem):
                cur = item.note.textsize
                if cur in _SIZE_SEQUENCE:
                    idx = _SIZE_SEQUENCE.index(cur)
                else:
                    idx = 1
                idx = max(0, min(len(_SIZE_SEQUENCE) - 1, idx + direction))
                item.set_textsize(_SIZE_SEQUENCE[idx])
        self.mark_dirty()

    def _cycle_anchor(self):
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.anchor
                if cur in _ANCHOR_CYCLE:
                    idx = _ANCHOR_CYCLE.index(cur)
                else:
                    idx = 0
                idx = (idx + 1) % len(_ANCHOR_CYCLE)
                item.set_anchor(_ANCHOR_CYCLE[idx])
        self.mark_dirty()

    def _cycle_style(self):
        self._push_undo()
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                cur = item.box.style
                seq = _BOX_STYLE_CYCLE
                idx = seq.index(cur) if cur in seq else 0
                item.set_style(seq[(idx + 1) % len(seq)])
            elif isinstance(item, NoteItem):
                cur = item.note.style
                seq = _NOTE_STYLE_CYCLE
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
        self.arrow_update_needed.emit()
        self.mark_dirty()
