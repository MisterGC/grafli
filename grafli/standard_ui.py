"""The standard control scheme's widgets (#352).

The menu bar, the toolbar and the right-click menus of the standard scheme
(:mod:`grafli.controls`), the dialog that asks for a scheme on the first
start, the icon picker the Format menu opens, and the two text editors that
stand in for textli's vim editors: a plain inline field for notes and a
plain text window for long texts.

Every menu item is a ``QAction`` whose object name is the command it runs
through :meth:`grafli.view.standard.StandardMixin.std_run`, so a test can
find an item by what the documentation calls it and check what it does.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QIcon, QKeySequence,
                           QPainter, QPixmap, QTextCursor)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from grafli import controls, theme

# id -> (text, shortcuts, a plain key the canvas answers: shown beside the
# item, never bound by the menu).
# The texts are what the documentation calls the items (keymap.py's
# ``Menu ▸ Item`` rows); tests hold the two together.
ACTIONS: dict[str, tuple[str, tuple[str, ...], str]] = {
    # File
    "new_board": ("New board", ("Ctrl+N",), ""),
    "open": ("Open…", ("Ctrl+O",), ""),
    "save": ("Save", ("Ctrl+S",), ""),
    "switch_board": ("Switch board…", (), ""),
    "last_board": ("Last board", (), ""),
    "close_board": ("Close board", ("Ctrl+W",), ""),
    "export_png": ("Copy as PNG", ("Ctrl+Shift+C",), ""),
    "export_svg": ("SVG…", ("Ctrl+E",), ""),
    "export_pdf": ("Flow as PDF…", (), ""),
    "export_pptx": ("Flow as PowerPoint…", (), ""),
    "export_html": ("HTML page…", (), ""),
    "quit": ("Quit", ("Ctrl+Q",), ""),
    # Edit
    "undo": ("Undo", ("Ctrl+Z",), ""),
    "redo": ("Redo", ("Ctrl+Shift+Z", "Ctrl+Y"), ""),
    "cut": ("Cut", ("Ctrl+X",), ""),
    "copy": ("Copy", ("Ctrl+C",), ""),
    "paste": ("Paste", ("Ctrl+V",), ""),
    "duplicate": ("Duplicate", ("Ctrl+D",), ""),
    "delete": ("Delete", (), "Del"),
    "select_all": ("Select all", ("Ctrl+A",), ""),
    "find": ("Find…", ("Ctrl+F",), ""),
    "rename": ("Rename", (), "F2"),
    "edit_text": ("Edit in a window", (), ""),
    "set_link": ("Link…", ("Ctrl+K",), ""),
    "open_attachment": ("Open", (), "Enter"),
    # Insert / tools
    "tool_select": ("Select", (), "Esc"),
    "tool_box": ("Box", (), ""),
    "tool_note": ("Note", (), ""),
    "tool_connect": ("Arrow", (), ""),
    "insert_image": ("Image…", (), ""),
    "tool_mockup": ("Mockup", (), ""),
    "group": ("Group in a box", ("Ctrl+G",), ""),
    # Format
    "icon": ("Icon…", (), ""),
    "bold": ("Bold", ("Ctrl+B",), ""),
    "italic": ("Italic", ("Ctrl+I",), ""),
    "outline": ("Outline letters (notes)", (), ""),
    "shadow": ("Shadow (notes)", (), ""),
    "text_bigger": ("Bigger", ("Ctrl+]",), ""),
    "text_smaller": ("Smaller", ("Ctrl+[",), ""),
    "round": ("Round shape", (), ""),
    "status": ("Status label…", (), ""),
    "arrow_kind": ("Arrow kind", (), ""),
    # Arrange
    "layout": ("Auto-layout", (), ""),
    "snap_grid": ("Snap to grid", (), ""),
    "slide_ratio": ("Slide ratio", (), ""),
    # View
    "zoom_in": ("Zoom in", ("Ctrl++", "Ctrl+="), ""),
    "zoom_out": ("Zoom out", ("Ctrl+-",), ""),
    "zoom_fit": ("Zoom to fit", ("Ctrl+0",), ""),
    "zoom_selection": ("Zoom to selection", (), ""),
    "grid": ("Grid", (), ""),
    "minimap": ("Minimap", (), ""),
    "legend": ("Legend", (), ""),
    "lod": ("Level of detail", (), ""),
    "dim_notes": ("Dim notes", (), ""),
    "dim_arrows": ("Dim arrows", (), ""),
    "heatmap": ("Connectivity heatmap", (), ""),
    "focus_connections": ("Focus on connections", (), ""),
    "focus_depth": ("Focus: one hop ⇄ all", (), ""),
    "tools_panel": ("Tools panel", (), ""),
    "theme": ("Light / dark theme", ("Ctrl+Shift+D",), ""),
    # Go
    "go_into": ("Into the box's board", (), ""),
    "go_up": ("Back up", ("Alt+Up",), ""),
    "nav_back": ("Back", ("Alt+Left",), ""),
    "nav_forward": ("Forward", ("Alt+Right",), ""),
    "parent_box": ("Parent box", (), ""),
    "first_child": ("First child", (), ""),
    "next_sibling": ("Next sibling", (), "Tab"),
    "prev_sibling": ("Previous sibling", (), "Shift+Tab"),
    "peek_doc": ("Read the doc", (), ""),
    # Tours
    "bookmark": ("Bookmark the view", (), ""),
    "bookmark_viewport": ("Bookmark the exact viewport", (), ""),
    "record_flow": ("Record a flow", (), ""),
    "auto_flow": ("Auto-flow from the box", (), ""),
    "tours_through": ("Tours through the box", (), ""),
    "edit_flows": ("Edit flows", (), ""),
    "present": ("Present", ("F5",), ""),
    "play_mode": ("Play, pause, loop", (), ""),
    "play_transition": ("Smooth camera", (), ""),
    # Help
    "help": ("Help", ("F1",), ""),
    "at_a_glance": ("grafli at a glance", (), ""),
}

# The commands that sit on the menu bar's menus, in order ("-" a line,
# ("sub", id, title) a submenu filled by ``_SUBMENUS``).
MENUS: tuple[tuple[str, tuple], ...] = (
    ("File", ("new_board", "open", "save", "-", "switch_board", "last_board",
              "close_board", "-", ("sub", "export_menu", "Export"), "-",
              "quit")),
    ("Edit", ("undo", "redo", "-", "cut", "copy", "paste", "duplicate",
              "delete", "-", "select_all", "find", "-", "rename",
              "edit_text", "set_link", ("sub", "attach", "Attach"),
              "open_attachment")),
    ("Insert", ("tool_box", "tool_note", "insert_image", "tool_mockup",
                "tool_connect", "-", ("sub", "connected_box", "Connected box"),
                "group")),
    ("Format", (("sub", "color", "Colour"), "icon",
                ("sub", "text_menu", "Text"),
                ("sub", "appearance", "Appearance"), "round", "-", "status",
                ("sub", "status_color", "Status colour"), "-",
                "arrow_kind")),
    ("Arrange", ("layout", "snap_grid", "slide_ratio", "-", "group")),
    ("View", ("zoom_in", "zoom_out", "zoom_fit", "zoom_selection", "-",
              "grid", "minimap", "legend", "lod", "-", "dim_notes",
              "dim_arrows", "heatmap", "focus_connections", "focus_depth",
              "-", "tools_panel", "theme")),
    ("Go", ("go_into", "go_up", "-", "nav_back", "nav_forward", "-",
            "parent_box", "first_child", "next_sibling", "prev_sibling", "-",
            "peek_doc")),
    ("Tours", ("bookmark", "bookmark_viewport", "record_flow", "auto_flow",
               "tours_through", "edit_flows", "-", "present", "play_mode",
               "play_transition")),
    ("Help", ("help", "at_a_glance", "-",
              ("sub", "scheme_menu", "Control scheme"))),
)

TOOLBAR = ("tool_select", "tool_box", "tool_note", "tool_connect",
           "insert_image", "tool_mockup", "-", "undo", "redo", "delete", "-",
           ("sub", "color", "Colour"), "icon", ("sub", "text_menu", "Text"),
           "-", "layout", "zoom_fit", "-", "open", "save",
           ("sub", "export_menu", "Export"))

TOOL_MODES = {"tool_select": "select", "tool_box": "rect",
              "tool_note": "text", "tool_connect": "connect",
              "tool_mockup": "image"}

TEXT_SIZES = (("Small", "small"), ("Medium", ""), ("Large", "large"),
              ("XL", "xlarge"), ("2XL", "xxlarge"), ("3XL", "xxxlarge"),
              ("4XL", "4xl"))
FACES = (("Hand-written (notes)", ""), ("Mono", "mono"), ("Sans", "sans"))
ATTACH = (("Markdown document", "markdown"), ("Sub-board", "grafli"),
          ("Link or file…", "file"))
CONNECTED = (("Right", "right"), ("Below", "down"), ("Left", "left"),
             ("Above", "up"))


def with_key(text: str, key: str) -> str:
    """``text`` with the plain key the canvas answers shown beside it.

    Only off macOS: there a native menu item turns the words after a tab
    into a real key equivalent, and Delete or Enter typed into a label
    would run the menu's command instead of editing the text."""
    if not key or sys.platform == "darwin":
        return text
    return f"{text}\t{key}"


