# Navigating graphs: standard controls

Once a diagram outgrows a single screen, the work stops being *drawing* and
becomes *moving around*: find the thing, zoom in, edit it, zoom back out,
find the next thing. This page is that loop with the standard controls —
the menus, the toolbar, the right-click menu and the usual shortcuts. For
every control in one table see [Standard controls](standard-controls.md).

!!! info "Using the vim keys?"
    The same tour with the single keys and modes is
    [Navigating graphs with the vim keys](navigating.md).

## The overview → focus → overview loop

The most common rhythm: sit in an overview, dive into one element, edit it,
pop back out.

- Select an element: click it, or find it with <kbd>Ctrl</kbd>+<kbd>F</kbd>.
- **View ▸ Zoom to selection** — the selection zooms up to fill the view,
  and grafli remembers where you came from. The right-click menu on a box
  has it too.
- Double-click to edit it, or <kbd>F2</kbd>.
- **View ▸ Zoom to selection** again — fly back to the exact overview you
  left.

!!! tip "Hop between elements without losing your way out"
    While zoomed in, select another element and zoom to the selection again:
    grafli focuses the new element but keeps your original way back. The
    last time always lands you where the loop started.

## Find and select an element

- **Click** selects, <kbd>Shift</kbd>+click adds to the selection or takes
  from it, and dragging on the empty canvas selects everything in the
  rectangle. <kbd>Ctrl</kbd>+<kbd>A</kbd> selects all.
- **Find** — <kbd>Ctrl</kbd>+<kbd>F</kbd>, then type: grafli matches labels,
  ids and note text and dims everything else. <kbd>Tab</kbd> goes to the next
  match, <kbd>Enter</kbd> hides the field and keeps the filter,
  <kbd>Esc</kbd> clears it.

## Move through the hierarchy

When boxes are nested, walk the tree instead of hunting for it:

- **Go ▸ Parent box** — select the box this one sits in (and zoom to it if
  it isn't fully on screen).
- **Go ▸ First child** — select the first box inside.
- <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> — the next or previous
  box beside it.

The status bar shows a breadcrumb of where you are.

To *build* the hierarchy, drag an element onto a box and drop it there; drag
it out to take it out again. Or select several and choose
**Arrange ▸ Group in a box** (<kbd>Ctrl</kbd>+<kbd>G</kbd>): grafli wraps
them in a new box sized to hold them and opens its label for a name.

## Go into a board and back out

A box with a `&graph` sub-board or a `.grafli` `&link` opens with
<kbd>Enter</kbd>, **Go ▸ Into the box's board**, or right-click ▸ *Into the
box's board*: the view zooms into the box and hands over to the board it
opens. <kbd>Alt</kbd>+<kbd>↑</kbd> (**Go ▸ Back up**) zooms back out to the
board you came from, exactly as you left it — same zoom, scroll and
selection. While you are inside, the breadcrumb starts with the boards you
came through, for example `System › Combat › impact()`.

To give a box a board of its own, select it and choose **Edit ▸ Attach** ▸
Sub-board (or right-click it ▸ Attach): grafli makes the board file beside
yours and takes you into it. <kbd>Enter</kbd> on a box with nothing
attached offers the same choices.

A link can point at one place in the board it opens: `&graph:combat#impact`
or `&link:../System.grafli#impact` opens the board framed on the bookmark
`impact` — or, if there is no such bookmark, on the element `impact` — with
it selected. If the board has neither, it opens fitted and says
"No element 'impact' in combat.grafli". `grafli diagnose` reports such a
link, and a link to a board that does not exist, as an error.

Once a box with a sub-board is large enough on screen, it shows a miniature
of that board, so you can see what is inside before you go in. Zooming in on
it never switches boards on its own — only <kbd>Enter</kbd> or
**Go ▸ Into the box's board** does.

A box with a `&doc` shows the first sentence of its doc below its label once
you are close enough to read it. To read the whole doc without leaving the
board, select the box and choose **Go ▸ Read the doc**: a read-only panel
opens beside the box, and <kbd>Esc</kbd> closes it.
**Edit ▸ Edit in a window** edits the doc.

## Follow the wiring

To trace how things connect rather than where they sit:

- **Right-click ▸ Follow an arrow** on a box lists the boxes its arrows lead
  to (→) and come from (←); pick one to select it and bring it into view.
- **View ▸ Focus on connections** shows only the selected box and what
  touches it; **View ▸ Focus: one hop ⇄ all** narrows that to its direct
  neighbours. Choose Focus on connections again, or <kbd>Esc</kbd>, to see
  everything.

## Zoom and frame

- The wheel or a pinch zooms; a two-finger scroll pans.
- <kbd>Ctrl</kbd>+<kbd>+</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd> zoom in and
  out, <kbd>Ctrl</kbd>+<kbd>0</kbd> fits the whole board (**View ▸ Zoom to
  fit**, also on the toolbar).
- Pan with the middle button, or hold <kbd>Space</kbd> and drag. With
  nothing selected the arrow keys pan too. (The right button opens the
  menu, so it does not pan here.)

## Retrace your steps

grafli keeps a history of where you have looked:

- <kbd>Alt</kbd>+<kbd>←</kbd> (**Go ▸ Back**) — the previous view.
- <kbd>Alt</kbd>+<kbd>→</kbd> (**Go ▸ Forward**) — forward again.

## Keep the big picture in view

- **View ▸ Minimap** — a corner overview with your viewport in it; drag
  the rectangle to move.
- **View ▸ Connectivity heatmap** — colours boxes by how many graph arrows
  touch them. When the board has [overlay files](format.md#overlay-files)
  beside it, choosing it again shows each of them in turn, with a legend.
- **View ▸ Dim notes** and **View ▸ Dim arrows** quieten what you are not
  looking at.

## Read a board zoomed out (semantic zoom)

Zoom a large board far out (<kbd>Ctrl</kbd>+<kbd>-</kbd>, the wheel, or
<kbd>Ctrl</kbd>+<kbd>0</kbd> to fit it all) and grafli summarises it instead
of shrinking it into specks — like a map that drops street names before town
names:

- **Containers fold into tiles.** A group whose children are too small to
  read collapses to one tile with its label; arrows re-route to the tile.
  Tiles at the same nesting level show their titles at the same size.
- **Small boxes become shells**: their colour stays, bars stand in for the
  unreadable label.
- **Loose clusters get a hull**: three or more connected free boxes close
  together wrap in a labelled outline.
- **Notes and images** too: a note too small to read shows a marker.

At 100 % the board is always shown in full, and the summary follows your
edits as you make them. Tiles and hulls are read-only — you edit at full
detail: double-click a tile or a hull to fly into that group, or zoom back
in. **View ▸ Level of detail** switches the summarising off and on; while it
is summarising, the status bar shows `◧ LoD` and the minimap outlines what
is folded.

## Across files and boards

**File ▸ Open…** opens another board beside the ones open; **File ▸ Switch
board…** picks among them (or a `.grafli` file nearby), **File ▸ Last board**
goes back to the one before, <kbd>Ctrl</kbd>+<kbd>W</kbd> closes the board
you are on. Every board saves itself as you go; <kbd>Ctrl</kbd>+<kbd>S</kbd>
saves at once.

## Tours

**Tours ▸ Bookmark the view** keeps what you see (or the selection) as a
stop; **Tours ▸ Record a flow** collects the bookmarks you take next into a
tour; **Tours ▸ Edit flows** opens them in the Tools panel to reorder and
time them. <kbd>F5</kbd> presents the tour fullscreen: <kbd>Space</kbd> or
<kbd>→</kbd> goes on, <kbd>←</kbd> back, <kbd>Esc</kbd> stops, and a
right-click holds the rest — play, pause or loop, smooth camera — since the
menu bar is hidden while presenting.
[Bookmarks & flows](bookmarks-flows.md) covers what a tour can do.

## Share the map as one page

**File ▸ Export** ▸ HTML page… writes the board and every board reachable
from it into one HTML file that opens in any browser, with no server. The
page has its own controls, the same in both schemes: see
[Share the map as one page](navigating.md#share-the-map-as-one-page).

## Hand a change to your agent

A Claude Code session you run can edit the board you are looking at:
<kbd>Ctrl</kbd>+<kbd>L</kbd> (**Agent ▸ Agent line…**) opens a line along
the bottom of the canvas for a grafli line or a sentence, and
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>L</kbd> or **Right-click ▸ Ask the
agent about this…** asks about one element. Its edits glow in purple, and
**Agent ▸ Undo the agent's edit** takes the last one back. How to connect
the session, and what you see while it works, is in
[In the desktop app](ai.md#in-the-desktop-app-hand-single-changes-to-your-agent);
[Your agent](standard-controls.md#your-agent) lists the controls.

## Show a board live in a browser tab

`grafli serve` shows boards in browser tabs with their own mouse controls
and keys; the desktop app's scheme does not change them. See
[Show a board live in a browser tab](navigating.md#show-a-board-live-in-a-browser-tab).
