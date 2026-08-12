"""Style mode for GrafliView (mixin).

The vim-like visual styling layer: everything the transient style mode
presents and applies to the current selection — box style / dimension keys,
the colour, icon, and type-size grids, arrow styling, and the connector
option overlay with its undo/restore snapshot. The host GrafliView provides
selection, scene, and undo machinery.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem
from grafli import theme
from grafli.constants import (
    COLOR_PALETTE,
    FONT_FAMILY,
    resolve_textsize_px,
)
from grafli.format import emphasis_from_flags
from grafli.iconset import EMPHASIS_NAMES, ICON_NAMES, has_icon, icon_pixmap
from grafli.items import BoxItem, ImageItem, NoteItem


class StyleModeMixin:
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
        bg_color = QColor(theme.OVERLAY_BG)
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
        badge.setDefaultTextColor(QColor(theme.OVERLAY_FG))
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

    def _color_picker_boxes(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, BoxItem)]

    def _color_picker_notes(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, NoteItem)]

    def _selected_image_items(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, ImageItem)]

    def _color_picker_targets(self) -> tuple:
        """``(mode, targets)`` — what the colour grid paints.

        Boxes, notes and connectors all have a ``color``, so they all get the
        same 5x3 grid; only the setter differs. Notes reach it for the first
        time here — ``Note.color`` has always serialized, but ``s`` ``c`` used
        to open the plate toggle instead, which now lives in ``s`` ``e`` (#144).
        """
        boxes = self._color_picker_boxes()
        if boxes:
            return "box", boxes
        notes = self._color_picker_notes()
        if notes:
            return "note", notes
        if self._selected_arrows:
            return "arrow", list(self._selected_arrows)
        return "", []

    @staticmethod
    def _target_color(mode: str, target) -> str:
        if mode == "box":
            return target.box.color
        if mode == "note":
            return target.note.color
        return target.color

    @staticmethod
    def _set_target_color(mode: str, target, value: str):
        if mode == "arrow":
            target.color = value
        else:
            target.set_color(value)

    def _open_color_picker(self):
        mode, targets = self._color_picker_targets()
        if not targets:
            self.toast("Select a box, note, or connector", kind="warn")
            return
        self._color_picker_mode = mode
        self._color_picker_original = {id(t): self._target_color(mode, t)
                                       for t in targets}
        values = [v for _, v in COLOR_PALETTE]
        cur = self._target_color(mode, targets[0])
        self._color_picker_index = values.index(cur) if cur in values else 0
        self._color_picker_active = True
        self.viewport().update()

    def _apply_color_picker_live(self):
        """Preview the highlighted choice on the selection (no undo/dirty)."""
        mode, targets = self._color_picker_targets()
        value = COLOR_PALETTE[self._color_picker_index][1]
        for t in targets:
            self._set_target_color(mode, t, value)
        if mode == "arrow":
            self._redraw_arrows()
            if self._selected_arrow:
                self._select_arrow(self._selected_arrow, keep_mode=True)

    def _color_picker_move(self, dcol: int, drow: int):
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
        mode, targets = self._color_picker_targets()
        value = COLOR_PALETTE[self._color_picker_index][1]
        # Restore the pre-picker colours so the undo snapshot captures the
        # original state, then apply the chosen colour as one undoable step.
        for t in targets:
            self._set_target_color(
                mode, t, self._color_picker_original.get(
                    id(t), self._target_color(mode, t)))
        self._push_undo()
        for t in targets:
            self._set_target_color(mode, t, value)
        if mode == "box":
            self._last_box_color = value
        if mode == "arrow":
            self._redraw_arrows()
            self._select_arrow(self._selected_arrow, keep_mode=True)
        self.mark_dirty()
        self._close_color_picker()

    def _cancel_color_picker(self):
        mode, targets = self._color_picker_targets()
        for t in targets:
            if id(t) in self._color_picker_original:
                self._set_target_color(mode, t,
                                       self._color_picker_original[id(t)])
        if mode == "arrow":
            self._redraw_arrows()
            self._select_arrow(self._selected_arrow, keep_mode=True)
        self._close_color_picker()

    def _close_color_picker(self):
        self._color_picker_active = False
        self._color_picker_original = {}
        self.viewport().update()

    def _color_picker_anchor_rect(self):
        """Scene rect the palette panel sits beside, or None with no selection.

        A connector has no graphics item of its own to measure, so it borrows
        the bounding box of the arrow pieces already on the scene.
        """
        mode, targets = self._color_picker_targets()
        if not targets:
            return None
        if mode == "arrow":
            return self._union_scene_rect(list(self._selected_arrow_items))
        return self._union_scene_rect(targets)

    def _draw_color_picker(self, painter: QPainter):
        """A small palette grid anchored beside the selection, with the live
        choice ringed in cyan. Static (no animation), viewport coords."""
        if not self._color_picker_active:
            return
        scene_rect = self._color_picker_anchor_rect()
        if scene_rect is None:
            return
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
        bg = QColor(theme.OVERLAY_BG)
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
            hexv = theme.resolve_color(value)
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
            painter.setBrush(QBrush(QColor(hexv) if hexv else QColor(theme.BOX_FILL)))
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

        painter.setPen(QPen(theme.overlay_ink(0.92)))
        painter.setFont(QFont(FONT_FAMILY, 9))
        painter.drawText(QRectF(px, gy0 + grid_h + 4, panel_w, label_h),
                         Qt.AlignmentFlag.AlignCenter,
                         COLOR_PALETTE[self._color_picker_index][0])
        painter.restore()

    # ── Icon-grid picker (style mode -> i), boxes and notes ──

    _ICON_GRID_COLS = 6
    _ICON_ENTRIES = [""] + ICON_NAMES   # "" = clear/none
    _icon_picker_digit = ""             # typed number badge ("", "1".."99")
    # Captioned category blocks: (header, first entry index, count). The
    # "none" cell leads the semantic block; emphasis symbols follow.
    _ICON_BLOCKS = (
        ("semantic", 0, len(_ICON_ENTRIES) - len(EMPHASIS_NAMES)),
        ("emphasis", len(_ICON_ENTRIES) - len(EMPHASIS_NAMES),
         len(EMPHASIS_NAMES)),
    )

    @classmethod
    def _icon_grid_rows(cls) -> list[list[int]]:
        """Visual rows of entry indices — blocks each start on a fresh row."""
        cols = cls._ICON_GRID_COLS
        rows: list[list[int]] = []
        for _, start, count in cls._ICON_BLOCKS:
            idxs = list(range(start, start + count))
            rows.extend(idxs[i:i + cols] for i in range(0, len(idxs), cols))
        return rows

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
        self._icon_picker_digit = cur if cur.isdigit() else ""
        self._icon_picker_index = (self._ICON_ENTRIES.index(cur)
                                   if cur in self._ICON_ENTRIES else 0)
        self._icon_picker_placement = self._el_placement(targets[0])
        self._icon_picker_active = True
        self.viewport().update()

    def _icon_picker_name(self) -> str:
        """The live choice — a typed number badge wins over the grid cell."""
        return self._icon_picker_digit or self._ICON_ENTRIES[
            self._icon_picker_index]

    def _apply_icon_picker_live(self):
        name = self._icon_picker_name()
        for it in self._icon_picker_targets():
            it.set_icon(name, self._icon_picker_placement)

    def _icon_picker_move(self, dcol: int, drow: int):
        rows = self._icon_grid_rows()
        row = next(i for i, r in enumerate(rows)
                   if self._icon_picker_index in r)
        col = rows[row].index(self._icon_picker_index)
        row = max(0, min(len(rows) - 1, row + drow))
        col = max(0, min(len(rows[row]) - 1, col + dcol))
        idx = rows[row][col]
        if idx != self._icon_picker_index or self._icon_picker_digit:
            self._icon_picker_index = idx
            self._icon_picker_digit = ""
            self._apply_icon_picker_live()
        self.viewport().update()

    def _toggle_icon_placement(self):
        # fill ("") -> lead -> badge -> fill; live-preview the change.
        cycle = {"": "lead", "lead": "badge", "badge": ""}
        self._icon_picker_placement = cycle[self._icon_picker_placement]
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
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            # number badge: 1-9 direct; a second digit press appends (12, 99…)
            digit = chr(ord("1") + key - Qt.Key.Key_1)
            cur = self._icon_picker_digit
            self._icon_picker_digit = cur + digit if len(cur) == 1 else digit
            self._apply_icon_picker_live()
            self.viewport().update()
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
        name = self._icon_picker_name()
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
        """A category-blocked symbol grid anchored beside the selection, with
        the live choice ringed in cyan. Static (no animation), viewport
        coords."""
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
        rows = self._icon_grid_rows()
        sw, gap, pad, label_h, head_h = 30, 6, 10, 18, 16
        grid_w = cols * sw + (cols - 1) * gap
        grid_h = (len(rows) * sw + (len(rows) - 1) * gap
                  + len(self._ICON_BLOCKS) * head_h)
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
        bg = QColor(theme.OVERLAY_BG)
        bg.setAlphaF(0.96)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(px, py, panel_w, panel_h), 8, 8)

        gx0 = px + pad
        cyan = QColor(0, 209, 224)
        ink = theme.overlay_ink(0.87)
        dpr = self.devicePixelRatioF() or 1.0
        head_font = QFont(FONT_FAMILY, 8)
        head_font.setCapitalization(QFont.Capitalization.AllUppercase)
        block_starts = {start: header
                        for header, start, _ in self._ICON_BLOCKS}
        sy = py + pad
        for row in rows:
            if row and row[0] in block_starts:
                painter.setPen(QPen(theme.overlay_ink(0.59)))
                painter.setFont(head_font)
                painter.drawText(QRectF(gx0, sy, grid_w, head_h),
                                 Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter,
                                 block_starts[row[0]])
                sy += head_h
            for c, i in enumerate(row):
                sx = gx0 + c * (sw + gap)
                cell = QRectF(sx, sy, sw, sw)
                name = self._ICON_ENTRIES[i]
                if name:
                    pm = icon_pixmap(name, ink, sw - 8, dpr)
                    if pm is not None:
                        painter.drawPixmap(QPointF(sx + 4, sy + 4), pm)
                else:
                    # "none" cell: a slash marks "no icon".
                    painter.setPen(QPen(QColor(150, 60, 60), 1.5))
                    painter.drawLine(QPointF(sx + 7, sy + sw - 7),
                                     QPointF(sx + sw - 7, sy + 7))
                if i == self._icon_picker_index and not self._icon_picker_digit:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(cyan, 2))
                    painter.drawRoundedRect(cell.adjusted(-1, -1, 1, 1), 5, 5)
            sy += sw + gap
        painter.setPen(QPen(theme.overlay_ink(0.92)))
        painter.setFont(QFont(FONT_FAMILY, 9))
        name = self._icon_picker_name()
        if name:
            shown = f"*{name}" if name.isdigit() else name
            place = self._icon_picker_placement or "fill"
            cur = f"{shown} · {place}   ⇥ placement · 1-9 number"
        else:
            cur = "none   1-9 number badge"
        painter.drawText(QRectF(px, sy - gap + 2, panel_w, label_h),
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
        bg = QColor(theme.OVERLAY_BG)
        bg.setAlphaF(0.96)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(px, py, panel_w, panel_h), 8, 8)

        gx0, gy0 = px + pad, py + pad
        cyan = QColor(0, 209, 224)
        ink = theme.overlay_ink(0.88)
        for r, size in enumerate(self._TYPE_SIZES):
            cy = gy0 + r * cell_h
            painter.setPen(QPen(theme.overlay_ink(0.59)))
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

        painter.setPen(QPen(theme.overlay_ink(0.92)))
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
            painter.setPen(QPen(theme.overlay_ink(0.59)))
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
        bg_color = QColor(theme.OVERLAY_BG)
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
        badge.setDefaultTextColor(QColor(theme.OVERLAY_FG))
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
        if self._elem_overlay_active:
            self._close_element_overlay()
        self._set_arrow_mode("")

    # ── Connector option overlay (style mode -> c / t) ──

    _CONN_HEAD_OPTIONS = (
        ("None", (False, False)),
        ("To →", (False, True)),
        ("← From", (True, False)),
        ("↔ Both", (True, True)),
    )
    _CONN_LINE_OPTIONS = (("Solid", ""), ("Dashed", "dashed"), ("Dotted", "dotted"))
    _CONN_THICK_OPTIONS = (("Thin", "thin"), ("Normal", ""), ("Thick", "thick"))
    _CONN_ROUTING_OPTIONS = (("Direct", ""), ("Spline", "spline"),
                             ("Stair", "ortho"))
    _CONN_SIZE_OPTIONS = (
        ("S", "small"), ("M", ""), ("L", "large"), ("XL", "xlarge"),
        ("2XL", "xxlarge"), ("3XL", "xxxlarge"), ("4XL", "4xl"),
    )
    # Fields snapshotted for undo/restore across the overlay's lifetime.
    _CONN_OVERLAY_FIELDS = ("head_from", "head_to", "style", "thickness",
                            "routing", "color", "textsize")

    def _set_all_arrows(self, field: str, value):
        for a in self._selected_arrows:
            setattr(a, field, value)

    def _connector_axes(self) -> list:
        """The axis spec for the active overlay kind. ``get`` reads the primary
        connector (what the matrix highlights); ``set`` unifies every selected
        connector to the pick."""
        primary = self._selected_arrow
        if self._elem_overlay_kind == "text":
            return [{
                "label": "Text size", "kind": "size",
                "options": list(self._CONN_SIZE_OPTIONS),
                "get": lambda: primary.textsize,
                "set": lambda v: self._set_all_arrows("textsize", v),
            }]
        def set_heads(v):
            for a in self._selected_arrows:
                a.head_from, a.head_to = v
        return [
            {"label": "Heads", "kind": "heads", "options": list(self._CONN_HEAD_OPTIONS),
             "get": lambda: (primary.head_from, primary.head_to),
             "set": set_heads},
            {"label": "Line", "kind": "line", "options": list(self._CONN_LINE_OPTIONS),
             "get": lambda: primary.style,
             "set": lambda v: self._set_all_arrows("style", v)},
            {"label": "Thickness", "kind": "thickness", "options": list(self._CONN_THICK_OPTIONS),
             "get": lambda: primary.thickness,
             "set": lambda v: self._set_all_arrows("thickness", v)},
            {"label": "Routing", "kind": "routing", "options": list(self._CONN_ROUTING_OPTIONS),
             "get": lambda: primary.routing,
             "set": lambda v: self._set_all_arrows("routing", v)},
            {"label": "Colour", "kind": "color", "options": list(COLOR_PALETTE),
             "get": lambda: primary.color,
             "set": lambda v: self._set_all_arrows("color", v)},
        ]

    # ── Box / note appearance axes (style mode -> e) ──

    # "Plate" is the ordinary node: a border, a solid fill, rounded corners.
    # "Flat" is what `!flat` has always meant — no border, translucent fill,
    # sharp corners — which is also the look a container gets for free. Pairing
    # it with a top-left label is how a layer band is drawn (#144).
    _BOX_BG_OPTIONS = (("Plate", ""), ("Flat", "flat"))
    _BOX_LABEL_OPTIONS = (("Center", ""), ("Top left", "topleft"),
                          ("Top center", "topcenter"))
    _NOTE_BG_AXIS_OPTIONS = (("Plate", False), ("None", True))
    # "Auto" follows the file type — raster framed, .svg frameless (#147).
    _IMAGE_FRAME_OPTIONS = (("Auto", ""), ("Frame", "on"), ("None", "off"))

    # Fields snapshotted per target so commit/cancel are exact.
    _BOX_OVERLAY_FIELDS = ("style", "anchor")
    _NOTE_OVERLAY_FIELDS = ("flat",)
    _IMAGE_OVERLAY_FIELDS = ("frame",)

    def _set_all_boxes(self, field: str, value):
        for it in self._color_picker_boxes():
            setattr(it.box, field, value)

    def _label_axis_enabled(self) -> bool:
        """False when an icon owns the label's position.

        ``_position_label`` returns early for ``fill`` and ``lead`` placements —
        the caption rides under the icon or beside it — so ``^anchor`` is dead
        for those boxes and the row must say so rather than silently do nothing.
        """
        return not any(
            it.box.icon and has_icon(it.box.icon)
            and it.box.icon_placement in ("", "lead")
            for it in self._color_picker_boxes())

    def _box_axes(self) -> list:
        primary = self._color_picker_boxes()[0].box
        return [
            {"label": "Background", "kind": "boxbg",
             "options": list(self._BOX_BG_OPTIONS),
             "get": lambda: primary.style,
             "set": lambda v: self._set_all_boxes("style", v)},
            {"label": "Label", "kind": "boxlabel",
             "options": list(self._BOX_LABEL_OPTIONS),
             "enabled": self._label_axis_enabled(),
             "get": lambda: primary.anchor,
             "set": lambda v: self._set_all_boxes("anchor", v)},
        ]

    def _note_axes(self) -> list:
        primary = self._color_picker_notes()[0].note

        def set_flat(v):
            for it in self._color_picker_notes():
                it.note.flat = v

        return [
            {"label": "Background", "kind": "notebg",
             "options": list(self._NOTE_BG_AXIS_OPTIONS),
             "get": lambda: primary.flat,
             "set": set_flat},
        ]

    def _image_axes(self) -> list:
        primary = self._selected_image_items()[0].image

        def set_frame(v):
            for it in self._selected_image_items():
                it.image.frame = v

        return [
            {"label": "Frame", "kind": "imgframe",
             "options": list(self._IMAGE_FRAME_OPTIONS),
             "get": lambda: primary.frame,
             "set": set_frame},
        ]

    def _elem_overlay_objects(self) -> list:
        """The data objects the overlay is editing — never the graphics items.

        Commit and cancel work by restoring fields on these, so they have to be
        the things the board actually serializes.
        """
        if self._elem_overlay_target == "arrow":
            return list(self._selected_arrows)
        if self._elem_overlay_target == "box":
            return [it.box for it in self._color_picker_boxes()]
        if self._elem_overlay_target == "note":
            return [it.note for it in self._color_picker_notes()]
        if self._elem_overlay_target == "image":
            return [it.image for it in self._selected_image_items()]
        return []

    def _elem_overlay_fields(self) -> tuple:
        if self._elem_overlay_target == "arrow":
            return self._CONN_OVERLAY_FIELDS
        if self._elem_overlay_target == "box":
            return self._BOX_OVERLAY_FIELDS
        if self._elem_overlay_target == "image":
            return self._IMAGE_OVERLAY_FIELDS
        return self._NOTE_OVERLAY_FIELDS

    def _open_element_overlay(self, kind: str = "appearance"):
        """Open the appearance overlay for whatever is selected.

        One panel, one key (``s`` then ``e``) — the axes differ by element type
        but the interaction does not, which is the whole point of #144.
        """
        if self._selected_arrows:
            self._elem_overlay_target = "arrow"
            axes = self._connector_axes()
        elif self._color_picker_boxes():
            self._elem_overlay_target = "box"
            axes = self._box_axes()
        elif self._color_picker_notes():
            self._elem_overlay_target = "note"
            axes = self._note_axes()
        elif self._selected_image_items():
            self._elem_overlay_target = "image"
            axes = self._image_axes()
        else:
            self.toast("Select a box, note, image, or connector", kind="warn")
            return
        self._elem_overlay_kind = kind
        self._elem_overlay_axes = axes
        self._elem_overlay_row = 0
        fields = self._elem_overlay_fields()
        self._elem_overlay_original = {
            id(o): {f: getattr(o, f) for f in fields}
            for o in self._elem_overlay_objects()}
        self._elem_overlay_active = True
        self.viewport().update()

    @staticmethod
    def _elem_axis_index(axis) -> int:
        cur = axis["get"]()
        for i, (_disp, value) in enumerate(axis["options"]):
            if value == cur:
                return i
        return 0

    def _resync_elem_items(self):
        """Push the data objects' current values back onto their graphics items.

        Boxes and notes render from item state, so restoring a field on the
        dataclass isn't visible until the item is told — which is what makes
        cancel actually revert rather than only look reverted.
        """
        if self._elem_overlay_target == "box":
            for it in self._color_picker_boxes():
                it._apply_color()          # border and fill follow !flat
                it.refresh_auto_layout()   # label position follows ^anchor
                it.update()
        elif self._elem_overlay_target == "note":
            for it in self._color_picker_notes():
                it.set_flat(it.note.flat)
        elif self._elem_overlay_target == "image":
            for it in self._selected_image_items():
                it.update()

    def _apply_element_overlay_live(self):
        """Preview the current choice on the selection (no undo/dirty)."""
        if self._elem_overlay_target == "arrow":
            self._redraw_arrows()
            if self._selected_arrow:
                self._select_arrow(self._selected_arrow, keep_mode=True)
            self._update_arrow_mode_badge_pos()
        else:
            self._resync_elem_items()
            self.arrow_update_needed.emit()   # anchors follow a moved label
        self.viewport().update()

    def _elem_overlay_move_row(self, delta: int):
        n = len(self._elem_overlay_axes)
        self._elem_overlay_row = max(0, min(n - 1, self._elem_overlay_row + delta))
        self.viewport().update()

    def _elem_overlay_cycle(self, delta: int):
        axis = self._elem_overlay_axes[self._elem_overlay_row]
        if not axis.get("enabled", True):
            return                      # a row something else already owns
        opts = axis["options"]
        idx = max(0, min(len(opts) - 1, self._elem_axis_index(axis) + delta))
        axis["set"](opts[idx][1])
        self._apply_element_overlay_live()

    def _handle_element_overlay_key(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_element_overlay()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_element_overlay()
        elif key == Qt.Key.Key_K:
            self._elem_overlay_move_row(-1)
        elif key == Qt.Key.Key_J:
            self._elem_overlay_move_row(1)
        elif key == Qt.Key.Key_H:
            self._elem_overlay_cycle(-1)
        elif key == Qt.Key.Key_L:
            self._elem_overlay_cycle(1)

    def _restore_elem_overlay_original(self, objs: list):
        for o in objs:
            for f, v in self._elem_overlay_original.get(id(o), {}).items():
                setattr(o, f, v)

    def _refresh_after_elem_overlay(self):
        if self._elem_overlay_target == "arrow":
            self._redraw_arrows()
            self._select_arrow(self._selected_arrow, keep_mode=True)
            self._update_arrow_mode_badge_pos()
        else:
            self._resync_elem_items()
            self.arrow_update_needed.emit()

    def _commit_element_overlay(self):
        objs = self._elem_overlay_objects()
        if not objs:
            self._close_element_overlay()
            return
        # Capture the chosen (live-previewed) values, restore the pre-overlay
        # state so the undo snapshot is the original, then re-apply every
        # element's choice as one undoable step.
        fields = self._elem_overlay_fields()
        chosen = {id(o): {f: getattr(o, f) for f in fields} for o in objs}
        changed = any(chosen[id(o)] != self._elem_overlay_original.get(id(o))
                      for o in objs)
        self._restore_elem_overlay_original(objs)
        if changed:
            self._push_undo()
            for o in objs:
                for f, v in chosen[id(o)].items():
                    setattr(o, f, v)
            self.mark_dirty()
        self._refresh_after_elem_overlay()
        self._close_element_overlay()

    def _cancel_element_overlay(self):
        objs = self._elem_overlay_objects()
        if objs:
            self._restore_elem_overlay_original(objs)
            self._refresh_after_elem_overlay()
        self._close_element_overlay()

    def _close_element_overlay(self):
        self._elem_overlay_active = False
        self._elem_overlay_axes = []
        self._elem_overlay_original = {}
        self._elem_overlay_target = ""
        self.viewport().update()

    @staticmethod
    def _union_scene_rect(items: list):
        if not items:
            return None
        rect = items[0].sceneBoundingRect()
        for it in items[1:]:
            rect = rect.united(it.sceneBoundingRect())
        return rect

    def _elem_overlay_anchor_rect(self):
        """Scene rect the panel sits beside — the elements it is editing.

        This has to follow the target: anchoring on the connector items alone
        left a box selection with an empty list, and the whole-viewport
        fallback parked the panel against the left edge of the window instead
        of beside the box.
        """
        if self._elem_overlay_target == "arrow":
            return self._union_scene_rect(list(self._selected_arrow_items))
        if self._elem_overlay_target == "box":
            return self._union_scene_rect(self._color_picker_boxes())
        if self._elem_overlay_target == "note":
            return self._union_scene_rect(self._color_picker_notes())
        if self._elem_overlay_target == "image":
            return self._union_scene_rect(self._selected_image_items())
        return None

    def _elem_overlay_title(self) -> str:
        if self._elem_overlay_kind == "text":
            return "Connector text"
        return {"arrow": "Connector style", "box": "Box style",
                "note": "Note style",
                "image": "Image style"}.get(self._elem_overlay_target, "Style")

    @staticmethod
    def _axis_cell_size(kind: str) -> tuple:
        """(width, height, gap) for one option cell of the given axis kind."""
        if kind == "color":
            return 18.0, 18.0, 4.0
        if kind == "size":
            return 26.0, 22.0, 4.0
        if kind in ("boxbg", "boxlabel", "notebg", "imgframe"):
            return 30.0, 22.0, 6.0   # miniature box previews
        return 44.0, 22.0, 6.0   # heads / line / thickness sample strips

    def _draw_element_overlay(self, painter: QPainter):
        """A picker matrix anchored beside the selection: one row per axis,
        each option a preview cell (line sample, colour swatch, arrowhead icon,
        miniature box). The selected cell is ringed; the active row glows cyan,
        the others sit muted so it reads as a grid of choices."""
        if not self._elem_overlay_active or not self._elem_overlay_axes:
            return
        scene_rect = self._elem_overlay_anchor_rect()
        if scene_rect is None:
            return
        anchor = self.mapFromScene(scene_rect).boundingRect()

        axes = self._elem_overlay_axes
        pad, title_h, row_h = 10, 18, 30
        # Measure the gutter rather than fixing it: "Background" and "Thickness"
        # are far wider than "Line", and a fixed column clipped them into the
        # first preview cell.
        metrics = QFontMetricsF(QFont(FONT_FAMILY, 9))
        label_w = max(metrics.horizontalAdvance(a["label"]) for a in axes) + 12
        content_w = 0.0
        for axis in axes:
            cw, _ch, gap = self._axis_cell_size(axis["kind"])
            n = len(axis["options"])
            content_w = max(content_w, n * cw + (n - 1) * gap)
        panel_w = pad * 2 + label_w + content_w
        panel_h = pad * 2 + title_h + row_h * len(axes)
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
        bg = QColor(theme.OVERLAY_BG)
        bg.setAlphaF(0.96)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(QRectF(px, py, panel_w, panel_h), 8, 8)

        cyan = QColor(0, 209, 224)
        dim_ring = QColor(120, 140, 142)
        title = self._elem_overlay_title()
        painter.setPen(QPen(theme.overlay_ink(0.59)))
        painter.setFont(QFont(FONT_FAMILY, 8))
        painter.drawText(QRectF(px, py + 4, panel_w, title_h),
                         Qt.AlignmentFlag.AlignHCenter, title)

        for r, axis in enumerate(axes):
            ry = py + pad + title_h + r * row_h
            active = r == self._elem_overlay_row
            enabled = axis.get("enabled", True)
            cw, ch, gap = self._axis_cell_size(axis["kind"])
            cur = self._elem_axis_index(axis)
            painter.setFont(QFont(FONT_FAMILY, 9))
            # A disabled row stays visible but reads as unavailable — something
            # else owns the property, and a hidden row would just look missing.
            strength = 0.28 if not enabled else (0.82 if active else 0.59)
            painter.setPen(QPen(theme.overlay_ink(strength)))
            painter.drawText(QRectF(px + pad, ry, label_w - 4, row_h),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             axis["label"])
            if not enabled:
                painter.setOpacity(0.35)
            cx0 = px + pad + label_w
            cy = ry + (row_h - ch) / 2
            for i, (disp, val) in enumerate(axis["options"]):
                cell = QRectF(cx0 + i * (cw + gap), cy, cw, ch)
                self._draw_axis_cell(painter, axis["kind"], i, disp, val, cell)
                if i == cur:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(cyan if active else dim_ring,
                                        2 if active else 1.3))
                    painter.drawRoundedRect(cell.adjusted(-2, -2, 2, 2), 4, 4)
            painter.setOpacity(1.0)
        painter.restore()

    def _draw_axis_cell(self, painter: QPainter, kind: str, idx: int,
                        disp: str, val, cell: QRectF):
        """Render one option as a small preview inside ``cell``."""
        ink = theme.overlay_ink(0.84)
        mid_y = cell.center().y()
        x1, x2 = cell.left() + 6, cell.right() - 6
        if kind == "color":
            hexv = theme.resolve_color(val)
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
            painter.setBrush(QBrush(QColor(hexv) if hexv else QColor(theme.BOX_FILL)))
            painter.drawRoundedRect(cell, 4, 4)
            if not hexv:   # "Default" swatch: a red slash marks "no override"
                painter.setPen(QPen(QColor(150, 60, 60), 1.5))
                painter.drawLine(QPointF(cell.left() + 3, cell.bottom() - 3),
                                 QPointF(cell.right() - 3, cell.top() + 3))
            return
        if kind == "size":
            ramp = [8, 10, 12, 14, 16, 18, 20]
            painter.setPen(QPen(ink))
            painter.setFont(QFont(FONT_FAMILY, ramp[min(idx, len(ramp) - 1)]))
            painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, "A")
            return
        if kind in ("boxbg", "notebg"):
            # A miniature of the thing itself: plate keeps its border and
            # rounded corners, flat drops both and washes the fill out.
            body = cell.adjusted(3, 3, -3, -3)
            flat = bool(val) if kind == "notebg" else val == "flat"
            fill = QColor(theme.BOX_FILL)
            if flat:
                fill.setAlphaF(0.45)
                painter.setPen(Qt.PenStyle.NoPen)
            else:
                painter.setPen(QPen(ink, 1.4))
            painter.setBrush(QBrush(fill))
            painter.drawRoundedRect(body, 0 if flat else 4, 0 if flat else 4)
            return
        if kind == "imgframe":
            # A tiny picture (circle sun + mountain line); the frame variant
            # rings it solid, "Auto" dashed (the type decides), "None" bare.
            body = cell.adjusted(3, 3, -3, -3)
            painter.setPen(QPen(ink, 1.3))
            painter.setBrush(QBrush(ink))
            painter.drawEllipse(QPointF(body.left() + 7, body.top() + 6), 2.2, 2.2)
            path = QPainterPath(QPointF(body.left() + 3, body.bottom() - 2))
            path.lineTo(QPointF(body.center().x(), body.top() + 8))
            path.lineTo(QPointF(body.right() - 3, body.bottom() - 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            if val != "off":
                pen = QPen(ink, 1.2)
                if val == "":
                    pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRect(body)
            return
        if kind == "boxlabel":
            # Where the caption sits, as a short rule inside an empty frame.
            body = cell.adjusted(3, 3, -3, -3)
            painter.setPen(QPen(ink, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(body, 3, 3)
            bar_w = body.width() * 0.55
            if val == "topleft":
                bx, by = body.left() + 2.5, body.top() + 4
            elif val == "topcenter":
                bx, by = body.center().x() - bar_w / 2, body.top() + 4
            else:
                bx, by = body.center().x() - bar_w / 2, body.center().y() - 1
            painter.setPen(QPen(ink, 2.2))
            painter.drawLine(QPointF(bx, by), QPointF(bx + bar_w, by))
            return
        if kind == "line":
            pen = QPen(ink, 2)
            if val == "dashed":
                pen.setStyle(Qt.PenStyle.DashLine)
            elif val == "dotted":
                pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x1, mid_y), QPointF(x2, mid_y))
            return
        if kind == "thickness":
            width = {"thin": 1.0, "": 2.5, "thick": 5.0}.get(val, 2.5)
            pen = QPen(ink, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x1, mid_y), QPointF(x2, mid_y))
            return
        if kind == "heads":
            head_from, head_to = val
            painter.setPen(QPen(ink, 1.6))
            painter.drawLine(QPointF(x1, mid_y), QPointF(x2, mid_y))
            painter.setBrush(QBrush(ink))
            painter.setPen(QPen(ink, 1))
            s = 3.6
            if head_to:
                painter.drawPolygon(QPolygonF([
                    QPointF(x2, mid_y), QPointF(x2 - 1.7 * s, mid_y - s),
                    QPointF(x2 - 1.7 * s, mid_y + s)]))
            if head_from:
                painter.drawPolygon(QPolygonF([
                    QPointF(x1, mid_y), QPointF(x1 + 1.7 * s, mid_y - s),
                    QPointF(x1 + 1.7 * s, mid_y + s)]))
            return
        if kind == "routing":
            # Each cell draws the shape it picks — a routing is easier to
            # recognise than to name.
            pen = QPen(ink, 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            top, bot = cell.top() + 5, cell.bottom() - 5
            preview = QPainterPath(QPointF(x1, bot))
            if val == "ortho":
                mx = (x1 + x2) / 2
                preview.lineTo(QPointF(mx, bot))
                preview.lineTo(QPointF(mx, top))
                preview.lineTo(QPointF(x2, top))
            elif val == "spline":
                preview.cubicTo(QPointF((x1 + x2) / 2, bot),
                                QPointF((x1 + x2) / 2, top),
                                QPointF(x2, top))
            else:
                preview.lineTo(QPointF(x2, top))
            painter.drawPath(preview)
            return

