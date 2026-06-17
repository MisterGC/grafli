# File format

A `.grafli` file is line-oriented plain text. One element per line. Lines
that start with `#` are comments. Order does not affect rendering — the
layout is encoded in each element's coordinates.

## Header

```text
#!grafli v1
```

The first line is a shebang-style header that identifies the format and
its version. It is required.

## Element types

```text
@ box <id> "<label>" <x>,<y> <w>x<h> [color] [^anchor] [~size] [!style] [>parent]
@ note [<id>] <x>,<y> "<text>" [color] [~size] [~width=N] [!style] [>parent]
@ arrow <from> <op> <to> ["label"] [!style] [~size]
```

| Element | Purpose |
|---------|---------|
| `box`   | Rectangular container with a label. Can nest via `>parent`. |
| `note`  | Free-form text block. Supports tasks, questions, code-mode, Markdown-mode, and discussions (see [Text annotations](text-annotations.md)). |
| `arrow` | Directed/bidirectional connector between two elements. |

### Arrow operators

| Operator | Meaning |
|----------|---------|
| `->`     | Right (from → to) |
| `<-`     | Left  (from ← to) |
| `<->`    | Bidirectional     |
| `--`     | No arrowhead      |

### Modifiers

- `<color>` — built-in tokens: `%base`, `%primary`, `%secondary`,
  `%tertiary`, `%subtle`, `%accent`, `%highlight`, `%muted`, `%soft`,
  `%clay`, `%teal`, `%rose`, `%forest`, `%plum`, or any `#rrggbb` hex value.
- `^anchor` — `topleft`, `top`, `topright`, `left`, `center`, `right`,
  `bottomleft`, `bottom`, `bottomright`. Controls how a box's label is
  placed.
- `~size` — `xsmall`, `small`, `medium`, `large`, `xlarge`.
- `~width=N` — *(notes only)* override the wrap width in characters.
  Notes auto-wrap to 80 chars by default so long AI-generated lines stay
  readable; this modifier sets a different budget per note (e.g.
  `~width=40` for a narrow caption, `~width=120` for a wide code listing).
  You can also drag the right edge of a selected note to set this
  interactively — the value persists on save.
- `!style` — `flat`, `dashed`, plus arrow-specific styles.
- `>parent` — nest this element inside the box with the given ID.

Graph connectors are drawn with a thickness proportional to the size of the
nodes they link — big containers get heavier arrows, small inner children stay
light — so a zoomed-out view reads as a clear hierarchy. This is automatic;
the weight is capped by the smaller of the two endpoints.

## Block text

When a note's text contains quote characters or spans multiple lines, use
triple quotes:

```text
@ note logic 100,320 """
code:
handleRequest(req) -> Response
call validate(req)
emit RequestAccepted(req.id)
return ok
"""
```

The serializer auto-promotes single-line notes that contain `"` to the
triple-quoted form.

## A complete example

```text
#!grafli v1
# A small architecture sketch

@ box frontend "Frontend" 100,100 160x60 %secondary
@ box backend  "Backend"  320,100 160x60 %primary
@ box db       "Database" 320,240 160x60 %subtle

@ arrow frontend -> backend "call: REST API"
@ arrow backend  -> db      "data: queries" !dashed

@ note 100,240 "SPA with React"
```

## Bookmarks and flows (v2)

Saved viewpoints and guided tours are stored in the file too. A file that
contains them uses the `v2` header; pure-diagram files stay on `v1`.

```text
@ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] ["<description>"]
@ bookmark <id> "<label>" ~view=<x>,<y>,<w>,<h> ["<description>"]
@ flow <id> "<label>" <bookmark_ref>[:<dwell>] ... ["<description>"]
```

- `@<ids>` is the **semantic anchor** — the item ids the view frames. The
  pan/zoom is computed by fitting them, so the bookmark survives layout edits.
  `~pad=<n>` overrides the framing padding.
- `~view=<x>,<y>,<w>,<h>` stores an **exact scene rect** instead, used for a
  hand-tuned framing or a viewpoint that contains no nodes. A bookmark uses
  one or the other.
- A `@ flow` lists bookmark ids in order; `:<dwell>` sets that stop's
  auto-play time in seconds (omit for the flow default).

```text
#!grafli v2
@ box api "API Gateway" 280,0 180x80 %secondary
@ box auth "Auth Service" 280,160 180x80 %soft
@ bookmark bm_auth "Authentication" @api,auth "Verified before routing."
@ flow tour "Walkthrough" bm_auth:6 "A short guided tour."
```

See [Bookmarks & flows](bookmarks-flows.md) for capturing, editing, playback,
present mode, and PDF export.

## Why plain text

- **Git-native** — every change is a line-level diff with intent baked in.
- **Editor-friendly** — open with any text editor; grafli watches the
  file and reloads automatically.
- **AI-ready** — the format is small enough that LLMs reliably read,
  modify, and emit valid diagrams from natural language.
