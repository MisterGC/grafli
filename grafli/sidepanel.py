"""Hideable side panel with graphical tool buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
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
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setFont(QFont(FONT_FAMILY, 16))
        icon_label.setFixedWidth(24)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"color: {BOX_BORDER.name()}; background: transparent;")
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(icon_label)

        text_label = QLabel(label)
        text_label.setFont(QFont(FONT_FAMILY, 13))
        text_label.setStyleSheet(f"color: {BOX_BORDER.name()}; background: transparent;")
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(text_label, stretch=1)

        hint = QLabel(shortcut)
        hint.setFont(QFont(FONT_FAMILY, 11))
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
        self.setFixedHeight(28)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 2)
        label = QLabel(title.upper())
        label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        label.setStyleSheet(
            f"color: {SIDE_PANEL_SECTION_COLOR.name()}; background: transparent;"
        )
        layout.addWidget(label)


# ── Side panel ───────────────────────────────────────────────────

class SidePanel(QWidget):
    """Left-edge tool panel with context-sensitive actions."""

    tool_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # Width is driven by the enclosing splitter; only a content-floor and a
        # sane ceiling are enforced so the panel can't clip or swallow the canvas.
        self.setMinimumWidth(self._TOOLS_MIN)
        self.setMaximumWidth(self._MAX_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Never steal keyboard focus from the canvas — panel is mouse-only.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Force a light background on the panel and all children, overriding
        # the system palette (which on macOS dark mode is dark).
        self.setStyleSheet(
            f"SidePanel, QScrollArea, QScrollArea > QWidget,"
            f" QScrollArea > QWidget > QWidget {{"
            f" background: {SIDE_PANEL_BG.name()}; }}"
        )

        self._buttons: dict[str, _ToolButton] = {}
        self._sections: dict[str, list[QWidget]] = {}
        self._view = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Tools | Flows tab switcher.
        root.addWidget(self._build_tabbar())

        # Tools page — scrollable tool buttons.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        content = QWidget()
        content.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(0, 10, 0, 10)
        self._layout.setSpacing(0)

        self._build_mode_section()
        self._build_edit_section()
        self._build_actions_section()
        self._build_view_section()
        self._build_export_section()

        self._layout.addStretch(1)
        scroll.setWidget(content)

        # Flows page — dedicated editor (wired once the view is attached).
        from grafli.flowspanel import FlowsPanel
        self._flows_panel = FlowsPanel(self)

        self._stack = QStackedWidget()
        self._stack.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stack.addWidget(scroll)              # index 0: Tools
        self._stack.addWidget(self._flows_panel)   # index 1: Flows
        root.addWidget(self._stack, stretch=1)

    _TOOLS_WIDTH = SIDE_PANEL_WIDTH
    _FLOWS_WIDTH = 300
    # Minimum widths below which each tab's content would start to clip.
    _TOOLS_MIN = SIDE_PANEL_WIDTH
    _FLOWS_MIN = 240
    _MAX_WIDTH = 720

    def preferred_width(self) -> int:
        """Default shared panel width on first run (wide enough for Flows)."""
        return self._FLOWS_WIDTH

    def _build_tabbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(34)
        bar.setStyleSheet(f"background: {SIDE_PANEL_BG.name()};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 0)
        h.setSpacing(4)
        self._tab_buttons: list[QLabel] = []
        for i, name in enumerate(("Tools", "Flows")):
            tab = QLabel(name)
            tab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tab.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.Bold))
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tab.mousePressEvent = lambda _e, idx=i: self.switch_tab(idx)
            h.addWidget(tab, stretch=1)
            self._tab_buttons.append(tab)
        return bar

    def attach_view(self, view):
        self._view = view
        self._flows_panel.attach(view)
        self.switch_tab(0)

    def switch_tab(self, index: int):
        self._stack.setCurrentIndex(index)
        # Keep the shared width; only adjust the floor to the current content.
        self.setMinimumWidth(self._FLOWS_MIN if index == 1 else self._TOOLS_MIN)
        for i, tab in enumerate(self._tab_buttons):
            active = i == index
            color = BOX_BORDER.name() if active else SIDE_PANEL_SECTION_COLOR.name()
            weight = "bold" if active else "normal"
            border = (f"2px solid {BOX_BORDER.name()}" if active
                      else "2px solid transparent")
            tab.setStyleSheet(
                f"color: {color}; background: transparent;"
                f" border-bottom: {border}; padding-bottom: 2px;"
                f" font-weight: {weight};")
        # Editing only targets a flow while the Flows tab is open.
        if self._view is not None:
            if index == 1:
                self._flows_panel.refresh()
            else:
                self._view.set_flow_edit_target(None, -1)
            self._view.setFocus()

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
            ("undo",        "󰕌", "Undo",        "u"),
            ("redo",        "󰑎", "Redo",        "^R"),
            ("layout",      "󱁐", "Layout",      "="),
            ("slide_ratio", "󰨤", "Slide ratio", "d r"),
            ("lock_ratio",  "󰦞", "Lock ratio",  "d a"),
            ("scale_fit",   "󰊁", "Scale fit",   "d f"),
            ("search",      "󰍉", "Search",      "/"),
        ])

    def _build_view_section(self):
        self._add_section("view", "View", [
            ("grid",          "󰕘", "Grid",     "#"),
            ("minimap",       "󰍍", "Minimap",  "M"),
            ("dim_notes",     "󰎞", "Notes",    "⇧N"),
            ("dim_arrows",    "󰁔", "Edges",    ","),
            ("complexity",    "󰈸", "Analysis", "A"),
        ])

    def _build_export_section(self):
        self._add_section("export", "Export", [
            ("yank_png",        "󰆏", "PNG",       "Y"),
            ("export_svg",      "󰈔", "SVG",       "^E"),
            ("export_flow_pdf", "󰈦", "Flow PDF",  ""),
        ])

    def refresh_flows(self):
        """Refresh the dedicated Flows editor (kept in sync with the board)."""
        self._flows_panel.refresh()

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
        # Right border line (panel sits on the left of the canvas)
        p.setPen(QPen(SIDE_PANEL_BORDER, 1))
        x = self.width() - 1
        p.drawLine(x, 0, x, self.height())
        p.end()


# ── Floating toggle button ───────────────────────────────────────

class PanelToggleButton(QWidget):
    """Small floating button in the top-left corner to toggle the side panel."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(SIDE_PANEL_TOGGLE_SIZE, SIDE_PANEL_TOGGLE_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
