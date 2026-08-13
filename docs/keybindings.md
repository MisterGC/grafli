# Keybindings

Grafli is modal. Most commands are a single key in **Select** mode (the
default). The full cheat sheet is also available in-app via <kbd>F1</kbd>,
with live filtering.

## Modes

| Key | Mode |
|-----|------|
| <kbd>v</kbd> | Select |
| <kbd>n</kbd> | Create node — <kbd>Shift</kbd>+click stays in mode |
| <kbd>t</kbd> | Create note — <kbd>Shift</kbd>+click stays in mode |
| <kbd>c</kbd> | Connect arrow (one-shot) |
| <kbd>s</kbd> | Style sub-mode (colors, sizes) |
| <kbd>d</kbd> | Dimension sub-mode (resize) |
| <kbd>Escape</kbd> | Cancel / back to Select |

In `n` / `t` mode a semi-transparent ghost preview follows the cursor
showing where the new element will land. Clicking creates the element
and exits to Select; holding <kbd>Shift</kbd> while clicking keeps you
in the create mode for rapid placement. New elements come prefilled with
placeholder text (*A Node* / *Some text …*) so the auto-opened editor
lands on the placeholder ready to type-replace.

## File

| Key | Action |
|-----|--------|
| <kbd>⌘</kbd>+<kbd>N</kbd> | New file |
| <kbd>⌘</kbd>+<kbd>O</kbd> | Open file |
| <kbd>⌘</kbd>+<kbd>S</kbd> | Save file |
| <kbd>⌘</kbd>+<kbd>Q</kbd> | Quit |

## Navigate

