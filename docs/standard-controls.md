# Standard controls

The standard control scheme drives grafli the way other apps are driven:
a **menu bar**, a **toolbar**, a **right-click menu** for whatever is under
the pointer, and the shortcuts you already know. No single letter key runs a
command, and there are no modes to learn: pick a tool on the toolbar and
click on the canvas. Box, Note and Image go back to **Select** after one
click; the Arrow tool stays on so you can draw several arrows, until you
choose **Toolbar ▸ Select** or press <kbd>Esc</kbd> with nothing selected.

!!! info "Using the vim keys instead?"
    grafli has a second scheme driven by single keys and modes. Its page is
    [Keybindings](keybindings.md), its guide
    [Navigating graphs with the vim keys](navigating.md).

## Choosing the scheme

The first time grafli starts it asks which scheme you want. Change it at any
time without a restart and without losing the open board:

- **Help ▸ Control scheme** in the menu bar,
- **Controls** at the bottom of the Tools panel (the gear in the top-left
  corner of the canvas opens it),
- **Switch to …** in the <kbd>F1</kbd> help.

The choice is remembered for the next start. The <kbd>F1</kbd> help and
[grafli at a glance](at-a-glance-standard.html) always show the scheme you
are on.

**Ctrl** is **⌘** on a Mac throughout: <kbd>Ctrl</kbd>+<kbd>C</kbd> is
⌘C, <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> is ⇧⌘Z.

## Building a board with the mouse

| To | Do |
|---|---|
| Create a box | **Toolbar ▸ Box**, then click on the canvas (or drag its size); type its name |
| Create a note | **Toolbar ▸ Note**, then click where it goes; type its text |
| Add a picture | **Toolbar ▸ Image** and pick the file, or drop image files on the canvas |
| Draw an arrow | **Toolbar ▸ Arrow**, click one box, then the other; or right-click a box ▸ **Connect from here** |
| Rename a box, edit an arrow's label | Double-click it, or select it and press <kbd>F2</kbd> |
| Move | Drag it; or the arrow keys |
| Resize | Select it, drag a corner (scales the text too) or an edge |
| Nest | Drag it onto a box and drop it; drag it out to take it out again |
| Group | Select several, **Arrange ▸ Group in a box** (<kbd>Ctrl</kbd>+<kbd>G</kbd>) |
| Delete | <kbd>Delete</kbd>, **Toolbar ▸ Delete** or right-click ▸ Delete |
| Give a box a sub-board or a document | **Edit ▸ Attach** (or right-click ▸ Attach): a markdown document, a sub-board, a link or file; <kbd>Enter</kbd> on a box with nothing attached offers the same |
| Go into a box's board | <kbd>Enter</kbd>, **Go ▸ Into the box's board** or right-click ▸ Into the box's board; <kbd>Alt</kbd>+<kbd>↑</kbd> comes back |
| Colour, icon, text style | **Format ▸ Colour**, **Format ▸ Icon…**, **Format ▸ Text**, or the same on the right-click menu and the toolbar |
| Undo, redo | **Toolbar ▸ Undo**, **Toolbar ▸ Redo**, or <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> |
| Open, save, export | **File ▸ Open…**, **File ▸ Save**, **File ▸ Export**; **Toolbar ▸ Open**, **Toolbar ▸ Save** |

The right-click menu changes with what is under the pointer: on a box it
has Rename, the clipboard, Format, Connect from here, **Right-click ▸ Follow
an arrow** to the boxes it is connected to, and the way into its board; on an
arrow its label, colour, line and kind; on the empty canvas Paste here and
New box / New note / Image here. A command for one element — Rename, Open,
Connect from here — acts on the element you right-clicked, even with others
selected; Delete, Colour and the other commands for many act on the whole
selection. While a tour plays, presenting fullscreen too, the right-click
menu holds the tour's controls: next, previous, play / pause / loop, smooth
camera, stop.

**Select all** (<kbd>Ctrl</kbd>+<kbd>A</kbd>) takes the arrows too, so a
colour or a text size reaches their labels. Copying an arrow on its own
copies its label as text: an arrow is pasted with the boxes it connects,
so select those with it.