def action_label(action_id: str) -> str:
    """The menu words for ``action_id``, with its key beside them."""
    text, shortcuts, shown = ACTIONS[action_id]
    key = shown or (QKeySequence(shortcuts[0]).toString(
        QKeySequence.SequenceFormat.NativeText) if shortcuts else "")
    return with_key(text, key)


def clean_text(text: str) -> str:
    """A menu item's words: no ``&`` mnemonic, no shown key, no ``…``."""
    return text.split("\t")[0].replace("&", "").rstrip("…").strip()


def _swatch(value: str) -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    hexv = theme.resolve_color(value) if value else ""
    p.setPen(QColor(0, 0, 0, 110))
    p.setBrush(QColor(hexv) if hexv else QColor(theme.BOX_FILL))
    p.drawRoundedRect(1, 1, 14, 14, 3, 3)
    if not hexv:
        p.setPen(QColor(150, 60, 60))
        p.drawLine(4, 12, 12, 4)
    p.end()
    return QIcon(pm)


class StandardActions:
    """The standard scheme's actions for one window and its view: made
    once, shared by the menu bar, the toolbar and the right-click menus."""

    def __init__(self, window, view):
        self.window = window
        self.view = view
        self.actions: dict[str, QAction] = {}
        for action_id, (text, shortcuts, shown) in ACTIONS.items():
            act = QAction(with_key(text, shown), window)
            # A toolbar button shows the words alone, not the menu's key.
            act.setIconText(clean_text(text))
            act.setObjectName(action_id)
            if shortcuts:
                act.setShortcuts([QKeySequence(s) for s in shortcuts])
            act.triggered.connect(
                lambda _=False, a=action_id: self.run(a))
            self.actions[action_id] = act
        self.actions["at_a_glance"].triggered.disconnect()
        self.actions["at_a_glance"].triggered.connect(
            lambda: view._open_help_page())
        self.tools = QActionGroup(window)
        self.tools.setExclusive(True)
        for action_id in TOOL_MODES:
            act = self.actions[action_id]
            act.setCheckable(True)
            self.tools.addAction(act)
        self.actions["tool_select"].setChecked(True)

    def run(self, action_id: str, **kw):
        self.view.std_run(action_id, **kw)

    def sync_mode(self, mode) -> None:
        for action_id, value in TOOL_MODES.items():
            if value == mode.value:
                self.actions[action_id].setChecked(True)

    def add(self, menu, entry, *, context=None):
        """Put ``entry`` (an id, ``"-"`` or a submenu) on ``menu``."""
        if entry == "-":
            menu.addSeparator()
            return
        if isinstance(entry, tuple):
            _, sub_id, title = entry
            sub = menu.addMenu(title)
            sub.setObjectName(sub_id)
            sub.menuAction().setObjectName(sub_id)
            sub.aboutToShow.connect(
                lambda s=sub, i=sub_id: self.fill(s, i, context))
            self.fill(sub, sub_id, context)
            return sub
        menu.addAction(self.actions[entry])

    # ── Submenus, filled each time they open ──

    def _item(self, menu, text: str, obj_name: str, action_id: str,
              checked: bool | None = None, icon=None, **kw):
        act = menu.addAction(text)
        act.setObjectName(obj_name)
        if icon is not None:
            act.setIcon(icon)
        if checked is not None:
            act.setCheckable(True)
            act.setChecked(checked)
        act.triggered.connect(lambda _=False: self.run(action_id, **kw))
        return act

    def fill(self, menu: QMenu, sub_id: str, context=None) -> None:
        # Submenus the last fill made would outlive the items clear() frees.
        for old in menu.findChildren(
                QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly):
            old.deleteLater()
        menu.clear()
        view = self.view
        if sub_id == "export_menu":
            for a in ("export_png", "export_svg", "export_pdf", "export_pptx",
                      "export_html"):
                menu.addAction(self.actions[a])
        elif sub_id in ("color", "status_color"):
            status = sub_id == "status_color"
            for label, value in view._color_choices():
                if value is None:
                    continue
                self._item(menu, label or value, f"color:{value}", "color",
                           icon=_swatch(value), value=value, status=status)
        elif sub_id == "text_menu":
            current = self._current_textsize()
            for label, value in TEXT_SIZES:
                self._item(menu, label, f"textsize:{value}", "textsize",
                           checked=(value == current), value=value)
            menu.addSeparator()
            for a in ("bold", "italic", "outline", "shadow", "-",
                      "text_bigger", "text_smaller"):
                if a == "-":
                    menu.addSeparator()
                else:
                    menu.addAction(self.actions[a])
            faces = menu.addMenu("Font")
            faces.setObjectName("face")
            for label, value in FACES:
                self._item(faces, label, f"face:{value}", "face", value=value)
        elif sub_id == "appearance":
            _target, axes = view.std_axes()
            if not axes:
                none = menu.addAction("Select a box, note, image or arrow")
                none.setEnabled(False)
            for row, axis in enumerate(axes):
                sub = menu.addMenu(axis["label"])
                sub.setObjectName(f"axis:{row}")
                sub.setEnabled(axis.get("enabled", True))
                cur = axis["get"]()
                for label, value in axis["options"]:
                    shown = label if isinstance(label, str) else str(label)
                    self._item(sub, shown, f"axis:{row}:{shown}", "axis",
                               checked=(value == cur), row=row, value=value)
        elif sub_id == "connected_box":
            for label, direction in CONNECTED:
                if context is not None:
                    self._item(menu, label, f"connected_box:{direction}",
                               "on_target", item=context,
                               command="connected_box", direction=direction)
                else:
                    self._item(menu, label, f"connected_box:{direction}",
                               "connected_box", direction=direction)
        elif sub_id == "attach":
            for label, kind in ATTACH:
                if context is not None:
                    self._item(menu, label, f"attach:{kind}", "on_target",
                               item=context, command="attach", kind=kind)
                else:
                    self._item(menu, label, f"attach:{kind}", "attach",
                               kind=kind)
        elif sub_id == "follow_arrow":
            for direction, eid, label in view.std_neighbours(context):
                self._item(menu, f"{direction} {label}", f"follow:{eid}",
                           "follow_arrow", target_id=eid)
        elif sub_id == "scheme_menu":
            for name in controls.SCHEMES:
                self._item(menu, controls.TITLES[name], f"scheme:{name}",
                           "scheme", checked=(controls.scheme() == name),
                           name=name)

    def _current_textsize(self) -> str | None:
        items = self.view._std_text_targets()
        if items:
            return self.view._el_textsize(items[0])
        if self.view._selected_arrow is not None:
            return self.view._selected_arrow.textsize
        return None


