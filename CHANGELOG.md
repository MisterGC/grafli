# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Inline vim-capable note editing** ([#66]). Editing a note (`e` /
  double-click) now opens a small vim editor in place on the canvas —
  the same keybindings as the full-window zen editor, without leaving
  the diagram. Opens in INSERT (type right away); `Esc` drops to NORMAL,
  a second `Esc` commits, `Shift+Esc` discards, clicking away commits.
  Markdown (`md:`) notes are syntax-highlighted while editing. The
  editor lives in a new dependency-clean `grafli.editor` package so the
  reusable widget can later move into a standalone editor project.
- **Markdown-mode notes** ([#65]). A note whose first non-empty line is
  `md:` (or `markdown:`) renders its body as a small subset of
  GitHub-flavoured Markdown — headings, bullet / ordered / task lists,
  blockquotes, horizontal rules, fenced and inline code (on a muted
  plate), inline `**bold**` / `*italic*` / `~~strike~~`, and clickable
  `[text](url)` links. A sibling of code-mode: a formatted block on the
  same beige plate with near-black body text. Rendered via Qt's
  `QTextDocument` Markdown engine, so it honours `~size` / `~width` and
  drag-to-resize like other notes.

## [0.3.0] - 2026-05-09

### Added
- **Notes auto-wrap to a width budget** ([#27]). Plain-text and code-mode
  notes now soft-wrap to **80 characters by default** — long
  AI-generated sentences flow onto multiple readable lines instead of
  running off the canvas. Explicit `\n`, blank lines, and leading
  indentation are preserved across wraps. Code-mode continuations use
  a two-space hanging indent so block structure stays visible.
- **Per-note width override** via `~width=N` modifier ([#28]) (placed after
  `~size`, before `!style`), e.g.
  `@ note n1 0,0 "..." ~small ~width=60`.
- **Drag-to-resize note width** ([#29]). The right edge of plain-text and
  code-mode notes is now a horizontal resize handle: hover shows
  `SizeHorCursor`, drag updates `wrap_chars` live and persists as
  `~width=N` on next save. Height auto-derives from the wrapped
  content.
- **Search (`/`) is now a dim-filter** ([#30]). Typing dims everything that
  doesn't match to 8% opacity so hits stand out across the canvas.
  `Tab` / `Shift+Tab` cycle between matches with an animated zoom and
  the selection follows; `Enter` dismisses the input but keeps the
  filter so you can pan/zoom around the highlighted set; `Esc`
  clears the filter. Matches search box label + id and note text
  (case-insensitive substring). The filter is mutually exclusive
  with focus / complexity / arrow-dim — opening one closes the
  others. The minimap now reflects the dimmed set so off-screen
  hits are still visible at a glance. The search input is a
  viewport overlay (drawn in viewport coordinates) so it stays put
  while you pan and zoom — earlier it was a scene item that scaled
  and scrolled away with the canvas. `/` also works on non-US
  layouts where typing the slash needs Shift+7.

### Changed
- **Zoom hotkeys redesigned** ([#31]). `z` now zooms *in* to the next step
  in `25% → 50% → 100% → 150%`, wrapping back to 25% after 150%.
  Works regardless of selection state. Direction is always "in",
  so a single keypress is predictable; if you ever need to go
  smaller you keep pressing until it wraps. `Shift+Z` zooms to fit
  the whole graph.
- **Search cycling pins zoom at 100%** ([#32]). Tabbing through search
  matches now lands at a consistent 100% zoom each time, so hits
  are easy to compare regardless of where the user was zoomed
  before. Previously the view fit each match individually,
  producing wildly different zoom levels per result.

### Fixed
- **Autoscroll fights leftward drags on oversize parents** ([#33]). The
  drag-autoscroll timer triggered whenever any edge of the dragged
  item was past a viewport-edge margin — for a parent box wider or
  taller than the viewport that was always true, so dragging left
  scrolled right. Autoscroll is now driven by the **cursor's**
  distance from the viewport edges, which is what reflects user
  intent. If the cursor leaves the viewport entirely mid-drag, the
  timer pauses rather than guessing direction.
- **`grafli render` clipped wide-and-short diagrams** ([#34]). Setting
  `QImage.setDevicePixelRatio(2)` *before* `QGraphicsScene.render(...)`
  with a null target rect made Qt drop most of the scene — the bug
  surfaced only for certain aspect ratios (LR pipelines like the new
  skill-pipeline diagram on `docs/ai.md` rendered to a near-blank PNG).
  The render path now passes an explicit pixel-extent target rect and
  defers the DPR setting until after the paint completes. Tall diagrams
  (e.g. the RPG-engine example) were also subtly affected; the fix
  produces complete renders for both shapes.

[#27]: https://github.com/MisterGC/grafli/issues/27
[#28]: https://github.com/MisterGC/grafli/issues/28
[#29]: https://github.com/MisterGC/grafli/issues/29
[#30]: https://github.com/MisterGC/grafli/issues/30
[#31]: https://github.com/MisterGC/grafli/issues/31
[#32]: https://github.com/MisterGC/grafli/issues/32
[#33]: https://github.com/MisterGC/grafli/issues/33
[#34]: https://github.com/MisterGC/grafli/issues/34
[#65]: https://github.com/MisterGC/grafli/issues/65
[#66]: https://github.com/MisterGC/grafli/issues/66

## [0.2.0] - 2026-05-05

### Added
- **AI skill bundled with the package.** `grafli/skills/grafli/SKILL.md`
  ships inside the wheel; extract via `grafli skill` (prints to stdout)
  or `grafli skill -o SKILL.md`. The skill teaches Claude Code,
  OpenCode, or Codex CLI agents how to author idiomatic `.grafli`
  files — format reference, planning loop, layout discipline,
  code-mode style guidance, common-mistakes checklist. Triggers only
  on explicit visualization requests so it doesn't pollute unrelated
  conversations.
- **`grafli render` CLI** — headless PNG / SVG render of a `.grafli`
  file without opening a window:
  `grafli render input.grafli output.png [--width N] [--padding N]`.
  Useful for docs-as-code workflows, snapshot tests, and skill
  iteration. Uses `QT_QPA_PLATFORM=offscreen` automatically.
- **"Pair with your AI" docs section** — README adds an install /
  usage block right after the screenshot. New `docs/ai.md` page
  covers the longer story (why a skill, what it triggers on, render
  workflow, graph + code-mode pattern). Fourth pillar added to the
  homepage *Why grafli* row.

### Fixed
- `examples/architecture.grafli` referenced an attached PNG that was
  never committed — the example now ships with its companion image
  so the diagram renders cleanly out of the box.

## [0.1.1] - 2026-05-03

### Fixed
- `RuntimeError: libshiboken: Internal C++ object … already deleted`
  when switching modes (via the side-panel buttons or `n` / `t` / `c`
  shortcuts) after a file open or scene reload. The floating mode
  badge's Python references survived the scene rebuild that auto-deletes
  their C++ counterparts; the next mode switch tried to remove the dead
  items. The badge cleanup is now defensive and the references are
  reset on `load_board`.

## [0.1.0] - 2026-05-03

First public release of grafli on PyPI.

### Added

#### Editing
- Modal editing — Select (`v`), Rect (`n`), Text (`t`), Connect (`c`).
  Click without modifier creates one element and exits to Select; hold
  `Shift` while clicking to stay in the create mode for rapid placement.
- **Ghost preview in create modes** — a semi-transparent box / note
  follows the cursor with prefilled placeholder text (*A Node* /
  *Some text …*). The placeholder also lands on the created element so
  the auto-opened editor is ready for type-replace.
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
  distinct colors so review work is visible at a glance. Both prefixes
  are case-insensitive and accept long forms (`TODO:` / `todo:`,
  `QUESTION:` / `question:`); the rendered badge is normalised to the
  short form for visual consistency.
- **Threaded discussions** — multi-speaker notes (`AI:`, `Reviewer:`,
  arbitrary speaker names) format as conversation bubbles inside a
  single note.
- **Code-mode notes** — lines starting with `code:` render as a
  stylized pseudocode block for review-oriented diagrams:
    - The first body line is the **function signature**, rendered bold
      with a divider rule beneath. Indentation carries block structure;
      indent guides are drawn automatically. Trailing `:` on keywords
      is optional.
    - **Flow keywords** (blue, bold): `if`, `else`, `for`, `while`,
      `try`, `catch`, `return`, `call`, `await`, `emit`, `state`.
    - **Contract keywords** (red, bold): `pre`, `post`, `assert`,
      `verify`, `risk`, `err`. Reviewer's eye lands here first.
    - **Clickable `@path:line` refs** open the file at that line in the
      configured editor (`editor/command` setting; auto-detects `code` /
      `cursor` / `subl`; falls back to `QDesktopServices`).
    - **Italic, muted comments** with `# …`. Plain assignments
      (`out = []`) need no keyword. String / hex / number / boolean
      literals are tokenised as values.
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
- **Arrow dimming** (`,`) fades arrows for label-first reading.
- **Note dimming** (`Shift+N`) fades notes and their connector arrows
  to 8% opacity so the bare graph reads cleanly.
- **Minimap** (`M`) toggles a corner overview showing boxes, notes,
  and connector density.
- **Tools panel** (`\`) toggles the side panel; the *View* section
  also exposes the three view-toggles (notes, edges, complexity) as
  buttons.
- **Auto-layout** (`=`) lays out the selection or the whole diagram.

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

[Unreleased]: https://github.com/MisterGC/grafli/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/MisterGC/grafli/releases/tag/v0.2.0
[0.1.1]: https://github.com/MisterGC/grafli/releases/tag/v0.1.1
[0.1.0]: https://github.com/MisterGC/grafli/releases/tag/v0.1.0
