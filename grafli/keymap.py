"""Every key grafli knows, in one table.

The F1 help in the desktop app and the "grafli at a glance" page
(``grafli/helppage.py``, published as ``docs/at-a-glance.html``) both render
from :data:`GROUPS`, so a key added here shows in both, and a key missing
from either fails ``tests/test_keymap.py``.

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


def key(keys: str, does: str) -> Key:
    return Key(keys, does)


def gesture(text: str, does: str) -> Key:
    return Key(text, does, is_gesture=True)


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


def groups(where: str) -> tuple[Group, ...]:
    return tuple(g for g in GROUPS if g.where == where)


def find(group_id: str, keys: str) -> Key:
    """The row of group ``group_id`` whose keys are ``keys``."""
    group = next(g for g in GROUPS if g.id == group_id)
    return next(k for k in group.keys if k.keys == keys)