| Key | Action |
|-----|--------|
| Arrow keys | Pan viewport |
| Middle-drag / Right-drag | Pan from anywhere |
| <kbd>+</kbd> / <kbd>-</kbd> | Zoom in / out |
| <kbd>z</kbd> | Zoom-in step cycle: 25 → 50 → 100 → 150 % (wraps) |
| <kbd>Shift</kbd>+<kbd>Z</kbd> | Zoom to fit (whole graph) |
| <kbd>g</kbd><kbd>z</kbd> | Focus: zoom the selection to fill the viewport; press again to fly back. Re-press after changing the selection to re-focus |
| <kbd>g</kbd><kbd>p</kbd> | Select parent (zoom if needed) |
| <kbd>g</kbd><kbd>c</kbd> | Select first child |
| <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> | Cycle siblings (or search matches when search is open) |
| <kbd>f</kbd> / <kbd>Ctrl</kbd>+<kbd>J</kbd> | Jump to any item (global) |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> / <kbd>Ctrl</kbd>+<kbd>I</kbd> | Nav history back / forward |
| <kbd>Alt</kbd> (hold) | Graph nav: follow connectors |
| <kbd>/</kbd> | Search dim-filter — see [Search](#search) below |

## Edit

| Key | Action |
|-----|--------|
| <kbd>e</kbd> / Double-click | Edit what the element **is** — box label / note text inline; an image's file opens in its system app (e.g. Inkscape for `.svg`) |
| <kbd>E</kbd> | Open [textli](https://mistergc.github.io/textli/) (the full-window Markdown editor) — edits a **note's own text**; for a box/image, opens (or creates) its attached markdown file |
| <kbd>W</kbd> | Set URL on selected item |
| <kbd>Return</kbd> | Open URL in browser |
| <kbd>Enter</kbd> | Accept edit |
| <kbd>y</kbd> / <kbd>p</kbd> | Yank / paste |
| <kbd>u</kbd> / <kbd>⌘</kbd>+<kbd>Z</kbd> | Undo |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> / <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> | Redo |
| <kbd>x</kbd> / <kbd>Delete</kbd> | Delete selection |
| <kbd>Ctrl</kbd>+<kbd>G</kbd> | Insert glyph (while editing a label) |

### Editing a note (vim)

Editing a note (<kbd>e</kbd> / double-click) opens a small **vim-capable**
editor in place — the same keybindings as textli's full editor, without
leaving the canvas. It opens in INSERT mode so you can type right
away; Markdown (`md:`) notes are syntax-highlighted.

| Key | Action |
|-----|--------|
| <kbd>Esc</kbd> (in INSERT) | Drop to NORMAL mode (vim motions/edits) |
| <kbd>Esc</kbd> (in NORMAL) | Commit and close |
| <kbd>Shift</kbd>+<kbd>Esc</kbd> (in NORMAL) | Discard and close |
| Click elsewhere | Commit and close |

### The full editor (textli)

<kbd>E</kbd> opens [textli](https://mistergc.github.io/textli/), grafli's
Markdown editor and its own project. Writing keys, the rendered reading view
(<kbd>⌘</kbd>+<kbd>R</kbd>), and the comment / suggestion review workflow are
documented in the
[textli key reference](https://mistergc.github.io/textli/keybindings/) — or
press <kbd>F1</kbd> inside the editor. See
[Text annotations](text-annotations.md) for how it fits into a review flow.

## Create

| Key | Action |
|-----|--------|
| <kbd>o</kbd> / <kbd>O</kbd> | Create box below / above selection |
| <kbd>Ctrl</kbd>+<kbd>G</kbd> | Encapsulate selection in a new parent box |
| <kbd>Ctrl</kbd>+arrow | Create connected box in that direction |
| <kbd>Alt</kbd>+drag | Connect nodes — boxes, notes, images (from Select) |
| <kbd>Alt</kbd>+click | Paste at position |

## Style

With a selection, press <kbd>s</kbd> to enter style mode, then any of the keys
below. Each one means the same thing whatever is selected — <kbd>e</kbd> is
appearance, <kbd>c</kbd> is colour, <kbd>t</kbd> is text, <kbd>i</kbd> is
symbols — so the map doesn't change under you when you switch from a box to a
connector.

| Key | Action |
|-----|--------|
| <kbd>e</kbd> | Element appearance overlay — box: background (plate / flat) and label position (center / top-left / top-center); note: background; image: frame (auto / frame / none). `j`/`k` pick a row, `h`/`l` cycle it, <kbd>Enter</kbd> commits, <kbd>Esc</kbd> cancels. A **flat** box with a **top-left** label is the container look, which is how you draw a layer band that has no children |
| <kbd>c</kbd> | Open the color grid — <kbd>h</kbd><kbd>j</kbd><kbd>k</kbd><kbd>l</kbd> to pick (live preview), <kbd>Enter</kbd> to confirm, <kbd>Esc</kbd> to cancel |
| <kbd>i</kbd> | Open the symbol grid (sketchnote vocabulary, semantic + emphasis blocks) — same keys; <kbd>Tab</kbd> cycles placement (fill → lead → badge); <kbd>1</kbd>–<kbd>9</kbd> types a number badge (a second press appends: 1,2 → 12). Fill: big symbol + caption. Lead: small symbol beside the label. Badge: compact top-right corner overlay |
| <kbd>t</kbd> | Open the text grid — rows = sizes, columns = Regular / Bold / Italic / Bold+Italic; <kbd>hjkl</kbd> to move (live preview), <kbd>Tab</kbd> toggles a note's font (handwritten ↔ monospace), <kbd>Enter</kbd> to confirm, <kbd>Esc</kbd> to cancel |
| <kbd>j</kbd> / <kbd>k</kbd> | Cycle text size (quick nudge) |
| <kbd>d</kbd> then <kbd>r</kbd> | Snap selected box(es) to the **slide aspect ratio** — a reusable export frame (re-apply after edits; works on a multi-selection) |
| <kbd>Shift</kbd>+<kbd>G</kbd> | Snap to grid |
| <kbd>=</kbd> | Auto-layout selection (or all) |

## Focus & analysis

| Key | Action |
|-----|--------|
| <kbd>,</kbd> | Dim arrows |
| <kbd>Shift</kbd>+<kbd>N</kbd> | Dim notes (and their connectors) |
| <kbd>A</kbd> | Complexity heatmap |
| <kbd>B</kbd> | Subgraph focus (cycle direction: all → forward → backward) |
| <kbd>Shift</kbd>+<kbd>B</kbd> | Toggle focus depth (full / 1-hop) |

The same three view-toggles also have buttons in the side panel's *View*
section.

## View

| Key | Action |
|-----|--------|
| <kbd>#</kbd> | Toggle grid |
| <kbd>M</kbd> | Toggle minimap |
| <kbd>\\</kbd> | Toggle tools panel |
| <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd> | Toggle light / dark theme — or click the sun/moon button next to the tools button |

### Light and dark

grafli ships two themes: the warm paper light theme and a dark counterpart in
the same style — same semantic roles, same contrast relationships, just a
low-key ground. Switch with <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd>, or click
the sun/moon button in the top-left of the canvas (it shows the theme you'd
switch *to*). The choice applies immediately and is remembered across restarts.

Colour tokens (`%accent`, `%primary`, …) are semantic, so they re-resolve per
theme and a `.grafli` written by someone on light reads correctly on dark. A
literal hex (`#C0FFEE`) is always kept exactly as written.

Headless renders don't follow the app's theme, so a given file and flags always
produce the same image. Pick one explicitly:

```bash
grafli render board.grafli out.png              # light (default)
grafli render board.grafli out.png --theme dark
```

## Export

| Key | Action |
|-----|--------|
| <kbd>Y</kbd> | Yank diagram as PNG to clipboard |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Export SVG to file |

## Arrows

| Key | Action |
|-----|--------|
| <kbd>Shift</kbd>+click | Add / remove a connector from the selection (format many at once) |
| <kbd>e</kbd> | Edit arrow label |
| <kbd>s</kbd> | Arrow style mode |
| <kbd>s</kbd> then <kbd>e</kbd> | Connector appearance overlay — heads, line pattern, thickness, routing, colour (`j`/`k` pick a row, `h`/`l` cycle it, <kbd>Enter</kbd> commits, <kbd>Esc</kbd> cancels) |
| <kbd>s</kbd> then <kbd>c</kbd> | Open the color grid — the same picker boxes and notes get |
| <kbd>s</kbd> then <kbd>t</kbd> | Connector label-text overlay (size) |
| <kbd>h</kbd> / <kbd>l</kbd> | Toggle arrowheads (in style mode) |
| <kbd>j</kbd> / <kbd>k</kbd> | Arrow label size (in style mode) |
| <kbd>Shift</kbd>+<kbd>J</kbd> / <kbd>Shift</kbd>+<kbd>K</kbd> | Cycle line pattern (in style mode) |
| <kbd>s</kbd> then <kbd>r</kbd> | Cycle connector routing: **direct** → **spline** → **stair** (in style mode) |
| <kbd>s</kbd> then <kbd>a</kbd> | Toggle connector kind: **graph edge** ⇄ **annotation** (a graph edge to a note or image makes it a node) |

## Buffers

| Key | Action |
|-----|--------|
| <kbd>Ctrl</kbd>+<kbd>K</kbd> | Open / switch buffer |
| <kbd>Ctrl</kbd>+<kbd>6</kbd> | Toggle last buffer |
| <kbd>Q</kbd> | Close buffer (no selection) |

## Bookmarks & flows

Save labeled viewpoints and string them into guided tours — see
[Bookmarks & flows](bookmarks-flows.md).

| Key | Action |
|-----|--------|
| <kbd>g</kbd><kbd>b</kbd> | Bookmark what's shown (selection, else everything visible) |
| <kbd>g</kbd><kbd>B</kbd> | Bookmark the exact viewport (pixel-faithful framing) |
| <kbd>g</kbd><kbd>f</kbd> | Start / stop flow recording (each capture is appended) |
| <kbd>g</kbd><kbd>F</kbd> | Auto-flow: generate a flow by walking forward arrows from the selected node |
| <kbd>F5</kbd> | Present the current flow fullscreen (chrome hidden, paused) |

During playback (in-app or presenting):

| Key | Action |
|-----|--------|
| <kbd>Space</kbd> / <kbd>→</kbd> | Next stop |
| <kbd>←</kbd> | Previous stop |
| <kbd>t</kbd> | Toggle smooth camera ↔ instant cuts |
| <kbd>p</kbd> | Cycle paused → playing → playing (loop) |
| <kbd>Esc</kbd> | Exit playback |

## Mouse

| Action | Effect |
|--------|--------|
| Click `@path:line` in a code-mode note | Open the file at that line in the configured editor |
| <kbd>Shift</kbd>+click | Toggle selection (on empty space or a node's body) |
| Drag a **corner handle** | **Scale** the selection — size *and* font, around its bounding box; keeps the aspect ratio. A preview frame shows where it lands and it commits on release. Hold <kbd>Shift</kbd> for a free (non-uniform) scale |
| Drag an **edge handle** | Stretch that single axis (modifier-agnostic) |
| <kbd>Alt</kbd>+drag | Connect nodes (boxes, notes, images) |
| <kbd>Alt</kbd>+click | Paste at position |

## Search

Press <kbd>/</kbd> to open the search dim-filter. Typing dims everything that
doesn't match to ~8% opacity so hits stand out across the canvas at once;
the minimap reflects the same dimming so off-screen hits stay visible.

| Key | Action |
|-----|--------|
| <kbd>/</kbd> | Open search input (works on non-US layouts where `/` needs <kbd>Shift</kbd>+<kbd>7</kbd>) |
| Type | Live filter — matches box label + box id + note text (case-insensitive substring) |
| <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> | Cycle to next / previous match (animated, lands at 100 % zoom) |
| <kbd>Enter</kbd> | Dismiss the input badge but keep the dim filter active |
| <kbd>Esc</kbd> | Clear the input and the filter |
| <kbd>Backspace</kbd> | Edit the query |

Search is mutually exclusive with focus / complexity / arrow-dim — opening
one closes the others.

## Help

| Key | Action |
|-----|--------|
| <kbd>F1</kbd> | In-app cheat sheet (with filter) and text-annotation reference |
| <kbd>`</kbd> | Toggle debug overlay |
