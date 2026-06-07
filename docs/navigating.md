# Navigating graphs efficiently

Once a diagram outgrows a single screen, the bottleneck stops being *drawing*
and becomes *moving around*: find the thing, zoom in, edit it, zoom back out,
find the next thing. grafli is built so that whole loop stays on the keyboard
and takes a handful of keystrokes — no pan-drag-scroll-wheel dance.

This page is the tour of what's possible. For the exhaustive table see
[Keybindings](keybindings.md).

## The overview → focus → overview loop

The single most common rhythm is: sit in an overview, dive into one element,
edit it, pop back out. That's one verb in grafli:

- Select an element (jump to it, search for it, or click it).
- <kbd>g</kbd><kbd>z</kbd> — **focus**: the selection zooms up to fill the
  viewport, and grafli remembers where you came from.
- <kbd>e</kbd> — edit it inline.
- <kbd>g</kbd><kbd>z</kbd> again — **fly back** to the exact overview you left.

!!! tip "Hop between elements without losing your way out"
    While focused, change the selection and press <kbd>g</kbd><kbd>z</kbd>
    again — it re-focuses on the new element but *keeps* your original return
    view. A final <kbd>g</kbd><kbd>z</kbd> always lands you back where the loop
    started.

Everything below is a faster way to do the "select an element" and "find your
way around" parts of that loop.

## Find and select an element

- **Jump labels** — <kbd>f</kbd> (or <kbd>Ctrl</kbd>+<kbd>J</kbd>) tags every
  visible item with a one- or two-character label; type it to select that item.
  This is the fastest way to put the cursor on something you can see.
- **Search** — <kbd>/</kbd> fuzzy-matches by label and dims everything else.
  <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> cycle the matches;
  <kbd>Esc</kbd> clears the filter.

![Jump-mode active — every visible item carries a one- or two-character label](assets/screenshots/jump-labels.png)

## Move through the hierarchy

When boxes are nested, walk the tree directly instead of hunting visually:

- <kbd>g</kbd><kbd>p</kbd> — select the **parent** (and zoom to it if it isn't
  fully on screen).
- <kbd>g</kbd><kbd>c</kbd> — select the **first child**.
- <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> — cycle **siblings**.

The status bar shows a breadcrumb of where you are, so you always know your
depth.

To *build* that hierarchy, select one or more elements and press
<kbd>Ctrl</kbd>+<kbd>G</kbd> — grafli wraps them in a new parent box sized to
contain them, then opens its label editor so you can name the group. Inner
nesting is preserved, and if everything you selected already shared a parent,
the new box slots in beside them under it. Drag an element onto a box to nest it
the other way around.

## Follow the wiring

To trace how things connect rather than where they sit:

- **Graph navigation** — hold <kbd>Alt</kbd> and grafli overlays a key on each
  connector leaving the current node; press it to hop along that edge, chord by
  chord.
- **Subgraph focus** — <kbd>B</kbd> isolates the selected node and its
  neighbourhood (press again to cycle direction); <kbd>Shift</kbd>+<kbd>B</kbd>
  toggles between the full subgraph and just one hop. Great for "show me only
  what touches this".

## Zoom and frame

- <kbd>+</kbd> / <kbd>-</kbd> — zoom in / out, anchored on your selection.
- <kbd>z</kbd> — step through fixed zoom levels (25 → 50 → 100 → 150 %, wraps).
- <kbd>Shift</kbd>+<kbd>Z</kbd> — zoom to fit the **whole graph** (your reset to
  overview).
- <kbd>g</kbd><kbd>z</kbd> — focus the selection / fly back (see above).

## Retrace your steps

grafli keeps a vim-style jumplist of viewports:

- <kbd>Ctrl</kbd>+<kbd>O</kbd> — jump **back** to the previous viewport.
- <kbd>Ctrl</kbd>+<kbd>I</kbd> — jump **forward** again.

Any navigation jump (a jump-label, <kbd>g</kbd><kbd>p</kbd>, a zoom step) pushes
onto this list, so you can always undo your way back through where you've
looked.

## Keep the big picture in view

- <kbd>M</kbd> — toggle the **minimap**: a corner overview with your viewport
  rectangle, so you never lose your bearings in a large graph.
- <kbd>A</kbd> — **complexity heatmap**: colours nodes by how connected/busy
  they are, to spot where the density is.

## Across files

A node can link to a deeper diagram in its own `.grafli` file (a *sub-grafli*).
Click through to descend into it, edit, and come back — so a large system can
be a shallow top-level map plus focused drill-downs instead of one giant
canvas.

## When you want to *explain* the path

Ad-hoc navigation is for working. When you want to capture a route through the
graph to replay or share, use **bookmarks and flows** — labeled viewpoints
strung into a guided tour you can step through, present, or export to PDF. See
[Bookmarks & flows](bookmarks-flows.md).