def build_menus(acts: StandardActions, parent) -> list[QMenu]:
    """The menu bar's menus, owned by ``parent`` so they outlive being
    taken off the menu bar."""
    menus = []
    for title, entries in MENUS:
        menu = QMenu(title, parent)
        menu.setObjectName(f"menu:{title}")
        for entry in entries:
            acts.add(menu, entry)
        menus.append(menu)
    return menus


def build_toolbar(acts: StandardActions, window) -> QToolBar:
    bar = QToolBar("Tools", window)
    bar.setObjectName("standard_toolbar")
    bar.setMovable(False)
    bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    for entry in TOOLBAR:
        if entry == "-":
            bar.addSeparator()
        elif isinstance(entry, tuple):
            _, sub_id, title = entry
            menu = QMenu(title, bar)
            menu.setObjectName(sub_id)
            menu.aboutToShow.connect(
                lambda m=menu, i=sub_id: acts.fill(m, i))
            acts.fill(menu, sub_id)
            act = menu.menuAction()
            act.setObjectName(sub_id)
            bar.addAction(act)
            button = bar.widgetForAction(act)
            if isinstance(button, QToolButton):
                button.setPopupMode(
                    QToolButton.ToolButtonPopupMode.InstantPopup)
        else:
            bar.addAction(acts.actions[entry])
    for w in bar.findChildren(QWidget):
        w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return bar