## Editing text

Labels, notes and long texts are plain text fields, without vim modes.

- A **box or arrow label** edits in place: <kbd>Enter</kbd> keeps it,
  <kbd>Shift</kbd>+Enter starts a new line.
- A **note** edits in place too; <kbd>Enter</kbd> is a new line there, and
  <kbd>Ctrl</kbd>+<kbd>Enter</kbd> keeps the text.
- <kbd>Esc</kbd> or a click elsewhere is done: the text is kept.
  <kbd>Ctrl</kbd>+<kbd>Z</kbd> afterwards takes the edit back.
- **Edit ▸ Edit in a window** opens long text in a window over the board:
  a note's text, or the markdown document of a box (created when it has
  none). <kbd>Ctrl</kbd>+<kbd>S</kbd> saves and keeps writing, Done or
  <kbd>Esc</kbd> keeps it and closes, Cancel drops what was typed since the
  last save.

The vim scheme edits the same texts in textli's vim editors; the board file
does not record which scheme wrote it.

## Your agent

A Claude Code session you run can take single changes from the app, as the
browser tab of `grafli serve` does: connect it once as
[In the desktop app](ai.md#in-the-desktop-app-hand-single-changes-to-your-agent)
says. Then, on a saved board:

- <kbd>Ctrl</kbd>+<kbd>L</kbd> or **Agent ▸ Agent line…** opens the agent
  line along the bottom of the canvas, and hosts the board the first time.
  A grafli line such as `@ box cache "Cache"` is applied at once, and
  <kbd>Ctrl</kbd>+<kbd>Z</kbd> takes it back; anything else is plain
  language for the agent. <kbd>↑</kbd> and <kbd>↓</kbd> bring back the
  lines sent before; <kbd>Enter</kbd> sends, <kbd>Esc</kbd> closes.
- <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>L</kbd> or **Agent ▸ Ask about the
  selection…** asks about the selected element; **Right-click ▸ Ask the
  agent about this…** asks about the element under the pointer.
- A change of more than 5 elements waits as the agent's proposal: **Agent ▸
  Take the proposal** or **Agent ▸ Drop the proposal**, which a right-click
  anywhere also offers first while it waits.
- **Agent ▸ Undo the agent's edit** takes back its last edit; your own edits
  since stay.
- **✦** in the status bar names the connected agent; its menu hosts the
  board and copies the links guests open in a browser tab.

## Every control

These tables are the ones the <kbd>F1</kbd> help shows, drawn from the same
key table. A test presses every key and clicks every menu and toolbar item
named here, and fails when it does not reach the command the table names or
that command is missing; each mouse, text and tour-playback row has a test
of its own that checks what it does.

<!-- standard-controls:start (python -m grafli.helppage) -->

### Tools

*The toolbar's first buttons; Esc goes back to Select.*

| Control | What it does |
|---|---|
| **Toolbar ▸ Select** | Select, move and resize: the default tool |
| **Toolbar ▸ Box** | Create a box: click, or drag its size |
| **Toolbar ▸ Note** | Create a note: click where it goes |
| **Toolbar ▸ Arrow** | Connect: click a box, then another |
| **Toolbar ▸ Image** | Place a picture from a file |
| **Toolbar ▸ Mockup** | Draw an SVG mockup in place, in its app |
| <kbd>Esc</kbd> | Back to Select; clear the selection |

### Mouse

*On the canvas.*

| Control | What it does |
|---|---|
| Click | Select |
| Shift+click | Add to / take from the selection |
| Drag on empty canvas | Select all in the rectangle |
| Drag an element | Move it |
| Drop it on a box | Nest it there; drop it outside to take it out |
| Drag a corner or an edge | Resize; a corner scales the text too |
| Double-click | Rename a box or an arrow, edit a note |
| Right-click | Menu for what is under the pointer |
| Alt+drag from a box | Draw an arrow to another |
| Middle drag / Space+drag | Pan the canvas |
| Wheel / pinch | Zoom; two-finger scroll pans |
| Drop image files | Add them as images |

### Edit

*Edit menu, or right-click.*

| Control | What it does |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Undo |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Y</kbd> | Redo |
| <kbd>Ctrl</kbd>+<kbd>X</kbd> | Cut |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | Copy |
| <kbd>Ctrl</kbd>+<kbd>V</kbd> | Paste at the pointer |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | Duplicate |
| <kbd>Delete</kbd> / <kbd>Backspace</kbd> | Delete the selection |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> | Select all |
| <kbd>F2</kbd> | Rename the box or arrow, edit the note |
| <kbd>←</kbd><kbd>↑</kbd><kbd>↓</kbd><kbd>→</kbd> | Move the selection; pan with nothing selected |
| <kbd>Shift</kbd>+<kbd>←</kbd><kbd>↑</kbd><kbd>↓</kbd><kbd>→</kbd> | Move the selection further |
| <kbd>Ctrl</kbd>+<kbd>K</kbd> | Link: a web page, a file or another board |
| **Edit ▸ Edit in a window** | Long text: a note, or the box's document |
| **Edit ▸ Attach** | A markdown document, a sub-board, a link or file |

### Editing text

*Labels, notes and the text window: no modes.*

| Control | What it does |
|---|---|
| <kbd>Enter</kbd> | Keep a label (Shift+Enter: a new line) |
| <kbd>Ctrl</kbd>+<kbd>Enter</kbd> | Keep a note's text |
| <kbd>Esc</kbd> | Done: keep the text and close |
| Click elsewhere | Keep the text and close |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | In the text window: save, keep writing |

### Format

*Format menu or right-click; boxes, notes, arrows alike.*

| Control | What it does |
|---|---|
| **Format ▸ Colour** | Fill of a box, colour of a note or an arrow |
| **Format ▸ Icon…** | Pick a symbol, where it sits, a number badge |
| **Format ▸ Text** | Size, bold, italic, font |
| <kbd>Ctrl</kbd>+<kbd>B</kbd> | Bold |
| <kbd>Ctrl</kbd>+<kbd>I</kbd> | Italic |
| <kbd>Ctrl</kbd>+<kbd>]</kbd> | Text bigger |
| <kbd>Ctrl</kbd>+<kbd>[</kbd> | Text smaller |
| **Format ▸ Appearance** | Plate / flat / card, label spot, outline; an arrow's heads, line, routing |
| **Format ▸ Round shape** | A circle when square, a pill otherwise |
| **Format ▸ Status label…** | A short status on the box's edge |
| **Format ▸ Arrow kind** | Graph edge ⇄ annotation |

### Arrange

*Arrange and Insert menus.*

| Control | What it does |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>G</kbd> | Group: wrap the selection in a new box |
| **Arrange ▸ Auto-layout** | Lay out the selection (or all) |
| **Arrange ▸ Snap to grid** | Snap the selection to the grid |
| **Arrange ▸ Slide ratio** | Boxes to the slide aspect ratio |
| **Insert ▸ Connected box** | A new box beside the selection, with an arrow |

### Navigate

*View and Go menus.*

| Control | What it does |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | Find: dim all but the matches (Tab: next match) |
| <kbd>Ctrl</kbd>+<kbd>+</kbd> | Zoom in |
| <kbd>Ctrl</kbd>+<kbd>-</kbd> | Zoom out |
| <kbd>Ctrl</kbd>+<kbd>0</kbd> | Zoom to fit the whole board |
| **View ▸ Zoom to selection** | Zoom to the selection ⇄ back |
| <kbd>Enter</kbd> | Open the box's board, link or doc; offers to attach one |
| <kbd>Alt</kbd>+<kbd>↑</kbd> | Back up to the board you came from |
| <kbd>Alt</kbd>+<kbd>←</kbd> | View history back |
| <kbd>Alt</kbd>+<kbd>→</kbd> | View history forward |
| <kbd>Tab</kbd> | Next sibling box |
| <kbd>Shift</kbd>+<kbd>Tab</kbd> | Previous sibling box |
| **Go ▸ Parent box** | Select the box this one sits in |
| **Go ▸ First child** | Select the first box inside |
| **Right-click ▸ Follow an arrow** | Go to a box this one is connected to |
| **Go ▸ Read the doc** | The box's doc beside it (Esc closes) |

### View

*View menu.*

| Control | What it does |
|---|---|
| **View ▸ Grid** | Grid: dots and snap / dots / off |
| **View ▸ Minimap** | Minimap |
| **View ▸ Legend** | The map palette's legend (also in exports) |
| **View ▸ Level of detail** | Semantic zoom on / off |
| **View ▸ Dim notes** | Concentrate on the graph |
| **View ▸ Dim arrows** | Arrows faint |
| **View ▸ Connectivity heatmap** | Then each overlay file |
| **View ▸ Focus on connections** | Only what touches the box |
| **View ▸ Tools panel** | The side panel: tools and flows |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd> | Light / dark theme |

### Bookmarks & tours

*Tours menu.*

| Control | What it does |
|---|---|
| **Tours ▸ Bookmark the view** | What's shown, or the selection |
| **Tours ▸ Bookmark the exact viewport** | Zoom and position as they are |
| **Tours ▸ Record a flow** | Start / stop: bookmarks join it |
| **Tours ▸ Auto-flow from the box** | Walk its arrows forward |
| **Tours ▸ Tours through the box** | Pick one, play from there |
| **Tours ▸ Edit flows** | Reorder, add, remove, dwell |
| <kbd>F5</kbd> | Present the flow fullscreen |

### Tour playback

*While a tour plays.*

| Control | What it does |
|---|---|
| <kbd>Space</kbd> / <kbd>→</kbd> | Next stop |
| <kbd>←</kbd> | Previous stop |
| <kbd>Esc</kbd> | Stop playback |
| Right-click | Next, previous, play / pause / loop, camera, stop — presenting too |
| **Tours ▸ Play, pause, loop** | Paused → playing → loop |
| **Tours ▸ Smooth camera** | Smooth camera ⇄ instant cuts |

### Files & export

*File and Help menus.*

| Control | What it does |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | New board |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Open a board |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save |
| <kbd>Ctrl</kbd>+<kbd>W</kbd> | Close the board |
| **File ▸ Switch board…** | Another open board, or one nearby |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd> | Copy the board as PNG |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Export SVG to a file |
| **File ▸ Export** | PNG, SVG, flow PDF / PPTX, HTML |
| <kbd>Ctrl</kbd>+<kbd>Q</kbd> | Quit |
| <kbd>F1</kbd> | This help |
| **Help ▸ Control scheme** | Switch to the vim keys, at once |

### Your agent

*A Claude Code session you run: the agent line hosts the board, /mcp__grafli__connect in the session connects it; right-click asks about what is under the pointer.*

| Control | What it does |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | Agent line: a grafli line is applied, plain language goes to the agent |
| <kbd>↑</kbd> / <kbd>↓</kbd> | On the agent line: the lines sent before |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>L</kbd> | Ask the agent about the selection |
| **Agent ▸ Take the proposal** | Take the agent's proposal, while one waits; right-click has it too |
| **Agent ▸ Drop the proposal** | Drop it; the board stays as it was |
| **Agent ▸ Undo the agent's edit** | Its last edit; yours stay |
| ✦ in the status bar | Its menu hosts the board and copies the links guests open in a browser tab |

<!-- standard-controls:end -->

## Not in the standard scheme

- Remapping single keys ([#117](https://github.com/MisterGC/grafli/issues/117)).
- The browser tab of `grafli serve` keeps its own mouse controls and keys,
  whichever scheme the desktop app is on: see
  [Show a board live in a browser tab](navigating.md#show-a-board-live-in-a-browser-tab).
- Touch gestures beyond the trackpad's scroll and pinch.
- The vim scheme's keyboard-only tools — jump labels, following arrows
  with <kbd>Alt</kbd> held, the `s` and `d` style modes — have menu
  equivalents here (**View ▸ Focus on connections**, **Go ▸ Parent box**,
  **Format ▸ Appearance**) rather than keys.
