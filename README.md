# grafli

A lightweight diagram tool with vim-style keybindings and a plain-text file format.

grafli lets you sketch architecture diagrams, flowcharts, and UI mockups directly from your keyboard.
Files are human-readable `.grafli` text files that play well with version control.

## Features

- **Vim-style modal editing** — four modes: Select (`v`), Rect (`n`), Text (`t`), Connect (`c`). Navigate and manipulate diagrams without leaving the keyboard.
- **Plain-text file format** — `.grafli` files are readable, diffable, and mergeable. No binary blobs.
- **Boxes, arrows, and notes** — rectangular containers with labels, directed/bidirectional arrows with optional labels, and free-text notes in handwritten or monospace style.
- **Nesting and hierarchy** — boxes can contain child boxes for grouping and layout.
- **Color tokens** — a built-in palette (`%primary`, `%accent`, `%tertiary`, ...) plus arbitrary hex colors.
- **Smart arrow routing** — edges snap to box boundaries with automatic curved or straight paths.
- **Search and jump** — `/` to search by label, `Ctrl+J` for global jump labels (visible and off-screen items).
- **Hierarchy navigation** — `P` (parent), `F` (first child), `Tab` (cycle siblings) for tree traversal.
- **Graph navigation** — hold `Alt` to see connector labels, press a key to follow a connector to the target node. Chainable.
- **Navigation history** — `Ctrl+O` / `Ctrl+I` to jump back/forward through viewport history (vim-style jumplist).
- **Breadcrumb** — status bar shows ancestry path (`root > parent > child`) when a box is selected.
- **Undo/redo, copy/paste** — full history with up to 50 undo states.
- **Subgraph focus** — press `B` on a selected node to dim unrelated items and highlight the connected subgraph. Cycle direction (all/forward/backward) with repeated `B`, toggle depth with `Shift+B`.
- **Minimap** — toggle an overview map with `M`.
- **File watching** — external edits are detected and merged automatically.
- **Auto-save** — changes are persisted within 300ms.

## Quick start

```bash
pip install grafli
grafli my-diagram.grafli
```

## The `.grafli` format

```
#!grafli v1
# Architecture overview

@ box frontend "Frontend" 100,100 160x60 %secondary
@ box backend  "Backend"  320,100 160x60 %primary
@ box db       "Database" 320,240 160x60 %subtle

@ arrow frontend -> backend "REST API"
@ arrow backend  -> db      "queries" !dashed

@ note 100,240 "SPA with React"
```

Elements are one line each:

| Element | Syntax |
|---------|--------|
| Box | `@ box <id> "<label>" <x>,<y> <w>x<h> [color] [^anchor] [~size] [!style] [>parent]` |
| Arrow | `@ arrow <from> <op> <to> ["label"] [!style] [~size]` |
| Note | `@ note [<id>] <x>,<y> "<text>" [color] [~size] [!style] [>parent]` |

Arrow operators: `->` right, `<-` left, `<->` both, `--` none.

## Keybindings at a glance

| Key | Action |
|-----|--------|
| `v` / `n` / `t` / `c` | Switch mode: Select / Rect / Text / Connect |
| `h` `j` `k` `l` | Move selection (vim directions) |
| `s` | Enter style sub-mode (colors, sizes) |
| `d` | Enter dimension sub-mode (resize) |
| `gp` / `F` | Select parent / first child |
| `Tab` / `Shift+Tab` | Cycle siblings |
| `Alt` (hold) | Graph nav: follow connectors with `hjkluiop` |
| `Ctrl+O` / `Ctrl+I` | Navigation history back / forward |
| `o` / `Shift+O` | Create adjacent box below / above |
| `Ctrl+hkl` | Create connected box (left/up/right) |
| `Ctrl+Shift+hkl` | Create connected note (left/up/right) |
| `e` / `E` | Edit label / annotation |
| `y` / `p` | Yank / paste |
| `Y` | Yank diagram as PNG to clipboard |
| `Ctrl+E` | Export SVG to file |
| `#` | Toggle grid |
| `/` | Search |
| `Ctrl+J` | Jump mode (all items) |
| `B` / `Shift+B` | Subgraph focus (cycle direction / toggle depth) |
| `Z` / `Shift+Z` | Zoom to selection / fit all |
| `u` / `Ctrl+R` | Undo / redo |
| `Shift+H` | Show full keybinding cheatsheet |

## Requirements

- Python 3.12+
- PySide6 (Qt 6.7+)

## License

MIT