def build_context_menu(view, target, scene_pos) -> QMenu:
    """The right-click menu for ``target`` (a box, note or image item, an
    arrow, or None for the empty canvas at ``scene_pos``).

    A command for one element (Rename, Open, Connect from here …) acts on
    the element right-clicked, even with others selected; one for many
    (Delete, Colour …) on the whole selection, which the right-click joined.
    """
    from grafli.format import Arrow
    from grafli.items import BoxItem, ImageItem, NoteItem
    acts = _actions_for(view)
    menu = QMenu(view)
    menu.setObjectName("context_menu")
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def item(text, obj_name, action_id, **kw):
        return acts._item(menu, text, obj_name, action_id, **kw)

    def single(action_id, text=None):
        return acts._item(menu, text or action_label(action_id), action_id,
                          "on_target", item=target, command=action_id)

    def add(*entries):
        for e in entries:
            acts.add(menu, e, context=target)

    if isinstance(target, Arrow):
        menu.setTitle("Arrow")
        single("rename", with_key("Edit label", "F2"))
        single("edit_text")
        add(("sub", "attach", "Attach"))
        if view._has_attachment(target):
            single("open_attachment")
        add("-", ("sub", "color", "Colour"),
            ("sub", "text_menu", "Text"), ("sub", "appearance", "Appearance"),
            "arrow_kind", "-", "copy", "cut", "delete")
    elif isinstance(target, (BoxItem, NoteItem, ImageItem)):
        is_box = isinstance(target, BoxItem)
        single("rename", with_key(
            "Rename" if is_box else "Edit text"
            if isinstance(target, NoteItem) else "Edit the image file", "F2"))
        single("edit_text")
        single("set_link")
        add(("sub", "attach", "Attach"))
        if view._has_attachment(view._item_elem(target)):
            single("open_attachment")
        add("-", "cut", "copy", "paste", "duplicate", "delete", "-",
            ("sub", "color", "Colour"))
        if not isinstance(target, ImageItem):
            add("icon", ("sub", "text_menu", "Text"))
        add(("sub", "appearance", "Appearance"))
        if is_box:
            add("round", "status")
        menu.addSeparator()
        single("connect_from", "Connect from here")
        add(("sub", "connected_box", "Connected box"))
        if view.std_neighbours(target):
            add(("sub", "follow_arrow", "Follow an arrow"))
        add("group", "-")
        if is_box and target.box.attach_kind == "graph":
            single("go_into")
        single("parent_box")
        single("zoom_selection")
        if is_box:
            single("focus_connections")
            single("peek_doc")
    else:
        item("Paste here", "paste_here", "paste", pos=scene_pos)
        item("New box here", "insert_box", "insert_box", pos=scene_pos)
        item("New note here", "insert_note", "insert_note", pos=scene_pos)
        item("Image here…", "insert_image_here", "insert_image",
             pos=scene_pos)
        add("-", "select_all", "zoom_fit", "-", "undo", "redo")
    return menu


