# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-01

First public release of grafli on PyPI.

### Added

#### Editing
- Modal editing — Select (`v`), Rect (`n`), Text (`t`), Connect (`c`),
  with sticky variants for repeated creation.
- Style sub-mode (`s`) and dimension sub-mode (`d`) for color, size, and
  resize without leaving the keyboard.
- Directional creation — `Ctrl+h` / `Ctrl+k` / `Ctrl+l` spawn a connected
  neighbor box (with arrow); `o` / `O` create adjacent boxes below /
  above the selection.
- Smart arrow routing — edges snap to the nearest box boundary;
  bidirectional pairs merge automatically.
- Undo/redo with up to 50 history states; copy/paste with `y` / `p`.

#### Diagram primitives
- **Boxes** with labels, anchored placement, free nesting via `>parent`,
  and color/size sub-mode cycling.
- **Arrows** with directional, bidirectional, and headless operators
  (`->`, `<-`, `<->`, `--`), optional labels, and dashed/flat styles.
- **Notes** — free-form text blocks, optionally child of any box.
- **Color tokens** — `%primary`, `%secondary`, `%tertiary`, `%accent`,
  `%subtle`, `%muted`, plus arbitrary `#rrggbb` hex.

#### Annotations
- **Tasks** (`T:`) and **questions** (`Q:`) lead-prefixes render with
  distinct colors so review work is visible at a glance.
- **Threaded discussions** — multi-speaker notes (`AI:`, `Reviewer:`,
  arbitrary speaker names) format as conversation bubbles inside a
  single note.
- **Code-mode notes** — lines starting with `code:` render as
  syntax-highlighted pseudocode with system-design keywords (`fn`,
  `if`, `then`, `else`, `for`, `while`, `call`, `await`, `emit`, `try`,
  `catch`, `set`, `state`, `assert`, `pre`, `post`, `verify`, `risk`,
  `return`, `err`, `note`) and `@path:line` source references.
- **Semantic edge-label prefixes** — `call:`, `data:`, `event:`,
  `state:`, `step:`, `verify:`, `owns:`, `depends:`, `risk:`, `note:`
  render as colored chips on arrows and tint the edge.
- **Markdown resources** — attach a markdown file to any element and
  edit it in a full-window zen editor with vim-style keybindings.
- **URLs** on any element — `W` to set, `Return` to open in browser.

#### Navigation
- Fuzzy **search** by label with `/`.
- **Jump labels** (`Ctrl+J`) overlay one- or two-character labels on
  every visible item; press the label to select.
- **Graph navigation** — hold `Alt` to see connector keys; chain hops
  along edges chord by chord.
- **Hierarchy traversal** — `gp` parent (zoom if needed), `F` first
  child, `Tab` / `Shift+Tab` cycle siblings; ancestry breadcrumb in
  the status bar.
- **Jumplist** — `Ctrl+O` / `Ctrl+I` for vim-style viewport history.
- **Sub-graflis** — link any node to a deeper diagram in its own file;
  click through and return.

#### Visualization
- **Subgraph focus** — `B` fades elements not reachable from the
  selection, cycling direction (all → forward → backward); `Shift+B`
  toggles 1-hop vs unlimited depth.
- **Complexity heatmap** (`A`) colors nodes by connectivity to surface
  refactoring candidates.
- **Minimap** (`M`) toggles an overview panel.
- **Tools panel** (`\`) toggles the side panel.
- **Auto-layout** (`=`) lays out the selection or the whole diagram.
- **Arrow dimming** (`,`) fades arrows for label-first reading.

#### File format
- Plain-text `.grafli` v1 — line-oriented, one element per line, with
  `#` comments and a `#!grafli v1` header.
- **Triple-quoted note blocks** for multi-line text and notes
  containing quote characters; the serializer auto-promotes single-line
  notes that contain quotes.
- **External edit watching** — changes from your editor reload
  automatically.
- **Auto-save** — changes persist within 300 ms.

#### Export & sharing
- **Yank as PNG** (`Y`) — copy the diagram to the clipboard.
- **SVG export** (`Ctrl+E`) — clean vector output.
- **Buffers** — `Ctrl+K` to switch, `Ctrl+6` to toggle last, `Q` to
  close.

#### Tooling
- In-app **F1 cheat sheet** with live filter and a Text Annotations
  reference tab.
- **Documentation site** (MkDocs Material) at
  <https://grafli.mistergc.dev>.

### Requirements
- Python 3.12+
- PySide6 (Qt 6.7+)

[Unreleased]: https://github.com/MisterGC/grafli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MisterGC/grafli/releases/tag/v0.1.0
