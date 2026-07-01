# grafli

A keyboard-driven, plain-text diagram tool for developers.

grafli lets you sketch architecture diagrams, code-review notes, and design
sketches without leaving the keyboard. Files are line-oriented `.grafli` text
that diffs cleanly in git and that LLMs can read and produce reliably.

![grafli — graph + code-mode notes in one diagram](https://raw.githubusercontent.com/MisterGC/grafli/main/docs/assets/screenshots/hero.png)

> Documentation and feature tour: **<https://grafli.mistergc.dev>**

## Pair grafli with your AI

grafli isn't just a diagram editor — it's the canvas your coding agent
uses to communicate complex systems back to you. The bundled **grafli
skill** teaches the agent how to produce idiomatic `.grafli` files —
proper layouts, semantic edge labels, code-mode notes for
review-oriented diagrams, plus a "plan before you write" loop that
keeps the output focused and readable.

Extract the skill from your installed copy and point your agent at it:

```bash
# Save to a file, or pipe straight into the right place for your tool.
grafli skill -o SKILL.md
grafli skill --where        # path of the bundled SKILL.md
grafli skill --help         # install URLs for Claude Code, OpenCode, Codex
```

| AI tool | Where the skill goes | Docs |
|---------|---------------------|------|
| Claude Code | `~/.claude/skills/grafli/SKILL.md` | <https://code.claude.com/docs/en/skills> |
| OpenCode | `~/.config/opencode/skills/grafli/SKILL.md` | <https://opencode.ai/docs/skills> |
| Codex CLI | append to `~/.codex/AGENTS.md` | <https://agents.md/> |

Once installed, ask your agent to "draw a diagram of …", "visualize the
data flow in this module", or "sketch the OAuth callback as a grafli" —
the skill triggers and produces a `.grafli` you can open in the
desktop app or render headless via `grafli render`.

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
- Code-mode notes — minimal pseudocode for review-oriented diagrams: a
  bold function signature on the first line, control/effect keywords
  (`if`, `for`, `call`, `emit`, …) in blue, contract keywords (`pre`,
  `post`, `verify`, `risk`, …) in red, and clickable `@file:line` refs.
- Tasks (`T:` / `TODO:`), questions (`Q:` / `QUESTION:`, both
  case-insensitive), and threaded discussions inside notes.
- Find and focus — combine these at will:
  - **Subgraph focus** (<kbd>B</kbd>) — fade everything not reachable from
    the selection; cycle direction (incoming / outgoing / both) and
    depth (1-hop / unlimited).
  - **Complexity heatmap** (<kbd>A</kbd>) — color nodes by connectivity
    to find hot spots.
  - **Dim connectors** (<kbd>,</kbd>) / **dim notes**
    (<kbd>Shift</kbd>+<kbd>N</kbd>) — fade arrows or text-notes to 8%
    opacity to read the rest.
  - **Minimap** (<kbd>M</kbd>) — corner overview with boxes, notes, and
    connector density.
- Jump labels and graph navigation — every visible element is one or two keys
  away; hold <kbd>Alt</kbd> to follow connectors edge by edge.
- Sub-graflis — link any node to a deeper diagram in its own file.
- Bookmarks & flows — save labeled viewpoints (semantic anchors, not pixel
  coords) and string them into guided tours: step through, auto-play, present
  fullscreen (<kbd>F5</kbd>), or export a slide PDF (`grafli export … --flow`).
  Plain text, so an AI can author an explanatory tour through a big graph.
- Markdown resources — attach a markdown note to any element and edit it in
  [textli](https://github.com/MisterGC/textli), grafli's full-window Markdown
  editor (its own project, bundled as a dependency).
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
handleRequest(req) -> Response
pre req.id is set
call validate(req)
emit RequestAccepted(req.id)
return ok  @api/handler.py:42
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
| <kbd>Shift</kbd>+click in `n`/`t` mode | Stay in create mode for rapid placement |
| <kbd>h</kbd> <kbd>j</kbd> <kbd>k</kbd> <kbd>l</kbd> | Move selection (vim directions) |
| <kbd>Ctrl</kbd>+<kbd>h</kbd>/<kbd>k</kbd>/<kbd>l</kbd> | Create connected box (left/up/right) |
| <kbd>Alt</kbd> (hold) | Graph navigation — follow connectors |
| <kbd>/</kbd> | Search by label |
| <kbd>Ctrl</kbd>+<kbd>J</kbd> | Jump mode (all visible items) |
| <kbd>B</kbd> / <kbd>Shift</kbd>+<kbd>B</kbd> | Subgraph focus (cycle direction / toggle depth) |
| <kbd>,</kbd> / <kbd>Shift</kbd>+<kbd>N</kbd> | Dim arrows / dim notes (focus on the rest) |
| <kbd>Y</kbd> / <kbd>Ctrl</kbd>+<kbd>E</kbd> | Yank PNG to clipboard / Export SVG |
| <kbd>F1</kbd> | In-app cheat sheet and text-annotation reference |

The full set is in the in-app <kbd>F1</kbd> dialog and on the documentation site.

## Project

- Documentation: <https://grafli.mistergc.dev>
- Source: <https://github.com/MisterGC/grafli>
- Issues: <https://github.com/MisterGC/grafli/issues>

## License

MIT