def _actions_for(view) -> "StandardActions":
    acts = getattr(view.window(), "_std", None)
    return acts if isinstance(acts, StandardActions) \
        else StandardActions(view, view)


def build_attach_menu(view) -> QMenu:
    """Open on an element with nothing attached: what can be attached."""
    acts = _actions_for(view)
    menu = QMenu(view)
    menu.setObjectName("attach")
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    head = menu.addAction("Nothing attached yet — attach:")
    head.setEnabled(False)
    for label, kind in ATTACH:
        acts._item(menu, label, f"attach:{kind}", "attach", kind=kind)
    return menu


def build_playback_menu(view) -> QMenu:
    """Right-click while a tour plays (the menu bar is hidden presenting)."""
    acts = _actions_for(view)
    menu = QMenu(view)
    menu.setObjectName("playback_menu")
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    player = view._flow_player
    mode = {"paused": "paused", "playing": "playing",
            "loop": "playing in a loop"}.get(player.mode, player.mode)
    for text, name, action in (
            ("Next stop", "play_next", "play:next"),
            ("Previous stop", "play_prev", "play:prev"),
            (f"Play, pause, loop (now {mode})", "play_mode", "play_mode"),
            ("Smooth camera" + (" (on)" if player.smooth else " (off)"),
             "play_transition", "play_transition"),
            ("Stop the tour", "play_stop", "play:stop")):
        acts._item(menu, text, name, action)
    return menu


