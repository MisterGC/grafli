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
@ arrow <from> <op> <to> ["label"] [color] [!pattern] [!thickness] [!routing] [~size]
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
  Tokens are *semantic*: each one resolves to a different value in the light
  and [dark theme](keybindings.md#light-and-dark), so a board written by
  someone on light reads correctly on dark. Prefer them over hex, which is
  kept exactly as written and so only suits one theme.
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
- `!style` — `flat`, `dashed`, plus arrow-specific styles. **Notes render in
  a handwritten face by default**; `!mono` (and `code:` notes) switch to the
  monospace face — handwriting for prose, monospace for code. (Style mode →
  `t` opens the text grid; `Tab` there toggles a note's font.)
- `!routing` *(arrows)* — how the connector travels between its ends:
  omitted for a **direct** line (the default), `!spline` for a curve, `!ortho`
  for a right-angle stair. Independent of `!pattern` and `!thickness`, so
  `!dashed !ortho` is a dashed stair. A routed connector leaves each box
  perpendicular to the side that faces the other end, and several connectors
  sharing a side are spread along it automatically — anchors are always
  derived from the board, never written into the file, so a board renders the
  same in the app and in `grafli render`. Routed connectors bend but do not
  steer around other boxes; `grafli diagnose` is the place to catch a
  connector that cuts across your layout.
- *(arrows)* a bare `%color` / `#hex` overrides the connector colour;
  `!dashed` / `!dotted` set the line pattern and `!thin` / `!thick` set the
  thickness (default width tracks the linked nodes). Select a connector (or
  shift+click several) and press `s` then `c` for a live overlay over all four
  axes — heads, line, thickness, colour — or `s` then `t` for the label text;
  the picks apply to every selected connector at once.
- `!bold` / `!italic` — *(boxes and notes)* text emphasis layered on the
  size, e.g. `~large !bold` for a heading. Combine freely (`!bold !italic`).
  (Style mode → `t` opens a size × style text grid.)
- `*symbol` — *(boxes and notes)* attach a sketchnote symbol. Three
  placements: bare `*name` is *fill* (a big symbol with the label/text as a
  caption — a framed node on a box, a borderless marker on a note);
  `*lead:name` is *lead* (a small symbol left of the label, which stays
  primary — `*lead:lock` → 🔒 Auth); `*badge:name` is *badge* (a compact
  overlay in the top-right corner, the label keeps its normal layout — for
  emphasis marks on existing nodes). Digits are *number badges*: `*3`,
  `*badge:7` (1–99) render as a circled number for sequences and rankings.
  The symbols live in `grafli/assets/sketchnote_symbols.svg` — one editable
  sheet, rendered vector-crisp at any zoom.
  *Semantic* names (what a thing is): `person`, `robot`, `gear`, `database`,
  `document`, `cloud`, `globe`, `target`, `lightbulb`, `question`, `warning`,
  `check`, `cross`, `flag`, `clock`, `calendar`, `magnifier`, `puzzle`,
  `lock`, `plant`, `money`, `link`.
  *Emphasis* names (how much it matters): `star`, `heart`, `flame`,
  `exclamation`, `brain`, `lightning`, `repeat`, `exercise`, `performance`.
  Legacy `bulb`/`doc` still parse as aliases of `lightbulb`/`document`.
  (Style mode → `i` opens the symbol grid; `Tab` cycles fill → lead → badge;
  `1`–`9` types a number badge.)
- `>parent` — nest this element inside the box with the given ID.

> **When to reach for symbols and emphasis.** They shine when you're
> *explaining a concept* — mind maps, idea boards, walkthroughs — where a
> `*lightbulb` node or a bold heading aids recognition. On *structural*
> diagrams (state machines, architecture, data flow) keep it clean: boxes,
> labels, arrows, and one colour per category read as a system; symbols and
> bold are mostly noise there. Default to restraint.

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

## Quoted-text escapes

Single-line quoted slots (box / arrow / bookmark / flow labels,
descriptions, note text, the footer) support two escapes: `\n` for a
newline and `\"` for a literal quote — `@ box a "Say \"hi\"" 0,0 200x100`.
Triple-quoted blocks take quotes and newlines literally.

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
@ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] [~iso] ["<description>"]
@ bookmark <id> "<label>" ~view=<x>,<y>,<w>,<h> ["<description>"]
@ flow <id> "<label>" <step> ... [~auto=<start_id>] [~detail=<v>] [~focus=<v>] ["<description>"]
@ footer "<markdown>"
@ title-bg <empty|thumbnail-art>
```

A flow `<step>` is a bookmark ref with optional `:`-separated segments, in
any order: a bare number is the auto-play dwell in seconds, and
`detail=<v>` / `focus=<v>` override the flow's presentation settings for
just that stop — `bm_all:6:detail=summary` or `bm_api:focus=complete`.

- `@<ids>` is the **semantic anchor** — the item ids the view frames. The
  pan/zoom is computed by fitting them, so the bookmark survives layout edits.
  `~pad=<n>` overrides the framing padding.
- `~iso` marks the anchor as a **narrowed selection**: thumbnails and exported
  slides render only the anchored items (and the arrows between them), not
  everything inside the framed region — see
  [scoping a step](bookmarks-flows.md#scoping-a-step-to-a-selection).
- `~view=<x>,<y>,<w>,<h>` stores an **exact scene rect** instead, used for a
  hand-tuned framing or a viewpoint that contains no nodes. A bookmark uses
  one or the other.
- A `@ flow` lists bookmark ids in order; `:<dwell>` sets that stop's
  auto-play time in seconds (omit for the flow default). `~auto=<start_id>`
  marks an [auto-generated flow](bookmarks-flows.md#auto-generated-flows),
  regenerable from that start node.
- `~detail=<v>` sets how the flow's stops render under
  [level-of-detail](navigating.md): `full` (everything as authored),
  `summary` (containers collapse to tiles), or `auto` (follow the app's
  global LoD toggle — the default when unset). A step's own `detail=` segment
  overrides the flow.
- `~focus=<v>` controls distraction fading: `complete` shows only elements
  *completely* inside the framed viewport at full opacity and blends out
  partially visible ones (a connector stays opaque only when both its ends
  do); `none` (default) shows the frame as-is. A step's `focus=` segment
  overrides the flow. See
  [per-stop detail & focus](bookmarks-flows.md#per-stop-detail--focus).
- A bookmark **description** is the playback / slide caption: it renders in
  full (wrapped), so keep it within **280 characters** — the GUI editor
  enforces the budget and `grafli export --check` flags older files past it.
- `@ footer` is the board-global markdown branding line on exported content
  slides; `@ title-bg thumbnail-art` selects the title slide's collage
  backdrop. Both are one-per-file.

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
