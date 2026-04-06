"""Hideable side panel with graphical tool buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from grafli.constants import (
    BOX_BORDER,
    FONT_FAMILY,
    SIDE_PANEL_BG,
    SIDE_PANEL_BORDER,
    SIDE_PANEL_BTN_ACTIVE,
    SIDE_PANEL_BTN_HOVER,
    SIDE_PANEL_SECTION_COLOR,
    SIDE_PANEL_SHORTCUT_COLOR,
    SIDE_PANEL_TOGGLE_BG,
    SIDE_PANEL_TOGGLE_BORDER,
    SIDE_PANEL_TOGGLE_MARGIN,
    SIDE_PANEL_TOGGLE_SIZE,
    SIDE_PANEL_WIDTH,
    Mode,
)


# ── Tool button ──────────────────────────────────────────────────

class _ToolButton(QWidget):
    """A single tool button row: icon + label + shortcut hint."""

    clicked = Signal(str)

    def __init__(self, action_id: str, icon: str, label: str,
                 shortcut: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._action_id = action_id
        self._hovered = False
        self._active = False
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(6)

        icon_label = QLabel(icon)
        icon_label.setFont(QFont(FONT_FAMILY, 13))
        icon_label.setFixedWidth(20)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"color: {BOX_BORDER.name()}; background: transparent;")
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(icon_label)

        text_label = QLabel(label)
        text_label.setFont(QFont(FONT_FAMILY, 10))
        text_label.setStyleSheet(f"color: {BOX_BORDER.name()}; background: transparent;")
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(text_label, stretch=1)

        hint = QLabel(shortcut)
        hint.setFont(QFont(FONT_FAMILY, 9))
        hint.setStyleSheet(f"color: {SIDE_PANEL_SHORTCUT_COLOR.name()}; background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(hint)

    @property
    def active(self) -> bool:
        return self._active

    @active.setter
    def active(self, value: bool):
        self._active = value
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._action_id)

    def paintEvent(self, event):
        if self._active or self._hovered:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = SIDE_PANEL_BTN_ACTIVE if self._active else SIDE_PANEL_BTN_HOVER
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawRoundedRect(self.rect().adjusted(4, 0, -4, 0), 4, 4)
            p.end()


# ── Section header ───────────────────────────────────────────────

class _SectionHeader(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 2)
        label = QLabel(title.upper())
        label.setFont(QFont(FONT_FAMILY, 8, QFont.Weight.Bold))
        label.setStyleSheet(
            f"color: {SIDE_PANEL_SECTION_COLOR.name()}; background: transparent;"
        )
        layout.addWidget(label)


# ── Side panel ───────────────────────────────────────────────────

class SidePanel(QWidget):
    """Right-edge tool panel with context-sensitive actions."""

    tool_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(SIDE_PANEL_WIDTH)

        self._buttons: dict[str, _ToolButton] = {}
        self._sections: dict[str, list[QWidget]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(0, 8, 0, 8)
        self._layout.setSpacing(0)

        self._build_mode_section()
        self._build_edit_section()
        self._build_actions_section()
        self._build_view_section()
        self._build_export_section()

        self._layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

    def _add_section(self, name: str, title: str,
                     buttons: list[tuple[str, str, str, str]]):
        header = _SectionHeader(title, self)
        self._layout.addWidget(header)
        widgets: list[QWidget] = [header]
        for action_id, icon, label, shortcut in buttons:
            btn = _ToolButton(action_id, icon, label, shortcut, self)
            btn.clicked.connect(self.tool_activated.emit)
            self._layout.addWidget(btn)
            self._buttons[action_id] = btn
            widgets.append(btn)
        self._sections[name] = widgets

    def _build_mode_section(self):
        self._add_section("mode", "Mode", [
            ("mode_select",  "󰆕", "Select",  "v"),
            ("mode_rect",    "󰹟", "Node",    "n"),
            ("mode_text",    "󰊄", "Text",    "t"),
            ("mode_connect", "󱃗", "Connect", "c"),
        ])

    def _build_edit_section(self):
        self._add_section("edit", "Edit", [
            ("edit_label",  "󰏫", "Edit",    "e"),
            ("delete",      "󰆴", "Delete",  "x"),
            ("style",       "󰃣", "Style",   "s"),
            ("dimension",   "󰳂", "Size",    "d"),
        ])

    def _build_actions_section(self):
        self._add_section("actions", "Actions", [
            ("undo",   "󰕌", "Undo",    "u"),
            ("redo",   "󰑎", "Redo",    "^R"),
            ("layout", "󱁐", "Layout",  "="),
            ("search", "󰍉", "Search",  "/"),
        ])

    def _build_view_section(self):
        self._add_section("view", "View", [
            ("grid",    "󰕘", "Grid",    "#"),
            ("minimap", "󰍍", "Minimap", "M"),
        ])

    def _build_export_section(self):
        self._add_section("export", "Export", [
            ("yank_png",   "󰆏", "PNG",  "Y"),
            ("export_svg", "󰈔", "SVG",  "^E"),
        ])

    def set_section_visible(self, name: str, visible: bool):
        for widget in self._sections.get(name, []):
            widget.setVisible(visible)

    def update_mode(self, mode: Mode):
        mode_map = {
            Mode.SELECT: "mode_select",
            Mode.RECT: "mode_rect",
            Mode.TEXT: "mode_text",
            Mode.CONNECT: "mode_connect",
        }
        for action_id, btn in self._buttons.items():
            if action_id.startswith("mode_"):
                btn.active = (action_id == mode_map.get(mode))

    def update_selection(self, has_selection: bool):
        self.set_section_visible("edit", has_selection)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), SIDE_PANEL_BG)
        # Left border line
        p.setPen(QPen(SIDE_PANEL_BORDER, 1))
        p.drawLine(0, 0, 0, self.height())
        p.end()


# ── Floating toggle button ───────────────────────────────────────

class PanelToggleButton(QWidget):
    """Small floating button in the top-left corner to toggle the side panel."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(SIDE_PANEL_TOGGLE_SIZE, SIDE_PANEL_TOGGLE_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self.setToolTip("Toggle tools panel (\\)")

    def reposition(self):
        if self.parent():
            self.move(SIDE_PANEL_TOGGLE_MARGIN, SIDE_PANEL_TOGGLE_MARGIN)
            self.raise_()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(SIDE_PANEL_TOGGLE_BG)
        if self._hovered:
            bg.setAlpha(240)

        p.setPen(QPen(SIDE_PANEL_TOGGLE_BORDER, 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)

        # Wrench icon (nerd font)
        p.setPen(QPen(QColor(BOX_BORDER), 1))
        p.setFont(QFont(FONT_FAMILY, 13))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "󰒓")
        p.end()