# ── The first start ─────────────────────────────────────────────────

class SchemeDialog(QDialog):
    """Asks once, on the first start, which control scheme to use."""

    def __init__(self, parent=None, current: str = ""):
        super().__init__(parent)
        self.setWindowTitle("How do you want to work in grafli?")
        self.choice = current or controls.STANDARD
        layout = QVBoxLayout(self)
        intro = QLabel("Pick how you control grafli. You can switch at any "
                       "time without losing your board: Help ▸ Control "
                       "scheme, the Tools panel, or the F1 help. Closing "
                       f"this keeps {controls.TITLES[self.choice]}.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for name in (controls.STANDARD, controls.VIM):
            btn = QPushButton(f"{controls.TITLES[name]}\n"
                              f"{controls.BLURBS[name]}")
            btn.setObjectName(f"scheme_{name}")
            btn.setMinimumHeight(72)
            btn.setStyleSheet("text-align: left; padding: 10px;")
            btn.clicked.connect(lambda _=False, n=name: self._pick(n))
            btn.setDefault(name == self.choice)
            layout.addWidget(btn)
        self.resize(520, 260)

    def _pick(self, name: str):
        self.choice = name
        self.accept()


# ── Icons ───────────────────────────────────────────────────────────

class IconDialog(QDialog):
    """Pick a symbol for the selection with the mouse: the built-in icons
    and the board's own, where the symbol sits, or a number badge."""

    PLACEMENTS = (("Fill the box", ""), ("Before the label", "lead"),
                  ("Corner badge", "badge"))

    def __init__(self, parent, current: str = "", placement: str = "",
                 own: list[str] | None = None, icons=None):
        super().__init__(parent)
        from grafli.format import SOLID_NUMBER_PREFIX
        from grafli.iconset import ICON_NAMES, icon_pixmap, number_badge
        self._solid_prefix = SOLID_NUMBER_PREFIX
        self.setWindowTitle("Icon")
        self.resize(520, 480)
        layout = QVBoxLayout(self)
        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Filter icons…")
        layout.addWidget(self.filter)
        self.grid = QListWidget(self)
        self.grid.setObjectName("icons")
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(QSize(32, 32))
        self.grid.setGridSize(QSize(88, 64))
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        ink = QColor(theme.INK)
        for name in [""] + list(ICON_NAMES) + list(own or []):
            it = QListWidgetItem(name or "none")
            it.setData(Qt.ItemDataRole.UserRole, name)
            pm = icon_pixmap(name, ink, 32, icons=icons) if name else None
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.grid.addItem(it)
            if name == current:
                self.grid.setCurrentItem(it)
        layout.addWidget(self.grid, 1)

        row = QHBoxLayout()
        self.placement = QComboBox(self)
        for label, value in self.PLACEMENTS:
            self.placement.addItem(label, value)
        idx = [v for _, v in self.PLACEMENTS].index(placement) \
            if placement in [v for _, v in self.PLACEMENTS] else 0
        self.placement.setCurrentIndex(idx)
        row.addWidget(QLabel("Sits:"))
        row.addWidget(self.placement)
        row.addStretch(1)
        # A number badge is its own choice: 0 is a number like any other.
        self.badge = QCheckBox("Number badge", self)
        self.number = QSpinBox(self)
        self.number.setRange(0, 99)
        self.filled = QCheckBox("filled", self)
        badge = number_badge(current) if current else None
        if badge:
            self.badge.setChecked(True)
            self.number.setValue(int(badge[0]))
            self.filled.setChecked(badge[1])
        self.number.valueChanged.connect(
            lambda _v: self.badge.setChecked(True))
        row.addWidget(self.badge)
        row.addWidget(self.number)
        row.addWidget(self.filled)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.filter.textChanged.connect(self._apply_filter)
        self.grid.itemClicked.connect(
            lambda _it: self.badge.setChecked(False))
        self.grid.itemDoubleClicked.connect(lambda _it: self.accept())

    def _apply_filter(self, text: str):
        t = text.lower()
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def value(self) -> tuple[str, str]:
        place = self.placement.currentData() or ""
        if self.badge.isChecked():
            prefix = self._solid_prefix if self.filled.isChecked() else ""
            return prefix + str(self.number.value()), place
        it = self.grid.currentItem()
        name = it.data(Qt.ItemDataRole.UserRole) if it is not None else ""
        return name, place

    def choose(self) -> tuple[str, str] | None:
        return self.value() if self.exec() == QDialog.DialogCode.Accepted \
            else None


# ── Text without vim ────────────────────────────────────────────────

def _is_ctrl_enter(event) -> bool:
    return (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))


