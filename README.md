# grafli

A keyboard-driven, plain-text diagram tool for developers.

grafli lets you sketch architecture diagrams, code-review notes, and design
sketches without leaving the keyboard. Files are line-oriented `.grafli` text
that diffs cleanly in git and that LLMs can read and produce reliably.

> Documentation and feature tour: **<https://grafli.mistergc.dev>**

## Install

```bash
pip install grafli
grafli my-diagram.grafli
```

Requirements: Python 3.12+, PySide6 (Qt 6.7+).

## Design philosophy

- **Keyboard-first.** Modal editing in the spirit of vim — Select, Rect, Text,
  Connect — composes a small set of keystrokes into rich diagrams.
- **Less is more.** Three primitives (boxes, arrows, notes) plus visible
  containment cover the cases that matter, without a menu maze.
- **Text for AI, git, humans.** `.grafli` files are line-oriented plain text;
  there are no binary blobs and no cloud dependency.

## Capabilities at a glance

- Modal vim-style editing with directional creation (one keystroke spawns a
  connected neighbor box or note).
- Semantic edge labels — prefixes such as `call:`, `data:`, `event:`,
  `verify:`, `risk:` render as colored chips and tint their arrow.
- Code-mode notes — keyword-led pseudocode (`fn:`, `if:`, `call:`,
  `verify:`, `@file:line`) for review-oriented diagrams.
- Tasks (`T:`), questions (`Q:`), and threaded discussions inside notes.
- Subgraph focus — fade everything not reachable from the current selection;
  cycle direction (all / forward / backward) and depth (1-hop / unlimited).
- Complexity heatmap — color nodes by connectivity to find hot spots.
- Jump labels and graph navigation — every visible element is one or two keys
  away; hold <kbd>Alt</kbd> to follow connectors edge by edge.
- Sub-graflis — link any node to a deeper diagram in its own file.
- Markdown resources — attach a markdown note to any element and edit it in a
  full-window zen editor.
- Auto-save and external file watching — open a `.grafli` next to your
  editor; changes flow both ways.
- Yank as PNG (<kbd>Y</kbd>), SVG export (<kbd>Ctrl</kbd>+<kbd>E</kbd>).

## File format

```text
@ box frontend "Frontend" 100,100 160x60 %secondary
@ box backend  "Backend"  320,100 160x60 %primary
@ box db       "Database" 320,240 160x60 %subtle

@ arrow frontend -> backend "REST API"
@ arrow backend  -> db      "data: queries" !dashed

@ note 100,240 "SPA with React"
@ note logic 100,320 """
code:
fn: handleRequest(req)
call: validate(req)
emit: RequestAccepted(req.id)
return: ok
"""
```

| Element | Syntax |
|---------|--------|
| Box   | `@ box <id> "<label>" <x>,<y> <w>x<h> [color] [^anchor] [~size] [!style] [>parent]` |
| Arrow | `@ arrow <from> <op> <to> ["label"] [!style] [~size]` |
| Note  | `@ note [<id>] <x>,<y> "<text>" [color] [~size] [!style] [>parent]` |

Arrow operators: `->` right, `<-` left, `<->` both, `--` none.

Triple-quoted block notes are supported when a note contains quote characters
or spans multiple lines.

## Keybindings (selection)

| Key | Action |
|-----|--------|
| <kbd>v</kbd> / <kbd>n</kbd> / <kbd>t</kbd> / <kbd>c</kbd> | Switch mode: Select / Rect / Text / Connect |
| <kbd>h</kbd> <kbd>j</kbd> <kbd>k</kbd> <kbd>l</kbd> | Move selection (vim directions) |
| <kbd>Ctrl</kbd>+<kbd>h</kbd>/<kbd>k</kbd>/<kbd>l</kbd> | Create connected box (left/up/right) |
| <kbd>Alt</kbd> (hold) | Graph navigation — follow connectors |
| <kbd>/</kbd> | Search by label |
| <kbd>Ctrl</kbd>+<kbd>J</kbd> | Jump mode (all visible items) |
| <kbd>B</kbd> / <kbd>Shift</kbd>+<kbd>B</kbd> | Subgraph focus (cycle direction / toggle depth) |
| <kbd>Y</kbd> / <kbd>Ctrl</kbd>+<kbd>E</kbd> | Yank PNG to clipboard / Export SVG |
| <kbd>F1</kbd> | In-app cheat sheet and text-annotation reference |

The full set is in the in-app <kbd>F1</kbd> dialog and on the documentation site.

## Project

- Documentation: <https://grafli.mistergc.dev>
- Source: <https://github.com/MisterGC/grafli>
- Issues: <https://github.com/MisterGC/grafli/issues>

## License

MIT
