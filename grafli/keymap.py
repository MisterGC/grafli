"""Every key grafli knows, in one table.

The F1 help in the desktop app and the "grafli at a glance" page
(``grafli/helppage.py``, published as ``docs/at-a-glance.html``) both render
from :data:`GROUPS`, so a key added here shows in both, and a key missing
from either fails ``tests/test_keymap.py``.

The desktop app has two control schemes (:mod:`grafli.controls`, #352).
:data:`GROUPS` holds the vim scheme's keys and the browser tab's;
:data:`STANDARD_GROUPS` the standard scheme's: menus, toolbar, mouse and the
shortcuts other apps use. Each standard row names the command it runs
(``Key.action``), and ``tests/test_standard_controls.py`` presses or clicks
every row and fails when the app does not run that command.

A row's keys are written in a small notation:

* ``" / "`` separates alternatives: ``"u / Cmd+Z"``;
* a space separates a sequence pressed one after another: ``"g z"``;
* ``"+"`` joins a chord held together: ``"Ctrl+Shift+Z"`` (a lone ``"+"`` is
  the plus key).

``Cmd`` and ``Shift`` are written out and drawn as ``⌘`` and ``⇧``. A row
whose trigger is a mouse gesture or a typed token rather than keys (a
double-click, ``~detail=``) is a :func:`gesture`; its text is shown as it
stands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .format import MAX_DESCRIPTION_CHARS

APP = "app"
TAB = "tab"


@dataclass(frozen=True)
class Key:
    keys: str
    does: str
    is_gesture: bool = False
    # The standard scheme's command this row runs (``GrafliView.std_run``);
    # ``mouse:``, ``text:`` and ``play:`` rows name a behaviour of the
    # canvas, the text editors or the tour player instead.
    action: str = ""


@dataclass(frozen=True)
class Group:
    id: str
    title: str
    where: str
    keys: tuple[Key, ...]
    # The key that enters this mode from Select; empty for the Select topics.
    enter: str = ""
    # One line on where the keys apply.
    blurb: str = ""
    # For the browser tab: the links whose tabs have these keys.
    links: tuple[str, ...] = ()


def key(keys: str, does: str, action: str = "") -> Key:
    return Key(keys, does, action=action)


def gesture(text: str, does: str, action: str = "") -> Key:
    return Key(text, does, is_gesture=True, action=action)


_GLYPHS = {"Cmd": "⌘", "Shift": "⇧"}


def parse_keys(notation: str) -> list[list[list[str]]]:
    """``notation`` as alternatives, each a sequence of chords of key names."""
    alts = []
    for alt in notation.split(" / "):
        seq = []
        for step in alt.split(" "):
            if step == "+":
                seq.append(["+"])
            else:
                seq.append(re.split(r"(?<=.)\+(?=.)", step))
        alts.append(seq)
    return alts


def key_name(name: str) -> str:
    """How a key is printed on its cap: ``Cmd`` as ``⌘``, ``Shift`` as ``⇧``."""
    return _GLYPHS.get(name, name)


def compact_keys(k: Key) -> str:
    """The row's keys as plain text, the way the F1 help prints them:
    ``g z`` as ``gz``, ``Shift+Z`` as ``⇧Z``, ``Ctrl+R`` as ``Ctrl+R``."""
    if k.is_gesture:
        return k.keys
    out = []
    for alt in parse_keys(k.keys):
        steps = []
        for chord in alt:
            text = ""
            for i, part in enumerate(chord):
                name = key_name(part)
                if i and chord[i - 1] not in _GLYPHS:
                    text += "+"
                text += name
            steps.append(text)
        glue = "" if all(len(s) == 1 for s in steps) else " "
        out.append(glue.join(steps))
    return " / ".join(out)


# ── The desktop app ─────────────────────────────────────────────────

_APP_GROUPS = (
    Group("modes", "Modes", APP, blurb="One key from Select; Esc comes back", keys=(
        key("v", "Select mode, the default"),
        key("n", "Create box (⇧click stays in mode)"),
        key("t", "Create note (⇧click stays in mode)"),
        key("i", "SVG mockup in place: a starter .svg opens in its app"),
        key("c", "Connect: click two nodes (the same twice: a loop)"),
        key("Esc", "Cancel / back to Select"),
    )),
    Group("navigate", "Navigate", APP, blurb="In Select", keys=(
        key("←↑↓→", "Pan the view (when nothing is selected)"),
        gesture("Middle / right drag", "Pan from anywhere"),
        gesture("Two-finger scroll", "Pan (trackpad)"),
        gesture("Wheel / ⌃scroll / pinch", "Zoom in / out"),
        key("+ / -", "Zoom in / out"),
        key("z", "Zoom in: 25 → 50 → 100 → 150 % (cycle)"),
        key("Shift+Z", "Zoom to fit (whole graph)"),
        key("g z", "Focus: zoom to the selection ⇄ back"),
        key("g p", "Select parent (zoom if needed)"),
        key("g c", "Select first child"),
        key("Tab / Shift+Tab", "Cycle siblings (or search matches)"),
        key("f / Ctrl+J", "Jump to any item: type its label"),
        key("Ctrl+O / Ctrl+I", "View history back / forward"),
        key("Alt", "Hold: follow connectors with keys"),
    )),
    Group("levels", "Boards & levels", APP, blurb="In Select", keys=(
        key("g d / Return", "Zoom into the box's sub-board"),
        key("g u", "Back to the board you came from"),
        key("g v", "Peek at the box's doc (Esc closes)"),
        key("Ctrl+K", "Open / switch buffer"),
        key("Ctrl+6", "Toggle last buffer"),
        key("Q", "Close buffer (no selection)"),
    )),
    Group("edit", "Edit", APP, blurb="In Select, on the selection", keys=(
        key("e", "Edit the element inline: label, note, image's file"),
        gesture("Double-click", "Edit what you clicked"),
        gesture("Shift+click", "Add to / take from the selection"),
        key("E", "textli, the full editor: note text / box or image markdown"),
        key("W", "Set URL on the selected item"),
        key("Return", "Open the attachment: a link, a sub-board"),
        key("y / p", "Yank / paste"),
        key("u / Cmd+Z", "Undo"),
        key("Ctrl+R / Cmd+Shift+Z", "Redo"),
        key("x / Delete", "Delete the selection"),
        gesture("Drag a note's right edge", "Note wrap width (~width=N; 80 by default)"),
    )),
    Group("create", "Create", APP, blurb="In Select", keys=(
        key("o / O", "New box below / above the selection"),
        key("Ctrl+←↑↓→",
            "New connected box on that side"),
        key("Ctrl+G", "Wrap the selection in a new parent box"),
        gesture("Alt+drag", "Connect nodes: boxes, notes, images"),
        gesture("Alt+click", "Paste at that point"),
    )),
    Group("note", "Editing text", APP, enter="e",
          blurb="The inline editor is vim-capable and opens in INSERT", keys=(
        key("Esc", "In INSERT: to NORMAL (vim motions)"),
        key("Esc", "In NORMAL: keep and close"),
        key("Shift+Esc", "In NORMAL: drop and close"),
        key("Enter", "Accept a label edit"),
        key("Ctrl+G", "Insert a glyph"),
        gesture("Click elsewhere", "Keep and close"),
    )),
    Group("style", "Style", APP, enter="s",
          blurb="s on a selection; the same keys for box, note, arrow", keys=(
        key("e", "Appearance: plate / flat / card, label spot (left: a band zoomed out), ink, outline"),
        key("c", "Color grid, then the map palette's %names and kinds (hjkl, Enter; 1–9 an entry)"),
        key("i", "Symbol grid, then the board's own icons from -res/icons/ (Tab: fill / lead / badge; 0–9 a number badge, f filled)"),
        key("t", "Text grid: size × bold / italic (Tab: the font; o outline, s shadow)"),
        key("s", "Status label on a box (~status=), then its colour"),
        key("r", "Round box: a circle when square, a pill otherwise"),
        key("j / k", "Nudge text size"),
        key("d", "On to Dimension mode"),
    )),
    Group("dimension", "Dimension", APP, enter="d",
          blurb="d on a selection of boxes, or s then d", keys=(
        key("h / j / k / l", "Shrink the boxes on that side"),
        key("Shift+H / Shift+J / Shift+K / Shift+L", "Grow them on that side"),
        key("r", "Snap to the slide aspect ratio (an export frame)"),
        key("s", "Back to Style"),
    )),
    Group("arrow", "Arrows", APP, blurb="With an arrow selected", keys=(
        key("e", "Edit the arrow's label"),
        key("s", "Arrow style mode"),
        key("s e", "Appearance: heads, ends, line, routing, sides, colour"),
        key("s c", "Colour grid"),
        key("s t", "Label text size"),
        key("s r", "Routing: direct / spline / stair"),
        key("s a", "Kind: graph edge ⇄ annotation"),
        key("h / l", "In style mode: toggle arrowheads"),
        key("j / k", "In style mode: label size"),
        key("Shift+J / Shift+K", "In style mode: line pattern"),
        gesture("Shift+click", "Add an arrow to the selection, style many"),
    )),
    Group("layout", "Lay out", APP, blurb="In Select", keys=(
        key("Shift+G", "Snap to grid"),
        key("=", "Auto-layout the selection (or all)"),
        gesture("Drag a corner", "Scale size and font; ⇧ frees the ratio"),
        gesture("Drag an edge", "Stretch one axis"),
    )),
    Group("focus", "Focus & analysis", APP, blurb="In Select", keys=(
        key(",", "Dim arrows"),
        key("Shift+N", "Dim notes: concentrate on the graph"),
        key("A", "Connectivity heatmap, then each overlay file"),
        key("B", "Subgraph focus (cycle direction)"),
        key("Shift+B", "Focus depth: full / 1-hop"),
    )),
    Group("search", "Search", APP, enter="/",
          blurb="Dims everything that does not match", keys=(
        gesture("Type", "Filter by label, id and note text"),
        key("Tab / Shift+Tab", "Next / previous match"),
        key("Enter", "Hide the input, keep the filter"),
        key("Esc", "Clear the filter"),
    )),
    Group("view", "View", APP, blurb="Anywhere", keys=(
        key("#", "Grid"),
        key("M", "Minimap"),
        key("Shift+M", "Toggle the legend of the map's palette (also in exports)"),
        key("Shift+D", "Level of detail (semantic zoom) on / off"),
        gesture("Double-click a tile", "Fly into a collapsed group"),
        key("\\", "Tools panel"),
        key("Cmd+Shift+D", "Light / dark theme"),
        key("`", "Debug overlay"),
    )),
    Group("tours", "Bookmarks & tours", APP, blurb="In Select", keys=(
        key("g b", "Bookmark what's shown (or the selection)"),
        key("g B", "Bookmark the exact viewport"),
        gesture("One note + g b, no caption", "A text slide, links clickable"),
        gesture("Flows tab step + g b", "Insert a new bookmark after it"),
        key("g f", "Start / stop recording a flow"),
        key("g F", "Auto-flow: walk forward arrows from the box"),
        key("g t", "Pick a tour through the box, play from there"),
        key("F5", "Present the flow fullscreen"),
        gesture("Flows tab (\\)", "Reorder, add, remove, dwell, re-generate"),
        gesture("Caption", f"Shown whole, wrapped: keep it ≤ "
                           f"{MAX_DESCRIPTION_CHARS} chars"),
        gesture("~detail=", "Flow / stop level of detail: full / summary"),
        gesture("~focus=", "Flow / stop focus: complete fades what is cut"),
    )),
    Group("playback", "Tour playback", APP, enter="F5",
          blurb="While a tour plays, in the app or presenting", keys=(
        key("Space / →", "Next stop"),
        key("←", "Previous stop"),
        key("t", "Smooth camera ⇄ instant cuts"),
        key("p", "Paused → playing → loop"),
        key("g d / Return", "Leave into the box's level; g u resumes"),
        key("Esc", "Stop playback"),
    )),
    Group("files", "Files & export", APP, blurb="Anywhere", keys=(
        key("Cmd+N", "New file"),
        key("Cmd+O", "Open file"),
        key("Cmd+S", "Save file"),
        key("Cmd+Q", "Quit"),
        key("Y", "Copy the diagram as PNG"),
        key("Ctrl+E", "Export SVG to a file"),
        gesture("Click @path:line", "Open the source in your editor"),
        key("F1", "This help"),
    )),
    Group("agent", "Your agent", APP,
          blurb="A Claude Code session you run: : hosts the board, "
                "/mcp__grafli__connect in the session connects it", keys=(
        key(":", "Command line: a grafli line is applied, plain language "
                 "goes to the agent"),
        key("↑ / ↓", "On the command line: the lines sent before"),
        key("Shift+A", "Ask the agent about the selection"),
        key("Enter", "Take the agent's proposal, while one waits"),
        key("x", "Drop the agent's proposal"),
        key("Shift+U", "Undo the agent's last edit; yours stay"),
        gesture("/mcp__grafli__connect",
                "In the session: connect it; the status bar names it"),
        gesture("✦ in the status bar",
                "Its menu copies the links guests open in a browser tab"),
    )),
)

# ── The browser tab of `grafli serve` ───────────────────────────────

_TAB_GROUPS = (
    Group("tab-read", "Every tab", TAB, links=("watch", "edit", "present"),
          blurb="Watch, edit and present links alike", keys=(
        gesture("Drag / wheel", "Pan and zoom"),
        key("Shift+Z", "Fit the board in view"),
        key("f", "Jump labels: type one to select"),
        key("g d / Return", "Into the box's level"),
        key("g u / Backspace", "Back up"),
        key("g v", "Read the box's doc (Esc closes)"),
        key("A", "Next overlay file"),
        key("k", "Laser on / off: a trail every tab sees"),
    )),
    Group("tab-build", "Build", TAB, links=("edit", "present"),
          blurb="Edit and present links", keys=(
        key("o / O", "New box below / above, with an arrow from it"),
        key("Ctrl+←↑↓→",
            "The same, on that side"),
        key("c", "Connect to the box whose label you type"),
        key("e", "Rename the selection"),
        key("x / Delete", "Delete the selection, with its arrows"),
        key("u / Cmd+Z", "Undo your last edit in this tab"),
        key(":", "Command line: a grafli line, or plain language"),
        key("↑", "On the command line: the last line"),
    )),
    Group("tab-mouse", "Mouse", TAB, links=("edit", "present"),
          blurb="Edit and present links: guests need no keys", keys=(
        gesture("Click", "Select; a box with a level opens it"),
        gesture("Double-click", "Rename what you clicked"),
        gesture("Drag a box", "Move it, into the box you drop it on"),
        gesture("Drag from a box's edge", "Draw an arrow"),
        gesture("Right-click", "Ask a Q: question in place"),
    )),
    Group("tab-agent", "Your agent", TAB, links=("edit", "present"),
          blurb="A Claude Code session you run and connect", keys=(
        key(":", "Plain language goes to the agent"),
        key("a", "Ask the agent about the selection (the ✦ ask chip)"),
        key("Enter", "Present link: take the agent's proposal"),
        key("x", "Present link: drop the proposal"),
        key("Shift+U", "Present link: undo the agent's last edit"),
    )),
    Group("tab-reveal", "Reveal", TAB, links=("present",),
          blurb="Present link: uncover a prepared board as you talk", keys=(
        key("v", "Jump labels on the hidden: type one to reveal it"),
        key("+", "Right after: also what an arrow connects it to"),
        key("Shift+V", "Reveal mode on / off"),
    )),
    Group("tab-tour", "Tour", TAB, links=("watch", "edit", "present"),
          blurb="While a tour plays in a tab", keys=(
        key("Space / → / l / j", "Next stop"),
        key("← / h / k", "Previous stop"),
        key("p", "Paused / playing / loop"),
        key("t", "Smooth or instant camera"),
        key("Esc / q", "End the tour"),
    )),
)

GROUPS: tuple[Group, ...] = _APP_GROUPS + _TAB_GROUPS


# ── The desktop app, standard scheme ────────────────────────────────
#
# A gesture row written ``"Menu ▸ Item"`` is that menu's item (``Toolbar ▸``
# a toolbar button, ``Right-click ▸`` the menu on a box). Ctrl is ⌘ on a Mac.

STANDARD_GROUPS: tuple[Group, ...] = (
    Group("std-tools", "Tools", APP,
          blurb="The toolbar's first buttons; Esc goes back to Select", keys=(
        gesture("Toolbar ▸ Select", "Select, move and resize: the default tool",
                "tool_select"),
        gesture("Toolbar ▸ Box", "Create a box: click, or drag its size",
                "tool_box"),
        gesture("Toolbar ▸ Note", "Create a note: click where it goes",
                "tool_note"),
        gesture("Toolbar ▸ Arrow", "Connect: click a box, then another",
                "tool_connect"),
        gesture("Toolbar ▸ Image", "Place a picture from a file",
                "insert_image"),
        gesture("Toolbar ▸ Mockup", "Draw an SVG mockup in place, in its app",
                "tool_mockup"),
        key("Esc", "Back to Select; clear the selection", "escape"),
    )),
    Group("std-mouse", "Mouse", APP, blurb="On the canvas", keys=(
        gesture("Click", "Select", "mouse:select"),
        gesture("Shift+click", "Add to / take from the selection",
                "mouse:add_select"),
        gesture("Drag on empty canvas", "Select all in the rectangle",
                "mouse:rubber_band"),
        gesture("Drag an element", "Move it", "mouse:move"),
        gesture("Drop it on a box", "Nest it there; drop it outside to take "
                "it out", "mouse:nest"),
        gesture("Drag a corner or an edge", "Resize; a corner scales the "
                "text too", "mouse:resize"),
        gesture("Double-click", "Rename a box or an arrow, edit a note",
                "mouse:edit"),
        gesture("Right-click", "Menu for what is under the pointer",
                "mouse:context_menu"),
        gesture("Alt+drag from a box", "Draw an arrow to another",
                "mouse:alt_connect"),
        gesture("Middle drag / Space+drag", "Pan the canvas", "mouse:pan"),
        gesture("Wheel / pinch", "Zoom; two-finger scroll pans",
                "mouse:zoom"),
        gesture("Drop image files", "Add them as images",
                "mouse:drop_images"),
    )),
    Group("std-edit", "Edit", APP, blurb="Edit menu, or right-click", keys=(
        key("Ctrl+Z", "Undo", "undo"),
        key("Ctrl+Shift+Z / Ctrl+Y", "Redo", "redo"),
        key("Ctrl+X", "Cut", "cut"),
        key("Ctrl+C", "Copy", "copy"),
        key("Ctrl+V", "Paste at the pointer", "paste"),
        key("Ctrl+D", "Duplicate", "duplicate"),
        key("Delete / Backspace", "Delete the selection", "delete"),
        key("Ctrl+A", "Select all", "select_all"),
        key("F2", "Rename the box or arrow, edit the note", "rename"),
        key("←↑↓→", "Move the selection; pan with nothing selected",
            "nudge"),
        key("Shift+←↑↓→", "Move the selection further", "nudge"),
        key("Ctrl+K", "Link: a web page, a file or another board",
            "set_link"),
        gesture("Edit ▸ Edit in a window", "Long text: a note, or the box's "
                "document", "edit_text"),
        gesture("Edit ▸ Attach", "A markdown document, a sub-board, a link "
                "or file", "attach"),
    )),
    Group("std-text", "Editing text", APP,
          blurb="Labels, notes and the text window: no modes", keys=(
        key("Enter", "Keep a label (Shift+Enter: a new line)", "text:enter"),
        key("Ctrl+Enter", "Keep a note's text", "text:ctrl_enter"),
        key("Esc", "Done: keep the text and close", "text:esc"),
        gesture("Click elsewhere", "Keep the text and close",
                "text:click_away"),
        key("Ctrl+S", "In the text window: save, keep writing",
            "text:save"),
    )),
    Group("std-format", "Format", APP,
          blurb="Format menu or right-click; boxes, notes, arrows alike", keys=(
        gesture("Format ▸ Colour", "Fill of a box, colour of a note or an "
                "arrow", "color"),
        gesture("Format ▸ Icon…", "Pick a symbol, where it sits, a number "
                "badge", "icon"),
        gesture("Format ▸ Text", "Size, bold, italic, font", "text_menu"),
        key("Ctrl+B", "Bold", "bold"),
        key("Ctrl+I", "Italic", "italic"),
        key("Ctrl+]", "Text bigger", "text_bigger"),
        key("Ctrl+[", "Text smaller", "text_smaller"),
        gesture("Format ▸ Appearance", "Plate / flat / card, label spot, "
                "outline; an arrow's heads, line, routing", "appearance"),
        gesture("Format ▸ Round shape", "A circle when square, a pill "
                "otherwise", "round"),
        gesture("Format ▸ Status label…", "A short status on the box's edge",
                "status"),
        gesture("Format ▸ Arrow kind", "Graph edge ⇄ annotation",
                "arrow_kind"),
    )),
    Group("std-arrange", "Arrange", APP, blurb="Arrange and Insert menus",
          keys=(
        key("Ctrl+G", "Group: wrap the selection in a new box", "group"),
        gesture("Arrange ▸ Auto-layout", "Lay out the selection (or all)",
                "layout"),
        gesture("Arrange ▸ Snap to grid", "Snap the selection to the grid",
                "snap_grid"),
        gesture("Arrange ▸ Slide ratio", "Boxes to the slide aspect ratio",
                "slide_ratio"),
        gesture("Insert ▸ Connected box", "A new box beside the selection, "
                "with an arrow", "connected_box"),
    )),
    Group("std-navigate", "Navigate", APP, blurb="View and Go menus", keys=(
        key("Ctrl+F", "Find: dim all but the matches (Tab: next match)",
            "find"),
        key("Ctrl++", "Zoom in", "zoom_in"),
        key("Ctrl+-", "Zoom out", "zoom_out"),
        key("Ctrl+0", "Zoom to fit the whole board", "zoom_fit"),
        gesture("View ▸ Zoom to selection", "Zoom to the selection ⇄ back",
                "zoom_selection"),
        key("Enter", "Open the box's board, link or doc; offers to attach one",
            "open_attachment"),
        key("Alt+↑", "Back up to the board you came from", "go_up"),
        key("Alt+←", "View history back", "nav_back"),
        key("Alt+→", "View history forward", "nav_forward"),
        key("Tab", "Next sibling box", "next_sibling"),
        key("Shift+Tab", "Previous sibling box", "prev_sibling"),
        gesture("Go ▸ Parent box", "Select the box this one sits in",
                "parent_box"),
        gesture("Go ▸ First child", "Select the first box inside",
                "first_child"),
        gesture("Right-click ▸ Follow an arrow", "Go to a box this one is "
                "connected to", "follow_arrow"),
        gesture("Go ▸ Read the doc", "The box's doc beside it (Esc closes)",
                "peek_doc"),
    )),
    Group("std-view", "View", APP, blurb="View menu", keys=(
        gesture("View ▸ Grid", "Grid: dots and snap / dots / off", "grid"),
        gesture("View ▸ Minimap", "Minimap", "minimap"),
        gesture("View ▸ Legend", "The map palette's legend (also in exports)",
                "legend"),
        gesture("View ▸ Level of detail", "Semantic zoom on / off", "lod"),
        gesture("View ▸ Dim notes", "Concentrate on the graph", "dim_notes"),
        gesture("View ▸ Dim arrows", "Arrows faint", "dim_arrows"),
        gesture("View ▸ Connectivity heatmap", "Then each overlay file",
                "heatmap"),
        gesture("View ▸ Focus on connections", "Only what touches the box",
                "focus_connections"),
        gesture("View ▸ Tools panel", "The side panel: tools and flows",
                "tools_panel"),
        key("Ctrl+Shift+D", "Light / dark theme", "theme"),
    )),
    Group("std-tours", "Bookmarks & tours", APP, blurb="Tours menu", keys=(
        gesture("Tours ▸ Bookmark the view", "What's shown, or the selection",
                "bookmark"),
        gesture("Tours ▸ Bookmark the exact viewport", "Zoom and position as "
                "they are", "bookmark_viewport"),
        gesture("Tours ▸ Record a flow", "Start / stop: bookmarks join it",
                "record_flow"),
        gesture("Tours ▸ Auto-flow from the box", "Walk its arrows forward",
                "auto_flow"),
        gesture("Tours ▸ Tours through the box", "Pick one, play from there",
                "tours_through"),
        gesture("Tours ▸ Edit flows", "Reorder, add, remove, dwell",
                "edit_flows"),
        key("F5", "Present the flow fullscreen", "present"),
    )),
    Group("std-playback", "Tour playback", APP, blurb="While a tour plays",
          keys=(
        key("Space / →", "Next stop", "play:next"),
        key("←", "Previous stop", "play:prev"),
        key("Esc", "Stop playback", "play:stop"),
        gesture("Right-click", "Next, previous, play / pause / loop, camera, "
                "stop — presenting too", "mouse:play_menu"),
        gesture("Tours ▸ Play, pause, loop", "Paused → playing → loop",
                "play_mode"),
        gesture("Tours ▸ Smooth camera", "Smooth camera ⇄ instant cuts",
                "play_transition"),
    )),
    Group("std-files", "Files & export", APP, blurb="File and Help menus",
          keys=(
        key("Ctrl+N", "New board", "new_board"),
        key("Ctrl+O", "Open a board", "open"),
        key("Ctrl+S", "Save", "save"),
        key("Ctrl+W", "Close the board", "close_board"),
        gesture("File ▸ Switch board…", "Another open board, or one nearby",
                "switch_board"),
        key("Ctrl+Shift+C", "Copy the board as PNG", "export_png"),
        key("Ctrl+E", "Export SVG to a file", "export_svg"),
        gesture("File ▸ Export", "PNG, SVG, flow PDF / PPTX, HTML",
                "export_menu"),
        key("Ctrl+Q", "Quit", "quit"),
        key("F1", "This help", "help"),
        gesture("Help ▸ Control scheme", "Switch to the vim keys, at once",
                "scheme_menu"),
    )),
    Group("std-agent", "Your agent", APP,
          blurb="A Claude Code session you run: the agent line hosts the "
                "board, /mcp__grafli__connect in the session connects it; "
                "right-click asks about what is under the pointer", keys=(
        key("Ctrl+L", "Agent line: a grafli line is applied, plain language "
                      "goes to the agent", "agent_line"),
        key("↑ / ↓", "On the agent line: the lines sent before",
            "text:agent_history"),
        key("Ctrl+Shift+L", "Ask the agent about the selection", "agent_ask"),
        gesture("Agent ▸ Take the proposal", "Take the agent's proposal, "
                "while one waits; right-click has it too", "agent_take"),
        gesture("Agent ▸ Drop the proposal", "Drop it; the board stays as "
                "it was", "agent_drop"),
        gesture("Agent ▸ Undo the agent's edit", "Its last edit; yours stay",
                "agent_undo"),
        gesture("✦ in the status bar", "Its menu hosts the board and copies "
                "the links guests open in a browser tab", "mouse:agent_chip"),
    )),
)


def groups(where: str) -> tuple[Group, ...]:
    return tuple(g for g in GROUPS if g.where == where)


def app_groups(scheme: str) -> tuple[Group, ...]:
    """The desktop app's groups for control scheme ``scheme``."""
    from grafli.controls import STANDARD
    return STANDARD_GROUPS if scheme == STANDARD else groups(APP)


def find(group_id: str, keys: str) -> Key:
    """The row of group ``group_id`` whose keys are ``keys``."""
    group = next(g for g in GROUPS + STANDARD_GROUPS if g.id == group_id)
    return next(k for k in group.keys if k.keys == keys)
