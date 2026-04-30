# Keybindings

Grafli is modal. Most commands are a single key in **Select** mode (the
default). The full cheat sheet is also available in-app via <kbd>F1</kbd>,
with live filtering.

## Modes

| Key | Mode |
|-----|------|
| <kbd>v</kbd> | Select |
| <kbd>n</kbd> / <kbd>Shift</kbd>+<kbd>n</kbd> | Create node (one-shot / sticky) |
| <kbd>t</kbd> / <kbd>Shift</kbd>+<kbd>t</kbd> | Create note (one-shot / sticky) |
| <kbd>c</kbd> | Connect arrow (one-shot) |
| <kbd>s</kbd> | Style sub-mode (colors, sizes) |
| <kbd>d</kbd> | Dimension sub-mode (resize) |
| <kbd>Escape</kbd> | Cancel / back to Select |

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
| Middle-drag | Pan from anywhere |
| <kbd>+</kbd> / <kbd>-</kbd> | Zoom in / out |
| <kbd>Z</kbd> | Zoom to selection (progressive) |
| <kbd>Shift</kbd>+<kbd>Z</kbd> | Zoom to fit all |
| <kbd>g</kbd><kbd>p</kbd> | Select parent (zoom if needed) |
| <kbd>F</kbd> | Select first child |
| <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> | Cycle siblings |
| <kbd>Ctrl</kbd>+<kbd>J</kbd> | Jump to any item (global) |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> / <kbd>Ctrl</kbd>+<kbd>I</kbd> | Nav history back / forward |
| <kbd>Alt</kbd> (hold) | Graph nav: follow connectors |
| <kbd>/</kbd> | Search by label |

## Edit

| Key | Action |
|-----|--------|
| <kbd>e</kbd> / Double-click | Edit selected element |
| <kbd>E</kbd> | Edit annotation |
| <kbd>W</kbd> | Set URL on selected item |
| <kbd>Return</kbd> | Open URL in browser |
| <kbd>Enter</kbd> | Accept edit |
| <kbd>y</kbd> / <kbd>p</kbd> | Yank / paste |
| <kbd>u</kbd> / <kbd>⌘</kbd>+<kbd>Z</kbd> | Undo |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> / <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> | Redo |
| <kbd>x</kbd> / <kbd>Delete</kbd> | Delete selection |
| <kbd>⌘</kbd>+<kbd>G</kbd> | Insert glyph / replace label |

## Create

| Key | Action |
|-----|--------|
| <kbd>o</kbd> / <kbd>O</kbd> | Create box below / above selection |
| <kbd>Ctrl</kbd>+arrow | Create connected box in that direction |
| <kbd>Alt</kbd>+drag | Connect boxes (from Select) |
| <kbd>Alt</kbd>+click | Paste at position |

## Style

| Key | Action |
|-----|--------|
| <kbd>h</kbd> / <kbd>l</kbd> | Cycle color |
| <kbd>j</kbd> / <kbd>k</kbd> | Cycle text size |
| <kbd>Shift</kbd>+<kbd>G</kbd> | Snap to grid |
| <kbd>=</kbd> | Auto-layout selection (or all) |

## Focus & analysis

| Key | Action |
|-----|--------|
| <kbd>,</kbd> | Dim arrows |
| <kbd>A</kbd> | Complexity heatmap |
| <kbd>B</kbd> | Subgraph focus (cycle direction: all → forward → backward) |
| <kbd>Shift</kbd>+<kbd>B</kbd> | Toggle focus depth (full / 1-hop) |

## View

| Key | Action |
|-----|--------|
| <kbd>#</kbd> | Toggle grid |
| <kbd>M</kbd> | Toggle minimap |
| <kbd>\\</kbd> | Toggle tools panel |

## Export

| Key | Action |
|-----|--------|
| <kbd>Y</kbd> | Yank diagram as PNG to clipboard |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Export SVG to file |

## Arrows

| Key | Action |
|-----|--------|
| <kbd>e</kbd> | Edit arrow label |
| <kbd>s</kbd> | Arrow style mode |
| <kbd>h</kbd> / <kbd>l</kbd> | Toggle arrowheads |
| <kbd>j</kbd> / <kbd>k</kbd> | Arrow label size |
| <kbd>Shift</kbd>+<kbd>J</kbd> / <kbd>Shift</kbd>+<kbd>K</kbd> | Cycle arrow style |

## Buffers

| Key | Action |
|-----|--------|
| <kbd>Ctrl</kbd>+<kbd>K</kbd> | Open / switch buffer |
| <kbd>Ctrl</kbd>+<kbd>6</kbd> | Toggle last buffer |
| <kbd>Q</kbd> | Close buffer (no selection) |

## Help

| Key | Action |
|-----|--------|
| <kbd>F1</kbd> | In-app cheat sheet (with filter) and text-annotation reference |
| <kbd>`</kbd> | Toggle debug overlay |
