"""The standard control scheme on the canvas (#352, mixin).

In the standard scheme (:mod:`grafli.controls`) the canvas answers the keys
and gestures other apps use and nothing else: chords like Ctrl+C are the
window's menu actions, plain keys (Delete, the arrows, F2, Enter, Esc) are
the table :data:`STANDARD_KEYS` here, the right button opens a menu for what
is under the pointer, and Space+drag pans. A plain letter never runs a
command.

Every command, whichever way it is reached — menu, toolbar, right-click
menu, key — runs through :meth:`StandardMixin.std_run`. That one door is what
``tests/test_standard_controls.py`` watches when it presses each documented
key and clicks each documented menu item.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from grafli import controls
from grafli.constants import DEFAULT_BOX_H, DEFAULT_BOX_W, Mode
from grafli.format import Arrow, Box, Note, emphasis_from_flags
from grafli.items import (ArrowLineItem, BoxItem, BoxLabelItem, ImageItem,
                          NoteItem, ResizeHandle)

_SHIFT = Qt.KeyboardModifier.ShiftModifier
_MODS = (Qt.KeyboardModifier.ShiftModifier
         | Qt.KeyboardModifier.ControlModifier
         | Qt.KeyboardModifier.AltModifier
         | Qt.KeyboardModifier.MetaModifier)
_NONE = Qt.KeyboardModifier.NoModifier

# The plain keys of the standard scheme: (key, modifiers) -> (command, args).
STANDARD_KEYS: dict[tuple, tuple[str, dict]] = {
    (Qt.Key.Key_Escape, _NONE): ("escape", {}),
    (Qt.Key.Key_Delete, _NONE): ("delete", {}),
    (Qt.Key.Key_Backspace, _NONE): ("delete", {}),
    (Qt.Key.Key_F2, _NONE): ("rename", {}),
    (Qt.Key.Key_Return, _NONE): ("open_attachment", {}),
    (Qt.Key.Key_Enter, _NONE): ("open_attachment", {}),
    (Qt.Key.Key_Tab, _NONE): ("next_sibling", {}),
    (Qt.Key.Key_Tab, _SHIFT): ("prev_sibling", {}),
    (Qt.Key.Key_Backtab, _SHIFT): ("prev_sibling", {}),
    (Qt.Key.Key_Backtab, _NONE): ("prev_sibling", {}),
}
for _key, _d in ((Qt.Key.Key_Left, (-1, 0)), (Qt.Key.Key_Right, (1, 0)),
                 (Qt.Key.Key_Up, (0, -1)), (Qt.Key.Key_Down, (0, 1))):
    STANDARD_KEYS[(_key, _NONE)] = ("nudge", {"dx": _d[0], "dy": _d[1]})
    STANDARD_KEYS[(_key, _SHIFT)] = ("nudge", {"dx": _d[0], "dy": _d[1],
                                               "big": True})

# While a tour plays.
PLAYBACK_KEYS: dict[tuple, str] = {
    (Qt.Key.Key_Space, _NONE): "play:next",
    (Qt.Key.Key_Right, _NONE): "play:next",
    (Qt.Key.Key_Left, _NONE): "play:prev",
    (Qt.Key.Key_Escape, _NONE): "play:stop",
    (Qt.Key.Key_Return, _NONE): "play:open",
}

# Commands an open text field answers itself (Ctrl+C copies its text): when
# one reaches the canvas with a field open, it goes to the field.
_TEXT_OWNED = {"undo", "redo", "cut", "copy", "paste", "select_all"}

# Commands that may run while a full-window editor or picker is up.
_ALWAYS = {"quit", "theme", "help"}

# Commands that change the selected elements: refused on a collapsed group
# of the level of detail, as the vim keys refuse them (you edit at full
# detail).
_EDITS = {"rename", "edit_text", "set_link", "attach", "color", "icon",
          "textsize", "bold", "italic", "outline", "shadow", "face",
          "text_bigger", "text_smaller", "axis", "round", "status", "group",
          "cut", "duplicate", "snap_grid", "slide_ratio", "connected_box"}

# Successive arrow-key moves within this many seconds are one undo step.
_NUDGE_UNDO_WINDOW = 1.0


def key_modifiers(event) -> Qt.KeyboardModifier:
    """The modifiers that tell keys apart (the keypad flag a Mac sets on
    the arrow keys is not one of them)."""
    return event.modifiers() & _MODS


def resolve_node(item):
    """The box, note or image a click on ``item`` (its label, a handle)
    means, or the item itself."""
    if isinstance(item, BoxLabelItem):
        return item._box_item
    if (isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem,
                          ResizeHandle))
            and isinstance(item.parentItem(), (BoxItem, NoteItem, ImageItem))):
        return item.parentItem()
    return item


def arrow_of(item) -> Arrow | None:
    """The arrow a graphics piece (its line, head, label) draws, if any."""
    if isinstance(item, (ArrowLineItem, QGraphicsLineItem,
                         QGraphicsPolygonItem, QGraphicsSimpleTextItem)):
        data = item.data(0)
        if isinstance(data, Arrow):
            return data
    return None


class StandardMixin:
    """The canvas's half of the standard control scheme."""

    _std_space_held = False
    _std_space_panning = False
    _last_context_menu = None
    _std_last_nudge = (0.0, frozenset(), None)

    def event(self, e):
        # While Find or the jump labels take typing, the keys are theirs:
        # a menu shortcut (Ctrl+X, Delete …) must not act on the board
        # behind the field.
        if (e.type() == QEvent.Type.ShortcutOverride
                and controls.is_standard()
                and (self._search_active or self._jump_active)):
            e.accept()
            return True
        return super().event(e)

    # ── The one door every command goes through ──

    def std_run(self, action: str, **kw):
        """Run standard-scheme command ``action``."""
        if self._text_field_command(action):
            return
        if (self._zen_editor is not None or self._fuzzy_overlay is not None) \
                and action not in _ALWAYS:
            return
        if self._editor is not None or self._note_widget is not None:
            self._commit_editor()
        if self._color_picker_active or self._icon_picker_active \
                or self._type_picker_active or self._elem_overlay_active:
            self._cancel_open_picker()
        if action in _EDITS and self._refuse_locked_edit():
            return
        handler = self._std_handlers().get(action)
        if handler is None:
            self.toast(f"No command {action!r}", "warn")
            return
        handler(**kw)

    def _text_field_command(self, action: str) -> bool:
        """A text command (Ctrl+C, Ctrl+Z …) that reached the canvas while a
        text field is open goes to the field, as the field would have taken
        it itself; Save in the text window saves its text."""
        from grafli.standard_ui import PlainTextWindow
        window = self._zen_editor
        if isinstance(window, PlainTextWindow) and action == "save":
            window.save()
            return True
        if action not in _TEXT_OWNED:
            return False
        field = (window.field if isinstance(window, PlainTextWindow)
                 else self._note_widget)
        if field is not None:
            {"undo": field.undo, "redo": field.redo, "cut": field.cut,
             "copy": field.copy, "paste": field.paste,
             "select_all": field.selectAll}[action]()
            return True
        editor = self._editor
        if editor is None:
            return False
        cursor = editor.textCursor()
        clipboard = QApplication.clipboard()
        if action == "undo":
            editor.document().undo()
        elif action == "redo":
            editor.document().redo()
        elif action == "select_all":
            cursor.select(cursor.SelectionType.Document)
            editor.setTextCursor(cursor)
        elif action in ("copy", "cut") and cursor.hasSelection():
            clipboard.setText(cursor.selectedText())
            if action == "cut":
                cursor.removeSelectedText()
                editor.setTextCursor(cursor)
        elif action == "paste":
            cursor.insertText(clipboard.text())
            editor.setTextCursor(cursor)
        return True

    def _cancel_open_picker(self):
        if self._color_picker_active:
            self._cancel_color_picker()
        if self._icon_picker_active:
            self._cancel_icon_picker()
        if self._type_picker_active:
            self._cancel_type_picker()
        if self._elem_overlay_active:
            self._cancel_element_overlay()

    def _win(self, name: str):
        """A command of the main window. A bare view (a headless render) has
        none: the stand-in says so, and is marked so a test can tell a real
        binding from a missing one."""
        fn = getattr(self.window(), name, None)
        if callable(fn):
            return fn

        def missing(*_a, **_k):
            self.toast("Not available here", "info")
        missing.std_missing = name
        return missing

    def _std_handlers(self) -> dict:
        w = self._win
        return {
            # tools
            "tool_select": lambda: self.set_mode(Mode.SELECT),
            "tool_box": lambda: self.set_mode(Mode.RECT),
            "tool_note": lambda: self.set_mode(Mode.TEXT),
            "tool_connect": lambda: self.set_mode(Mode.CONNECT),
            "tool_mockup": lambda: self.set_mode(Mode.IMAGE),
            "insert_image": self._std_insert_image,
            "insert_box": self._std_insert_box,
            "insert_note": self._std_insert_note,
            "connect_from": self._std_connect_from,
            "on_target": self._std_on_target,
            "escape": self._std_escape,
            # edit
            "undo": self._undo,
            "redo": self._redo,
            "cut": self._std_cut,
            "copy": self._std_copy,
            "paste": self._std_paste,
            "duplicate": self._std_duplicate,
            "delete": self._std_delete,
            "select_all": self._std_select_all,
            "rename": self._std_rename,
            "nudge": self._std_nudge,
            "set_link": self._set_url,
            "attach": self._std_attach,
            "edit_text": self._std_edit_text,
            # format
            "color": self._std_set_color,
            "icon": self._std_pick_icon,
            "textsize": self._std_set_textsize,
            "bold": lambda: self._std_toggle_emphasis("bold"),
            "italic": lambda: self._std_toggle_emphasis("italic"),
            "outline": lambda: self._std_toggle_emphasis("outline",
                                                         notes_only=True),
            "shadow": lambda: self._std_toggle_emphasis("shadow",
                                                        notes_only=True),
            "face": self._std_set_face,
            "text_bigger": lambda: self._cycle_textsize(1),
            "text_smaller": lambda: self._cycle_textsize(-1),
            "axis": self._std_set_axis,
            "round": self._toggle_round,
            "status": self._std_edit_status,
            "arrow_kind": self._std_toggle_arrow_kind,
            # arrange
            "group": self._encapsulate_selection,
            "layout": self._layout_selected,
            "snap_grid": self._std_snap_to_grid,
            "slide_ratio": self._snap_selection_to_slide_ratio,
            "connected_box": self._create_adjacent_box,
            # navigate
            "find": self._start_search,
            "zoom_in": w("_zoom_in"),
            "zoom_out": w("_zoom_out"),
            "zoom_fit": w("_zoom_fit_shortcut"),
            "zoom_selection": self._toggle_focus_zoom,
            "open_attachment": self._std_open,
            "go_into": self._go_down,
            "go_up": w("_go_up"),
            "nav_back": self._nav_back,
            "nav_forward": self._nav_forward,
            "next_sibling": lambda: self._std_cycle_sibling(1),
            "prev_sibling": lambda: self._std_cycle_sibling(-1),
            "parent_box": self._select_parent_and_zoom,
            "first_child": self._select_first_child,
            "follow_arrow": self._std_follow,
            "peek_doc": self._peek_doc,
            # view
            "grid": self.toggle_grid,
            "minimap": self._toggle_minimap,
            "legend": self._toggle_legend,
            "lod": self._toggle_lod,
            "dim_notes": self._toggle_notes_hidden,
            "dim_arrows": self._toggle_arrows_dimmed,
            "heatmap": self._toggle_complexity,
            "focus_connections": self._std_focus_connections,
            "focus_depth": self._std_focus_depth,
            "tools_panel": w("_toggle_panel"),
            "theme": w("_toggle_theme"),
            # tours
            "bookmark": lambda: self.capture_bookmark("logical"),
            "bookmark_viewport": lambda: self.capture_bookmark("viewport"),
            "record_flow": self.toggle_flow_recording,
            "auto_flow": self.new_auto_flow_from_selection,
            "tours_through": self._tours_through_selection,
            "edit_flows": w("_show_flows_panel"),
            "present": w("_present_current"),
            "play_mode": lambda: self._std_player("cycle_play_mode"),
            "play_transition": lambda: self._std_player("toggle_transition"),
            "play:next": lambda: self._std_player("next"),
            "play:prev": lambda: self._std_player("prev"),
            "play:stop": lambda: self._std_player("end"),
            "play:open": self._std_play_open,
            # files
            "new_board": w("_new_file"),
            "open": w("_open_dialog"),
            "save": w("_save_file"),
            "close_board": w("close_buffer"),
            "switch_board": w("_open_fuzzy_picker"),
            "last_board": w("_toggle_last_buffer"),
            "export_png": self._yank_png_to_clipboard,
            "export_svg": self._export_svg_file,
            "export_pdf": w("_export_flow_pdf"),
            "export_pptx": w("_export_flow_pptx"),
            "export_html": w("_export_html"),
            "quit": w("close"),
            "help": self._show_cheatsheet,
            "scheme": w("set_control_scheme"),
            # the board's agent
            "agent_line": w("open_agent_line"),
            "agent_ask": w("ask_agent_about_selection"),
            "agent_take": w("take_agent_proposal"),
            "agent_drop": w("drop_agent_proposal"),
            "agent_undo": w("undo_agent_edit"),
        }

    # ── Keys ──

    def _std_key_press(self, event):
        """``keyPressEvent`` in the standard scheme, past the open editors."""
        mods = key_modifiers(event)
        key = event.key()

        if self._flow_player is not None and self._flow_player.active:
            action = PLAYBACK_KEYS.get((key, mods))
            if action:
                self.std_run(action)
            event.accept()
            return

        # The keyboard pickers and text modes of the canvas keep their keys.
        if self._search_active:
            chord = mods & ~_SHIFT
            if event.matches(QKeySequence.StandardKey.Paste):
                text = " ".join(QApplication.clipboard().text().split())
                if text:
                    self._search_text += text
                    self._update_search_results()
                    self._update_search_badge()
            elif chord:
                pass    # Ctrl+X and the like: neither typed nor run
            else:
                self._handle_search_key(event)
            event.accept()
            return
        for active, handler in (
                (self._jump_active, self._handle_jump_key),
                (self._graph_nav_active, self._handle_graph_nav_key),
                (self._color_picker_active, self._handle_color_picker_key),
                (self._icon_picker_active, self._handle_icon_picker_key),
                (self._type_picker_active, self._handle_type_picker_key),
                (self._elem_overlay_active,
                 self._handle_element_overlay_key)):
            if active:
                handler(event)
                event.accept()
                return

        if key == Qt.Key.Key_Space and mods == _NONE:
            if not event.isAutoRepeat():
                self._std_space_held = True
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return

        bound = STANDARD_KEYS.get((key, mods))
        if bound is not None:
            action, args = bound
            self.std_run(action, **args)
            event.accept()
            return
        # Anything else — a plain letter above all — does nothing here.
        event.accept()

    def _std_key_release(self, event) -> bool:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._std_space_held = False
            if not self._std_space_panning:
                self.viewport().unsetCursor()
            return True
        return False

    # ── Mouse ──

    def _std_mouse_press(self, event) -> bool:
        """The standard scheme's own presses; False lets the view go on."""
        if (event.button() == Qt.MouseButton.LeftButton
                and self._editor is not None):
            # A click elsewhere is done with the label: keep it, and let the
            # click go on to select what it hit.
            scene_pos = self.mapToScene(event.position().toPoint())
            if not self._editor.sceneBoundingRect().contains(scene_pos):
                self._commit_editor()
        if event.button() == Qt.MouseButton.RightButton:
            self._std_context_menu(event.position())
            event.accept()
            return True
        if (event.button() == Qt.MouseButton.LeftButton
                and self._std_space_held):
            self._panning = True
            self._std_space_panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return True
        return False

    def _std_mouse_release(self, event) -> bool:
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return True
        if (event.button() == Qt.MouseButton.LeftButton
                and self._std_space_panning):
            self._panning = False
            self._std_space_panning = False
            self.setCursor(Qt.CursorShape.OpenHandCursor
                           if self._std_space_held
                           else Qt.CursorShape.ArrowCursor)
            event.accept()
            return True
        return False

    def focusOutEvent(self, event):
        # A Space let go while another window had the keys never reaches
        # the view: forget it, or every later drag would pan.
        if self._std_space_held or self._std_space_panning:
            self._std_space_held = False
            if self._std_space_panning:
                self._std_space_panning = False
                self._panning = False
            self.viewport().unsetCursor()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().focusOutEvent(event)

    def _std_double_click(self, item) -> bool:
        """Double-click on an arrow: edit its label."""
        arrow = arrow_of(item)
        if arrow is None:
            return False
        self._select_arrow(arrow)
        self._start_editing_arrow(arrow)
        return True

    def _std_click_keeps_source(self, event) -> bool:
        """True when the Arrow tool's press and release were on the source
        itself: the first of two clicks, not the end of a drag."""
        line = self._connect_line
        if line is not None:
            line.setVisible(False)
        scene_pos = self.mapToScene(event.position().toPoint())
        item = resolve_node(self._scene.itemAt(scene_pos, self.transform()))
        if line is not None:
            line.setVisible(True)
        return item is self._connect_source

    def _std_context_menu(self, view_pos):
        """Right-click: select what is under the pointer (unless it is part
        of the selection already), then open its menu."""
        from grafli.standard_ui import build_context_menu, build_playback_menu
        # Done with what was being typed before the target is picked: a
        # committed arrow label would otherwise take the selection back.
        self._commit_editor()
        self._cancel_open_picker()
        if self._last_context_menu is not None:
            from shiboken6 import isValid
            if isValid(self._last_context_menu):
                self._last_context_menu.deleteLater()
            self._last_context_menu = None
        global_pos = self.viewport().mapToGlobal(view_pos.toPoint())
        if self._flow_player is not None and self._flow_player.active:
            # Presenting hides the menu bar: the tour's own controls are here.
            menu = build_playback_menu(self)
            self._last_context_menu = menu
            menu.popup(global_pos)
            return menu
        scene_pos = self.mapToScene(view_pos.toPoint())
        raw = self._scene.itemAt(scene_pos, self.transform())
        arrow = arrow_of(raw)
        node = resolve_node(raw)
        if (arrow is not None or isinstance(node, (BoxItem, NoteItem,
                                                   ImageItem))) \
                and self.mode != Mode.SELECT:
            # A tool is active: what was right-clicked is acted on, so back
            # to Select, where it can be selected.
            self.set_mode(Mode.SELECT)
        if arrow is not None:
            if arrow not in self._selected_arrows:
                self._scene.clearSelection()
                self._select_arrow(arrow)
            target = arrow
        elif isinstance(node, (BoxItem, NoteItem, ImageItem)):
            if not node.isSelected():
                self._deselect_arrow()
                self._scene.clearSelection()
                node.setSelected(True)
            target = node
        else:
            target = None
        menu = build_context_menu(self, target, scene_pos)
        self._last_context_menu = menu
        menu.popup(global_pos)
        return menu

    def _std_on_target(self, item=None, command: str = "", **kw):
        """A right-click menu's command for the one element it was opened
        on, whatever else is selected: select that element alone, then run."""
        from shiboken6 import isValid
        if isinstance(item, Arrow):
            if self._board is None or not any(a is item
                                              for a in self._board.arrows):
                return
            self._scene.clearSelection()
            self._select_arrow(item)
        elif item is not None:
            if not isValid(item) or item.scene() is not self._scene:
                return
            self._deselect_arrow()
            self._scene.clearSelection()
            item.setSelected(True)
        self.std_run(command, **kw)

    # ── Commands ──

    def _std_escape(self):
        """Esc: drop what is open, then the selection, back to Select."""
        if self._close_doc_peek():
            return
        if self._search_filter_active:
            self._clear_search_filter()
            return
        if self._complexity_active:
            self._clear_complexity_heatmap()
            return
        if self._focus_active:
            self._clear_focus_filter()
            return
        if self._selected_arrow:
            self._deselect_arrow()
            return
        self._scene.clearSelection()
        self.set_mode(Mode.SELECT)

    def _std_nodes(self) -> list:
        return [it for it in self._scene.selectedItems()
                if isinstance(it, (BoxItem, NoteItem, ImageItem))]

    def _std_delete(self):
        """Delete what is selected: elements, arrows, or both (after Select
        all) — one undo step either way."""
        arrows = list(self._selected_arrows)
        nodes = self._std_nodes()
        if not arrows and not nodes:
            self.toast("Nothing selected to delete", "info")
            return
        if nodes and self._refuse_locked_edit():
            return
        if arrows:
            self._push_undo()
            depth = len(self._undo_stack)
            self._clear_arrow_mode()
            for arrow in arrows:
                self._board.remove_arrow(arrow)
            self._selected_arrows = []
            self._selected_arrow_items.clear()
            self._redraw_arrows()
            self.mark_dirty()
            if nodes:
                self._delete_selected()
                if len(self._undo_stack) == depth + 1:
                    self._undo_stack.pop()   # the half-way snapshot
            return
        self._delete_selected()

    def _std_copy(self):
        """Copy the selected elements (with the arrows between them). An
        arrow on its own copies its label as text — an arrow cannot be
        pasted without the boxes it connects — and the board's earlier copy
        is dropped, so Paste never brings back something else."""
        if self._std_nodes() or not self._selected_arrows:
            self._copy_selected()
            return False
        text = "\n".join(a.label for a in self._selected_arrows if a.label)
        self._clipboard_boxes, self._clipboard_notes = [], []
        self._clipboard_arrows, self._clipboard_images = [], []
        QApplication.clipboard().setText(text)
        self._copy_clip_text = ""
        self.toast("Copied the arrow's label" if text else
                   "An arrow is copied with the boxes it connects: select "
                   "them", "info")
        return True

    def _std_cut(self):
        if self._std_nodes():
            self._copy_selected()
            self._std_delete()
            return
        if self._selected_arrows:
            self._std_copy()
            self._std_delete()
            return
        self.toast("Nothing selected to cut", "warn")

    def _std_paste(self, pos: QPointF | None = None):
        """Ctrl+V pastes at the pointer, Paste here where the menu opened;
        both take the latest copy, the board's or another app's."""
        if pos is None:
            self._paste()
        else:
            self._paste_to(pos)

    def _std_duplicate(self):
        """A copy beside the selection; the clipboard keeps what it held."""
        nodes = self._std_nodes()
        if not nodes:
            self.toast("Select something to duplicate", "warn")
            return
        saved = (self._clipboard_boxes, self._clipboard_notes,
                 self._clipboard_arrows, self._clipboard_images,
                 self._copy_clip_img_fp, self._copy_clip_text)
        self._clipboard_boxes, self._clipboard_notes = [], []
        self._clipboard_arrows, self._clipboard_images = [], []
        rect = self._union_scene_rect(nodes)
        self._copy_selected()
        try:
            self._paste_at(rect.center() + QPointF(30, 30))
        finally:
            (self._clipboard_boxes, self._clipboard_notes,
             self._clipboard_arrows, self._clipboard_images,
             self._copy_clip_img_fp, self._copy_clip_text) = saved

    def _std_select_all(self):
        """Every element and every arrow: what follows (Delete, a text
        size, a colour) reaches them all."""
        self._deselect_arrow()
        if self.mode != Mode.SELECT:
            self.set_mode(Mode.SELECT)
        for items in (self._box_items, self._note_items, self._image_items):
            for item in items.values():
                if item.isVisible():
                    item.setSelected(True)
        if self._board and self._board.arrows:
            # Arrows are a selection of their own; set it after the
            # elements', whose change would otherwise clear it.
            self._selected_arrows = list(self._board.arrows)
            self._highlight_selected_arrows()

    def _std_target(self):
        """``(item, element)`` a single-target command acts on: the arrow
        last selected, or the first selected box, note or image."""
        if self._selected_arrow is not None:
            return self._selected_arrow, self._selected_arrow
        for item in self._std_nodes():
            return item, self._item_elem(item)
        return None, None

    def _std_edit_text(self):
        """Edit ▸ Edit in a window: a note's text, or the document of a
        box, image or arrow — opened when it has one, made when it has
        none."""
        item, el = self._std_target()
        if el is None:
            self.toast("Select a box, note, image or arrow", "info")
            return
        if isinstance(item, NoteItem):
            self._zen_edit_note(item)
            return
        if el.attach_kind == "doc":
            self._open_attachment(el)
            return
        if el.url and el.url.split("#")[0].endswith(".md"):
            self._open_url_string(el.url)
            return
        if self._has_attachment(el):
            self.toast("It is attached to something else: Open (Enter) "
                       "follows it, Edit ▸ Attach replaces it", "info")
            return
        self._std_attach("markdown")

    def _std_attach(self, kind: str = "markdown"):
        """Attach to the selected element: a markdown document, a sub-board
        (and go into it), or a link or file."""
        item, el = self._std_target()
        if el is None:
            self.toast("Select a box, note, image or arrow", "info")
            return
        if kind == "file":
            self._set_url()
            return
        if not getattr(self.window(), "_file_path", None):
            self.toast("Save the board first to attach a document or a "
                       "sub-board", "warn")
            return
        if isinstance(item, Arrow):
            self._create_arrow_resource(item, f"{item.from_id}--{item.to_id}",
                                        kind)
        else:
            self._create_resource(item, self._item_id(item), kind)

    def _std_rename(self):
        if self._selected_arrow is not None:
            self._start_editing_arrow(self._selected_arrow)
            return
        if not self._std_nodes():
            self.toast("Select a box, note or arrow to rename", "info")
            return
        self._edit_selected()

    def _std_open(self):
        """Enter / Open: follow the attachment; with none, offer what can
        be attached (a menu, not the vim scheme's letter picker)."""
        item, el = self._std_target()
        if el is None:
            return
        if self._has_attachment(el):
            self._open_attachment(el)
            return
        from grafli.standard_ui import build_attach_menu
        menu = build_attach_menu(self)
        if isinstance(item, Arrow):
            rect = self._union_scene_rect(list(self._selected_arrow_items))
        else:
            rect = item.sceneBoundingRect()
        at = (self.mapFromScene(rect.center()) if rect is not None
              else self.viewport().rect().center())
        self._last_context_menu = menu
        menu.popup(self.viewport().mapToGlobal(at))

    def _std_cycle_sibling(self, direction: int):
        sel = self._scene.selectedItems()
        if len(sel) == 1 and isinstance(sel[0], BoxItem):
            self._cycle_sibling(direction)

    def _std_nudge(self, dx: int = 0, dy: int = 0, big: bool = False):
        """Arrow keys: move the selection, or pan when nothing is selected."""
        nodes = self._std_nodes()
        if not nodes:
            step = 200 if big else 50
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() + dx * step)
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() + dy * step)
            return
        if self._refuse_locked_edit():
            return
        snap = self._grid_snap
        if snap:
            step = self.GRID_SPACING * (5 if big else 1)
        else:
            step = 10 if big else 1
        # Move the outermost of the selection: an item drags what it holds
        # along, so a selected child of a selected box must not move twice.
        ids = {self._item_id(it) for it in nodes}
        top = [it for it in nodes
               if not (set(self._ancestor_ids(it)) & ids)]
        # Presses in a row are one move, and one Ctrl+Z — unless an undo,
        # a redo or another edit came between them: the undo stack is then
        # no longer as the last press left it, and this press is a new step.
        import time
        now = time.monotonic()
        last_at, last_ids, last_top = self._std_last_nudge
        if not (now - last_at < _NUDGE_UNDO_WINDOW
                and last_ids == frozenset(ids)
                and self._undo_stack and self._undo_stack[-1] is last_top):
            self._push_undo()
        # The top entry itself, not its id(): held here, it cannot be freed
        # and its address handed to the next snapshot, so only this press's
        # own entry is ever the same object.
        self._std_last_nudge = (now, frozenset(ids),
                                self._undo_stack[-1] if self._undo_stack
                                else None)
        g = self.GRID_SPACING
        for item in top:
            mx, my = dx * step, dy * step
            if snap:
                # Land on the grid, as a drag does.
                px, py = item.pos().x(), item.pos().y()
                mx = round((px + mx) / g) * g - px if dx else 0
                my = round((py + my) / g) * g - py if dy else 0
                if not mx and not my:
                    mx, my = dx * g, dy * g
            item.moveBy(mx, my)
        self.arrow_update_needed.emit()
        self.mark_dirty()
        self._ensure_selection_visible()

    def _ancestor_ids(self, item) -> list[str]:
        out, seen = [], set()
        parent = self._element_parent(self._item_id(item))
        while parent and parent not in seen:
            seen.add(parent)
            out.append(parent)
            parent = self._element_parent(parent)
        return out

    def _std_snap_to_grid(self):
        if not self._std_nodes():
            self.toast("Select something to snap", "info")
            return
        self._snap_to_grid()

    def _std_view_center(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def _std_insert_box(self, pos: QPointF | None = None):
        """A new box at ``pos`` (the middle of the view), label editor open."""
        if not self._board:
            return
        pos = pos if pos is not None else self._std_view_center()
        self.set_mode(Mode.SELECT)
        self._push_undo()
        box = Box(id=self._board.next_box_id(), label="A Node",
                  x=pos.x() - DEFAULT_BOX_W / 2, y=pos.y() - DEFAULT_BOX_H / 2,
                  w=DEFAULT_BOX_W, h=DEFAULT_BOX_H,
                  color=self._last_box_color, textsize=self._last_box_textsize)
        self._board.add_box(box)
        item = BoxItem(box)
        self._scene.addItem(item)
        self._scene.addItem(item._label)
        self._box_items[box.id] = item
        self.mark_dirty()
        self._scene.clearSelection()
        item.setSelected(True)
        self._start_editing(item)

    def _std_insert_note(self, pos: QPointF | None = None):
        if not self._board:
            return
        pos = pos if pos is not None else self._std_view_center()
        self.set_mode(Mode.SELECT)
        self._push_undo()
        note = Note(id="", x=pos.x(), y=pos.y(), text="Some text ...",
                    textsize=self._last_note_textsize)
        self._board.add_note(note)
        item = NoteItem(note)
        self._scene.addItem(item)
        self._note_items[note.id] = item
        self.mark_dirty()
        self._scene.clearSelection()
        item.setSelected(True)
        self._start_editing(item)

    def _image_file_dialog(self) -> list[str]:
        """Ask for picture files (a seam tests replace)."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Insert image", "",
            "Images (*.svg *.png *.jpg *.jpeg *.gif *.webp *.bmp);;"
            "All Files (*)")
        return paths

    def _std_insert_image(self, pos: QPointF | None = None):
        paths = self._image_file_dialog()
        if not paths:
            return
        self.set_mode(Mode.SELECT)
        self._add_image_files(paths, pos if pos is not None
                              else self._std_view_center())

    def _std_connect_from(self, item=None):
        """Right-click ▸ Connect: the arrow tool, already holding ``item``."""
        from PySide6.QtGui import QPen
        from grafli import theme
        from grafli.constants import ARROW_WIDTH
        item = item or (self._std_nodes() or [None])[0]
        if item is None:
            return
        self.set_mode(Mode.CONNECT)
        self._connect_source = item
        c = self._item_center(item)
        pen = QPen(theme.ARROW_COLOR, ARROW_WIDTH, Qt.PenStyle.DashLine)
        self._connect_line = self._scene.addLine(c.x(), c.y(), c.x(), c.y(),
                                                 pen)
        self.toast("Click the box to connect to; Esc cancels")

    # ── Format ──

    def _std_set_color(self, value: str = "", status: bool = False):
        """Colour everything selected: boxes, notes and arrows alike (or the
        selected boxes' status labels)."""
        if status:
            groups = [("status", [b for b in self._color_picker_boxes()
                                  if b.box.status])]
        else:
            groups = [("box", self._color_picker_boxes()),
                      ("note", self._color_picker_notes()),
                      ("arrow", list(self._selected_arrows))]
        groups = [(mode, targets) for mode, targets in groups if targets]
        if not groups:
            self.toast("Select a box, note, or arrow" if not status
                       else "Select a box with a status label", "warn")
            return
        self._push_undo()
        for mode, targets in groups:
            for t in targets:
                self._set_target_color(mode, t, value)
            if mode == "box":
                self._last_box_color = value
        if self._selected_arrows:
            self._std_rehighlight_arrows()
        self.mark_dirty()

    def _std_rehighlight_arrows(self):
        """Redraw the arrows and keep the selected ones marked — without
        ``_select_arrow``, which would drop a selection of elements made
        alongside (Select all)."""
        self._redraw_arrows()
        self._highlight_selected_arrows()

    def _icon_dialog(self, current: str, placement: str):
        """Ask for a symbol: ``(name, placement)`` or None (a seam tests
        replace)."""
        from grafli.standard_ui import IconDialog
        icons = getattr(self._scene, "board_icons", None)
        own = icons.names() if icons is not None else []
        dlg = IconDialog(self, current, placement, own, icons)
        return dlg.choose()

    def _std_pick_icon(self, name: str | None = None, placement: str = ""):
        targets = self._icon_picker_targets()
        if not targets:
            self.toast("Select a box or note to add an icon", "warn")
            return
        if name is None:
            picked = self._icon_dialog(self._el_icon(targets[0]),
                                       self._el_placement(targets[0]))
            if picked is None:
                return
            name, placement = picked
        self._push_undo()
        for it in targets:
            it.set_icon(name, placement)
        self.arrow_update_needed.emit()
        self.mark_dirty()

    def _std_text_targets(self):
        return [it for it in self._scene.selectedItems()
                if isinstance(it, (BoxItem, NoteItem))]

    def _std_set_textsize(self, value: str = ""):
        targets = self._std_text_targets()
        arrows = list(self._selected_arrows)
        if not targets and not arrows:
            self.toast("Select a box, note or arrow", "warn")
            return
        self._push_undo()
        for it in targets:
            it.set_textsize(value)
        for a in arrows:
            a.textsize = value
        if arrows:
            self._std_rehighlight_arrows()
        self.arrow_update_needed.emit()
        self.mark_dirty()

    def _std_toggle_emphasis(self, flag: str, notes_only: bool = False):
        targets = [it for it in self._std_text_targets()
                   if not notes_only or isinstance(it, NoteItem)]
        if not targets:
            self.toast("Select a note" if notes_only else
                       "Select a box or note", "warn")
            return
        on = not all(flag in self._el_emphasis(it).split() for it in targets)
        self._push_undo()
        for it in targets:
            flags = set(self._el_emphasis(it).split())
            flags = flags | {flag} if on else flags - {flag}
            it.set_emphasis(emphasis_from_flags(flags))
        self.mark_dirty()

    def _std_set_face(self, value: str = ""):
        """The font: ``""`` hand-written (notes), ``mono``, ``sans``."""
        targets = self._std_text_targets()
        if not targets:
            self.toast("Select a box or note", "warn")
            return
        self._push_undo()
        for it in targets:
            if isinstance(it, NoteItem):
                it.set_face(value)
            else:
                it.set_sans(value == "sans")
        self.arrow_update_needed.emit()
        self.mark_dirty()

    def std_axes(self) -> tuple[str, list]:
        """``(target, axes)`` the Appearance menu offers for the selection,
        the same rows the vim scheme's ``s e`` panel has."""
        if self._selected_arrows:
            target, make = "arrow", self._connector_axes
        elif self._color_picker_boxes():
            target, make = "box", self._box_axes
        elif self._color_picker_notes():
            target, make = "note", self._note_axes
        elif self._selected_image_items():
            target, make = "image", self._image_axes
        else:
            return "", []
        kind = self._elem_overlay_kind
        self._elem_overlay_kind = "appearance"
        self._elem_overlay_target = target
        try:
            return target, make()
        finally:
            self._elem_overlay_target = ""
            self._elem_overlay_kind = kind

    def _std_set_axis(self, row: int = 0, value=None):
        """Set appearance row ``row`` of the selection to ``value``."""
        target, axes = self.std_axes()
        if not axes or row >= len(axes):
            self.toast("Select a box, note, image, or arrow", "warn")
            return
        axis = axes[row]
        if not axis.get("enabled", True):
            self.toast("The icon decides where this label sits", "info")
            return
        self._push_undo()
        self._elem_overlay_target = target
        self._elem_overlay_original = {}
        try:
            axis["set"](value)
            self._refresh_after_elem_overlay()
        finally:
            self._elem_overlay_target = ""
        self.mark_dirty()

    def _std_edit_status(self):
        boxes = self._color_picker_boxes()
        if not boxes:
            self.toast("Only boxes carry a status label", "warn")
            return
        raw, ok = self._status_dialog(boxes[0].box.status)
        if not ok:
            return
        status = self._status_token(raw)
        self._push_undo()
        for item in boxes:
            item.set_status(status, item.box.status_color)
        self.mark_dirty()
        if status:
            self.toast("Its colour: Format ▸ Status colour")

    def _std_toggle_arrow_kind(self):
        primary = self._selected_arrow
        if primary is None:
            self.toast("Select an arrow", "warn")
            return
        self._push_undo()
        new_kind = ("graph" if self._is_annotation_link(primary)
                    else "annotation")
        for a in self._selected_arrows:
            a.kind = new_kind
        self._last_connector_kind = new_kind
        self._redraw_arrows()
        self._select_arrow(self._selected_arrow, keep_mode=True)
        self.mark_dirty()
        self.toast("Graph edge" if new_kind == "graph" else "Annotation")

    # ── Navigate ──

    def std_neighbours(self, item) -> list[tuple[str, str, str]]:
        """``(direction, element id, label)`` of what ``item``'s arrows reach."""
        if not self._board or item is None:
            return []
        own = self._item_id(item)
        out = []
        for a in self._board.arrows:
            if a.from_id == own and a.to_id != own:
                out.append(("→", a.to_id))
            elif a.to_id == own and a.from_id != own:
                out.append(("←", a.from_id))
        named = []
        for direction, eid in out:
            el = (self._board.box_by_id(eid) if hasattr(self._board,
                                                       "box_by_id") else None)
            label = (el.label if el is not None and el.label else eid)
            named.append((direction, eid, label.split("\n")[0]))
        return named

    def _std_follow(self, target_id: str = ""):
        """Select the element ``target_id`` (one an arrow leads to) and show
        it."""
        item = (self._box_items.get(target_id)
                or self._note_items.get(target_id)
                or self._image_items.get(target_id))
        if item is None:
            if not target_id:
                self.toast("Right-click a box and pick where its arrows lead",
                           "info")
            return
        self._deselect_arrow()
        self._scene.clearSelection()
        item.setSelected(True)
        self._ensure_selection_visible()

    def _std_focus_connections(self):
        """Show only what touches the selected box; again to stop."""
        if self._focus_active:
            self._clear_focus_filter()
            return
        selected = self._scene.selectedItems()
        if len(selected) != 1 or not isinstance(selected[0], BoxItem):
            self.toast("Select a single box to focus its connections", "warn")
            return
        if self._complexity_active:
            self._clear_complexity_heatmap()
        self._focus_active = True
        self._focus_node_id = selected[0].box.id
        self._focus_direction = "all"
        self._focus_depth = 0
        self._apply_focus_filter()

    def _std_focus_depth(self):
        if not self._focus_active:
            self.toast("Focus on a box's connections first", "warn")
            return
        self._focus_depth = 0 if self._focus_depth == 1 else 1
        self._apply_focus_filter()

    # ── Tours ──

    def _std_player(self, method: str):
        player = self._flow_player
        if player is None or not player.active:
            self.toast("No tour is playing", "info")
            return
        getattr(player, method)()

    def _std_play_open(self):
        el = self._selected_board_link()
        if el is not None:
            self._open_attachment(el)