class PlainInlineEditor(QPlainTextEdit):
    """The inline note editor without vim: a plain Qt text field, with the
    signals and sizing the canvas expects of textli's inline editor. Enter
    is a new line; Ctrl/⌘+Enter, Esc or a click elsewhere keep the text."""

    committed = Signal(str)
    cancelled = Signal()

    # Vertical chrome around the lines: document margin (4) + the host
    # stylesheet's border (1) and padding (4), top and bottom.
    _CHROME = 18

    def __init__(self, text: str = "", *, markdown: bool = False,
                 font=None, commit_on_focus_out: bool = True,
                 max_lines: int = 24, parent=None):
        super().__init__(parent)
        self._done = False
        self._commit_on_focus_out = commit_on_focus_out
        self._max_lines = max_lines
        if font is not None:
            self.setFont(font)
        self.setPlainText(text)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._highlighter = None
        if markdown:
            try:   # colour only; the field has no modes either way
                from textli.highlight import MarkdownHighlighter
            except ImportError:
                MarkdownHighlighter = None
            if MarkdownHighlighter is not None:
                self._highlighter = MarkdownHighlighter(self.document())
                self._highlighter.set_focus_enabled(False)
                if font is not None:
                    self._highlighter.set_base_size(font.pointSize())
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.document().documentLayout().documentSizeChanged.connect(
            self._autosize)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, 24)

    def fit_to_width(self, width: int):
        self.resize(width, self.height())
        self._autosize()

    def _autosize(self, *_):
        n_lines = max(self.document().size().height(), 1)
        line_h = self.fontMetrics().lineSpacing()
        wanted = min(n_lines, self._max_lines) * line_h + self._CHROME
        wanted = max(int(wanted), int(line_h + self._CHROME))
        if wanted != self.height():
            self.resize(self.width(), wanted)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape or _is_ctrl_enter(event):
            self.commit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self._commit_on_focus_out:
            self.commit()

    def commit(self):
        if not self._done:
            self._done = True
            self.committed.emit(self.toPlainText())

    def cancel(self):
        if not self._done:
            self._done = True
            self.cancelled.emit()


class _PlainField(QPlainTextEdit):
    """The text window's field: its own keys win over the window's
    shortcuts (Ctrl+S saves the text, not the board)."""

    save_requested = Signal()
    done_requested = Signal()

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride and (
                e.matches(QKeySequence.StandardKey.Save)
                or e.key() == Qt.Key.Key_Escape or _is_ctrl_enter(e)):
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Save):
            self.save_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape or _is_ctrl_enter(event):
            self.done_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PlainTextWindow(QWidget):
    """Long text without vim: a note's text or a markdown file, in a plain
    field over the window. Done (Esc, Ctrl/⌘+Enter) keeps it, Cancel drops
    what was typed since the last save, Ctrl/⌘+S saves and keeps writing.

    It speaks the zen editor's signals, so the canvas treats both alike."""

    finished = Signal(str)
    cancelled = Signal()
    applied = Signal(str)
    file_saved = Signal(Path)

    def __init__(self, parent: QWidget, text: str, title: str = "",
                 file_path: Path | None = None):
        super().__init__(parent)
        self.setObjectName("plain_text_window")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._file_path = file_path
        # What the file holds as far as this window knows: Done writes only
        # when the text differs, so an agent's edit to the file meanwhile is
        # not overwritten by an unchanged copy.
        self._saved_text = text
        self._done = False
        self.setStyleSheet(
            f"#plain_text_window {{ background: {theme.HELP_BG.name()}; }}"
            f" QLabel {{ color: {theme.HELP_FG.name()}; }}"
            f" QPlainTextEdit {{ background: {theme.EDITOR_BG.name()};"
            f" color: {theme.INK.name()};"
            f" border: 1px solid {theme.EDITOR_BORDER.name()};"
            " padding: 8px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 24, 48, 24)
        head = QLabel(title or (file_path.name if file_path else "Text"))
        f = head.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        head.setFont(f)
        layout.addWidget(head)
        self.field = _PlainField(self)
        self.field.setPlainText(text)
        font = self.field.font()
        font.setPointSize(14)
        self.field.setFont(font)
        layout.addWidget(self.field, 1)
        hint = QLabel("Esc or Ctrl/⌘+Enter: done, the text is kept · "
                      "Ctrl/⌘+S: save · Cancel: drop the changes")
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        save = QPushButton("Save", self)
        save.setObjectName("save")
        save.clicked.connect(self.save)
        cancel = QPushButton("Cancel", self)
        cancel.setObjectName("cancel")
        cancel.clicked.connect(self.cancel)
        done = QPushButton("Done", self)
        done.setObjectName("done")
        done.setDefault(True)
        done.clicked.connect(self.done)
        for b in (save, cancel, done):
            row.addWidget(b)
        layout.addLayout(row)
        self.field.save_requested.connect(self.save)
        self.field.done_requested.connect(self.done)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self.field.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def text(self) -> str:
        return self.field.toPlainText()

    def _write(self) -> bool:
        """Write the text to the file; False (and a word why) if it cannot
        be written — the window stays open with the text."""
        text = self.text()
        try:
            self._file_path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Could not save",
                                f"{self._file_path}:\n{exc.strerror or exc}")
            return False
        self._saved_text = text
        self.file_saved.emit(self._file_path)
        return True

    def save(self):
        if self._file_path is not None:
            if self.text() != self._saved_text:
                self._write()
        else:
            self.applied.emit(self.text())

    def done(self):
        if self._done:
            return
        if (self._file_path is not None and self.text() != self._saved_text
                and not self._write()):
            return
        self._done = True
        self.finished.emit(self.text())
        super().close()

    def cancel(self):
        if self._done:
            return
        self._done = True
        self.cancelled.emit()
        super().close()

    def closeEvent(self, event):
        # Closed from outside (the canvas cancels what is open): keep the
        # text, as a click elsewhere keeps a note's. A file that cannot be
        # written loses nothing silently: the window says so and stays.
        if not self._done:
            self.done()
            if not self._done:
                event.ignore()
                return
        super().closeEvent(event)
