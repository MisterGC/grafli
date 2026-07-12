# grafli file format — full reference

Full element syntax for `.grafli` authoring. The always-loaded skill core
(SKILL.md) carries the quick reference; open this file when you write any
element beyond it.

## Box syntax

```
@ box <id> "<label>" <x>,<y> <w>x<h> [%color] [^anchor] [~size] [!flat !bold !italic] [*icon] [&attach] [>parent]
```

**Modifier order is enforced** — write them in exactly this sequence:
`%color` → `^anchor` → `~size` → `!`-flags → `*icon` → `&attach` →
`>parent` → `# annotation`. The `!`-flags (`!flat` / `!bold` / `!italic`)
are one group and may appear in any order *among themselves*, but the
whole group must sit **after `~size` and before `*icon`**. Putting a flag
out of place (e.g. `*lead:gear !bold`) makes the line fail to parse and
the element **silently disappears** from the render — the same failure
class as a misplaced triple-quote modifier.

| Modifier | Values | Effect |
|----------|--------|--------|
| `%color` | color token or `#RRGGBB` | fill color |
| `^anchor` | `^topleft`, `^topcenter` | label alignment (default: center) |
| `~size` | named `~small`…`~xxxlarge`, `~4xl` (hero), short aliases `~2xl`/`~3xl`, or numeric `~16` | text size (default: medium) |
| `!flat` | `!flat` | no border, semi-transparent fill |
| `!bold` / `!italic` | `!bold`, `!italic` | text emphasis, in the `!`-flag group (combine for headings/asides) |
| `!outline` / `!shadow` | `!outline`, `!shadow` | **note** display lettering — hollow letters / drop-shadow depth, for sketchnote headers (layer with `~size` + `!bold`); render on notes, not boxes |
| `!flat` (note) | `!flat` | drop the beige background plate — the note's text sits directly on the canvas (for a hand-lettered title/header) |
| `*symbol` | `*lightbulb` (fill), `*lead:gear` (lead), `*badge:star` (badge), `*3` (number) | sketchnote symbol — fill: big symbol + caption; lead: small symbol left of the label; badge: compact top-right overlay; digits 1–99 render as circled number badges |
| `&attach` | `&link:<url>`, `&doc:<name>`, `&graph:<name>` | typed attachment (see "Attachments") |
| `>parent` | `>parent_id` | nest inside parent box |

## Sketchnote symbols (`*name`, on boxes and notes)

Two vocabularies with different jobs. **Semantic** symbols say *what a thing
is*; **emphasis** symbols say *how much it matters*. Pick by intent, not by
looks:

| Semantic | Intent | Semantic | Intent |
|---|---|---|---|
| `person` | human actor | `calendar` | schedule or deadline |
| `robot` | automated actor (AI/bot) | `magnifier` | investigation or search |
| `gear` | process or logic | `puzzle` | dependency or integration |
| `database` | persistent storage | `lock` | security or protection |
| `document` | information artifact | `plant` | growth or evolution |
| `cloud` | remote service | `globe` | external world |
| `target` | goal or objective | `flag` | marker or milestone |
| `lightbulb` | new insight or idea | `clock` | time or duration |
| `question` | unknown or open | `check` | confirmed or done |
| `warning` | known risk or issue | `cross` | rejected or invalid |
| `money` | cost or budget | `link` | reference or connection |

| Emphasis | Intent | Emphasis | Intent |
|---|---|---|---|
| `star` | important (objective) | `brain` | deep work, concentration |
| `heart` | valued (subjective) | `lightning` | disruption, interruption |
| `flame` | urgent, hot topic | `repeat` | iteration, recurrence |
| `exclamation` | attention, note well | `exercise` | deliberate practice |
| `1`…`99` | order or sequence | `performance` | powerful, fast |

Near-misses that agents confuse — keep these distinct: `warning` is a *known*
risk, `lightning` a *sudden* disruption. `flame` means urgent, `exclamation`
means "don't overlook" even when not urgent. `repeat` is plain recurrence,
`exercise` is practice meant to improve capability (and `gear` is the process
itself, not its repetition). `clock` is duration, `calendar` a scheduled
date. `star` marks objective importance, `heart` subjective value. `target`
is the destination, `flag` a point along the way. `plant` is gradual growth,
`performance` current strength. `brain` is the concentrated work,
`lightbulb` the insight it produces.

Placement: bare `*name` *fills* the element (big symbol, label/text becomes a
caption) — a framed concept node on a box (`*lightbulb` = idea), a borderless
marker on a note. `*lead:name` puts a *small* symbol left of the label, which
stays primary — for labeled items (`*lead:database` → a "Postgres" node).
`*badge:name` overlays a *compact* symbol in the top-right corner and leaves
the label/text layout untouched — the emphasis layer (`*badge:flame` on the
hot topic, `*badge:2` as step two of a sequence). Number badges accept any
placement (`*3` fill, `*lead:3`, `*badge:3`). Legacy `bulb`/`doc` parse as
aliases of `lightbulb`/`document` and normalize on save.

Container behavior: when a box has children, its anchor auto-switches
to `^topleft` and text defaults to `~small` (10 pt). Set `~large`
explicitly on top-level containers for a more prominent heading.
Child positions use absolute coordinates — see the container layout
model in `references/design.md`.

**Boxes are identifiers, not bodies.** A box label should be the
shortest phrase that names the node — typically one line, two at
most. If you're tempted to add bullet points, pseudocode,
behavioral detail, or a multi-paragraph description inside a box
label, that content belongs in a `code:` or plain note next to the
box — not inside it. Notes carry distinct visual affordances (badge
colours for `T:` / `Q:`, handwriting font, syntax-styled `code:`
rendering) that you forfeit by inlining the detail. The shape of
your diagram is the graph; the detail lives in notes adjacent to it.

## Arrow syntax

```
@ arrow <from_id> (->|<-|<->|--) <to_id> ["label"] [@dx,dy] [%color] [!pattern] [!thickness] [~size] [~kind=graph|annotation] [# annotation]
```

| Feature | Syntax | Effect |
|---------|--------|--------|
| Direction | `->` | forward (arrowhead at target) |
| Direction | `<-` | backward (arrowhead at source) |
| Direction | `<->` | bidirectional |
| Direction | `--` | line only (no arrowheads) |
| Label offset | `@dx,dy` | shift label position by `dx,dy` px from center |
| Colour | `%token` / `#hex` | override the kind-derived line colour (same palette as boxes) |
| Pattern | (default) | solid line |
| Pattern | `!dashed` | dashed line |
| Pattern | `!dotted` | dotted line |
| Thickness | (default) | width tracks the linked nodes' size |
| Thickness | `!thin` | half-width line |
| Thickness | `!thick` | double-width line |
| Text size | `~size` | as for boxes |
| Connector kind | `~kind=graph` / `~kind=annotation` | override the endpoint default (see below) |
| Annotation | `# text` | authoring metadata (indicator dot, not visible text) |

Arrows auto-route from box edge to box edge. Opposite arrows
(`A->B` and `B->A`) merge into a single bidirectional line.

**Connector kind.** An arrow touching a note or image defaults to an
*annotation* link (muted, "just extra text"); box↔box arrows are *graph*
edges. `~kind=graph` promotes a note/image connector to a first-class
graph edge — auto-flows and graph navigation then follow it (see
`references/presenting.md`); `~kind=annotation` demotes the other way.

### Semantic edge labels

A one-word prefix on an arrow label marks the relationship kind — it
renders as a colored chip and tints the edge. Use them wherever they
fit; they make what-flows-where machine-scannable and visually distinct:

| Prefix | Meaning |
|--------|---------|
| `call:` | Function / RPC call |
| `data:` | Data flow |
| `event:` | Event emission |
| `state:` | State change |
| `step:` | Step in a sequence |
| `verify:` | Verification / test |
| `owns:` | Ownership |
| `depends:` | Dependency |
| `risk:` | Risk / hazard |
| `note:` | Annotation |

```
@ arrow frontend -> backend "call: POST /orders"
@ arrow backend  -> queue   "event: OrderCreated"
@ arrow worker   -> db      "data: persist order"
```

Unknown `word:` prefixes stay plain label text, so ordinary labels with
colons are unaffected.

## Note syntax

```
@ note <id> <x>,<y> "<text>" [~size] [&attach] [>parent]
@ note <id> <x>,<y> [~size] &doc [>parent]
```

The second form is a **doc-bodied note**: the line carries only geometry
and presentation, and the body is the markdown file `<stem>-res/<id>.md`
(or `&doc:<name>` for an explicit name — several notes naming the same
doc share one body). This is the canonical form for markdown notes: the
file is pristine markdown with no `md:` sentinel, edits to it diff
line-by-line in git, and you can read/rewrite the prose without touching
the board. Create one by writing the `.md` into the vault and adding the
`&doc` line.

Notes render as badge-style labels with a light background. Color is
determined automatically by semantic prefix:

| Prefix | Aliases (case-insensitive) | Pen color | Meaning |
|--------|-----------------------------|-----------|---------|
| `T: ...` | `t:`, `TODO:`, `todo:`     | `#C53030` (red) | Task / todo |
| `Q: ...` | `q:`, `QUESTION:`, `question:` | `#805AD5` (purple) | Question |
| *(none)*  | — | `#2B6CB0` (blue) | Informational |

The rendered badge is normalised to the short form (`T:` / `Q:`)
regardless of how it was typed.

| Modifier | Values | Effect |
|----------|--------|--------|
| `~size` | `~small`…`~xxxlarge`, `~4xl`; aliases `~2xl`/`~3xl` | text size |
| `~width=N` | integer, `N` chars per line | soft-wrap width (default 80) |
| `&attach` | `&link:<url>`, `&doc[:<name>]`, `&graph:<name>` | typed attachment; `&doc` makes the note doc-bodied |
| `>parent` | `>parent_id` | nest inside parent box |

**Auto-wrap.** Plain-text and code-mode notes wrap at `~width` chars
(default **80**). Long sentences flow naturally onto multiple readable
lines — write the prose as a single paragraph and let the renderer lay
it out. Explicit `\n`, blank lines, and leading indentation are
preserved across wraps. For code-mode notes, continuations of a wrapped
logical line use a **two-space hanging indent** so the block structure
stays visible. Override per-note with `~width=60` (narrow column) or
`~width=120` (wide). Authors and AI agents can also drag the right
edge of a note in the desktop app to set the width interactively;
the chosen value is persisted as `~width=N`.

### Code-mode notes (`code:`)

A note whose first non-empty line is `code:` renders as a stylized
pseudocode block in display mode. Edit mode stays plain text. The
pseudocode is **not** real source code — it is a minimal, scannable
language for summarizing implementations in review-oriented diagrams.

Goal: a reviewer can verify in seconds that an implementation covers
the expected steps, branches, and side effects — without opening the
source.

`code:` notes are the right home for any multi-line detail you might
otherwise be tempted to cram into a box label: assertion lists,
phase checklists, configuration snippets, behavioral specs, sequence
sketches. The syntax-styled rendering (bold signature line, indent
guides, coloured keywords) gives that content a distinct visual voice
the diagram needs — flat text inside a box label is a regression in
both readability and review value.

#### Layout

* **First body line is the function signature** — rendered bold with
  a divider rule beneath. Write it without any keyword prefix:
  `tokenize(raw) -> [Token]`. Legacy `fn:` / `fn ` prefixes are
  auto-stripped.
* **Indentation carries block structure.** Two spaces per level.
  Indent guides are drawn automatically.
* Trailing `:` on keywords is **optional** — `if cond` and
  `if: cond` both work. Prefer the no-colon form for new notes.

#### Keywords

Two visual groups. Blue **flow** keywords carry control / effect
plumbing; red **contract** keywords mark things a reviewer should
spot first.

| Keyword | Use | Colour |
|---------|-----|--------|
| `if cond` / `else action` | Branching | blue |
| `for x in xs` / `while cond` | Iteration | blue |
| `try` / `catch err -> action` | Protected block / error handling | blue |
| `return expr` | Exit value | blue |
| `call f(args)` | Important call | blue |
| `await op` | Blocking / async wait | blue |
| `emit event(args)` | Event / message emission | blue |
| `state from -> to` | State transition / lifecycle | blue |
| `pre cond` / `post cond` | Pre- / postcondition | **red** |
| `assert cond` | Invariant / expected fact | **red** |
| `verify evidence` | Test / check / trace | **red** |
| `risk text` | Failure mode / review risk | **red** |
| `err expr` | Error / raise | **red** |
| `@path:line` | Clickable source reference (opens in editor) | blue, underlined |
| `# …` | Comment (italic, muted) | grey |
| `"..."`, `#FFF`, `42`, `true` | Literal values render as plain text | — |

Plain assignments need no keyword: `out = []` is unambiguous.

#### Style guidance — the most important thing

The snippet should reveal *what happens*, not literally mirror the
source. Optimise for visual understanding at a glance.

* **Prefer short predicates and named operations** over long OO
  chains. `blank(line)` reads faster than `line.stripped.isEmpty`.
  `starts_with(line, prefix)` reads faster than
  `line.startswith(prefix)`. Even when the underlying code uses dot
  chains, the note should use the verb that captures the intent.
* **Keep one abstraction level per snippet.** Mixing real method
  names with prose verbs forces the reader to re-parse mid-line.
* **Drop boilerplate.** Wrappers, logging, telemetry, defensive
  copies — omit unless they're the point of the function.
* **Name phases.** For multi-step algorithms, give intermediate
  steps a verb-phrase (`split_at_comment`, `consume_prefix`,
  `join_lines`) instead of inlining the mechanics.

If a note grows past ~10 lines, it's trying to be a graph. Split it.

#### Sizing in multi-column phases

Code-mode notes wrap at `~width` (default 80 chars), but a single long
line will still soft-wrap onto multiple rows and may push past the
column gap into the neighbouring note. To avoid overlap when notes sit
side-by-side, set a narrower per-note budget — `~width=40` for a
typical column-width pseudocode block.

Rules of thumb:

* **Use `~small` by default for code notes in multi-column phases.**
  At default size you have ~24 chars of horizontal budget per column;
  at `~small` you have ~32. Most useful pseudocode lines fit at
  `~small` and stay readable.
* **Set `~width=N` to match the column width.** Even with auto-wrap, a
  too-wide note can occupy more horizontal space than its column allows
  before any line is long enough to wrap. Choosing `~width=40` (or
  whatever matches the column gap) caps the visual footprint.
* **Keep ≤7 body lines per note** when columns sit side-by-side, so
  the note's height also fits inside the container.
* **The rightmost column has the container's right edge as its
  budget.** If you've placed `n` boxes of width `w` with gap `g`
  starting at `x_left`, the rightmost column extends from
  `x_left + (n-1)·(w+g)` to the container's right edge minus margin.
  Verify the longest line fits.

#### Format constraints

* A `"` inside single-line quoted text must be escaped as `\"`
  (`@ note n 0,0 "say \"hi\""`). Inside a triple-quoted block, quotes
  need no escaping — prefer the block form for text with quotes or
  multiple lines.
* Indent nested blocks with **two spaces**.

### Markdown-mode notes (`md:`)

A markdown note renders its body as a small subset of Markdown. Use it
for **prose annotations with light structure** — rationale, checklists,
review notes — where code-mode would be the wrong shape and a plain note
too flat. It's a sibling of code-mode: a formatted block on the same
beige plate, with near-black body text.

Two equivalent forms — pick by length:

* **Inline `md:`** — first non-empty line is `md:` (or `markdown:`),
  body in the note. Best for a few lines kept *with* the board; this is
  what the compact examples below use.
* **Doc-bodied `&doc`** — `@ note <id> <x>,<y> &doc`, body in
  `<stem>-res/<id>.md` (pristine markdown, no sentinel). The on-disk
  canonical form: the app rewrites inline `md:` into it on save, edits
  diff line-by-line in git, and several notes can share one `.md`. Reach
  for it when the note is more than a handful of lines or you want to
  read/rewrite the prose without touching the board.

Supported (GitHub-flavoured) subset:

| Markdown | Renders as |
|----------|------------|
| `# ` / `## ` / `### ` | Headings (3 levels, bold) |
| `- ` / `* ` / `1. ` | Bullet / ordered list |
| `- [ ]` / `- [x]` | Task checkboxes — **click to tick/untick** |
| `> ` | Blockquote |
| `---` | Horizontal rule |
| ` ``` ` / `` `code` `` | Code block / inline code (muted plate) |
| `**bold**`, `*italic*`, `~~strike~~` | Inline emphasis |
| `[text](url)` | Clickable link (reuses `&url` handling) |

Honours `~size` / `~width` and drag-to-resize like other notes. Keep
notes small — tables, images, and raw HTML are parsed but rarely fit a
canvas annotation; if a note wants that much, link a `.md` resource
instead. Quotes in inline text need the `\"` escape; the triple-quoted
block form takes them literally (same constraint as code-mode).

```text
@ note plan 100,320 ~small """
md:
# Release checklist
Ship **0.4.0** with the new note type.

- [x] Parser + rendering
- [ ] Docs and changelog
"""
```

#### Combined graph + code-mode example

This is the pattern to aim for: a small graph showing *who calls
whom*, with a code-mode note under each box describing *what one
function does*.

```
@ note title 600,-40 "OAuth callback — request flow" ~xlarge

@ box provider "OAuth Provider" 460,140 220x80 %muted
@ box cb    "Callback Handler" 80,300 220x80 %primary
@ box xchg  "Token Exchange"   460,300 220x80 %tertiary
@ box sess  "Session Mint"     840,300 220x80 %tertiary

@ arrow cb   -> xchg     "call: exchange"
@ arrow xchg -> provider "call: POST /token"
@ arrow xchg -> sess     "call: mint"

@ note n_cb 60,420 """
code:
handle_callback(req) -> Response
pre req.method == POST
state = req.query.state
if not csrf_match(state, cookie):
  err 400 csrf_mismatch
risk timing leak — use ct_eq
return exchange(req.query.code)
""" ~small

@ note n_xchg 440,420 """
code:
exchange(code) -> Session
token = provider.post(code)
verify token.iss == issuer
verify token.aud == client_id
return mint_session(token.sub)
""" ~small

@ note n_sess 820,420 """
code:
mint_session(user) -> SessionId
sid = random_token(32)
state new -> active (ttl=30d)
post HttpOnly, Secure, Lax
risk fixation on reuse
return sid
""" ~small

@ box tests "Security Tests" 460,560 220x80 %muted
@ arrow tests -> cb   "verify: csrf"     !dashed
@ arrow tests -> sess "verify: fixation" !dashed
```

What makes this work:

* Each code note is 5–7 lines — short enough to read in one glance.
* Predicate-style names (`csrf_match`, `random_token`,
  `constant_time_eq`) reveal intent; we never write
  `req.cookie.value.compareTo(...)` even if the source does.
* Contract keywords are deployed sparingly — `pre` for entry
  conditions, `verify` for facts the code asserts, `risk` for things
  a reviewer should challenge.
* The dashed `verify:` arrows from the tests box mirror the `verify:`
  lines inside the code notes, so the diagram cross-references its
  own claims.
* One `@path:line` ref per note points to the real source line.

#### When to use code-mode vs multiple nodes with transitions

Prefer a **single code-mode note** when the logic is linear or small
enough that splitting it would create visual noise without adding
insight — a flat sequence of steps, a short guard + return, a
utility with one branch.

Prefer a **graph of nodes with transitions** when:

* The flow branches across components the reader needs to see as
  distinct entities (services, layers, modules).
* Two code paths execute in parallel — model the fork as one node
  with outgoing arrows to two sibling nodes, each carrying a
  code-mode note as its summary.
* The control flow is the primary story (state machines, retries,
  fan-out / fan-in) — arrows express that better than nested
  pseudocode.

Rule of thumb: if a code-block grows past ~10 lines, it's trying to
be a graph. Split it. Conversely, if every node in your graph has
only one arrow out and carries a tiny label, collapse adjacent nodes
into a single code-mode note.

**Never use code-mode as a substitute for a long code listing.**
Readers come to a grafli to grasp structure at a glance, not to
read code. Summarise ruthlessly.

### Discussion notes

Notes with 2+ distinct speaker prefixes render as threaded
conversations. A speaker prefix is a label of **1–16 characters starting
with an uppercase letter, followed by `: `** (`GC:`, `CC:`, `AI:`,
`User:`, `Reviewer:`). Each speaker gets a colored badge and
block-indented body text.

```
@ note n1 500,300 "GC: How does a user specify the label content?\nCC: Most discoverable: action from inspection panel.\nUser inspects feature, sees attribute.\n\nCan be session-only or persisted.\nGC: Makes sense, what about batch mode?"
```

Rules:

* A line starting with a speaker prefix (uppercase-initial label,
  1–16 chars, + `: `) starts a new speaker block.
* All subsequent lines (including empty lines) belong to that
  block until the next speaker prefix.
* Requires 2+ distinct speakers to activate discussion rendering —
  a single speaker renders as a normal note.
* Speaker colors are assigned automatically from a palette in
  order of appearance.

## Image syntax

```
@ image <id> "<relative_path>" <x>,<y> <w>x<h> [>parent]
```

Path is relative to the `.grafli` file. The companion folder
`<stem>-res/` is the canonical place for attached resources.

## Color tokens

```
%base    %primary    %secondary  %tertiary   %subtle
%accent  %highlight   %muted      %soft
%clay    %teal        %rose       %forest     %plum
```

This is a palette to *choose from*, not a set to *use*. The default
that almost always reads well: a neutral field (`%muted` / `%soft` /
`%subtle` for containers and background nodes) plus **one or two
saturated accents** (`%primary`, `%highlight`, or a `#RRGGBB`) reserved
for the focal point and one semantic category. Stick to **3–4 colors
per diagram total**, each encoding something (layer, ownership, status) —
reaching for a fifth token is the start of a rainbow, not a new meaning.

## Nerd Font glyphs

Box and note labels render in JetBrainsMono Nerd Font. Use glyphs
sparingly — they accent, they don't replace text.

```
@ box db "󰆼  Database" 100,100 200x100
@ box cloud "󰅟  Cloud Storage" 300,100 200x100
```

## Parent nesting (`>parent`)

Use `>parent` to nest a box / note / image inside a container box.
Children use **absolute** coordinates (not relative to the parent),
so you must position them inside the parent's rect manually.

```
@ box backend "Backend" 20,250 520x200 %tertiary ^topleft ~large !flat
@ box api "API" 40,310 220x100 %accent >backend
@ box auth "Auth" 280,310 220x100 %accent >backend
```

The `!flat` style is recommended for container boxes — they recede
visually so children stand out.

## Bookmarks, flows, and board-global directives

Full syntax; see `references/presenting.md` for how to compose them into
tours and slide decks. A file using any of these carries a `#!grafli v2`
header — when you add the first one to a v1 file, bump the header line
yourself.

```
@ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] [~iso] ["<description>"]
@ bookmark <id> "<label>" ~view=<x>,<y>,<w>,<h> ["<description>"]
@ flow <id> "<label>" <step> ... [~auto=<start_id>] [~detail=<v>] [~focus=<v>] ["<description>"]
@ footer "<markdown>"
@ title-bg <empty|thumbnail-art>
```

A flow `<step>` is `<bookmark_ref>` plus optional `:`-separated segments in
any order: a bare number is the dwell, `detail=<v>` / `focus=<v>` override
the flow's presentation settings for that stop —
`bm_all:6:detail=summary`, `bm_api:focus=complete`.

* `@<ids>` is the **semantic anchor** — the item ids the view frames; the
  pan/zoom is computed at display time by fitting them, so a bookmark
  survives layout edits. Always anchor on ids, never raw coordinates
  (`~view` exists only for hand-tuned or node-less viewpoints).
* `~pad=<n>` overrides the framing padding.
* `~iso` makes the anchor a **narrowed selection**: thumbnails and the
  exported slide render *only* the anchored items (and the arrows between
  them) — not everything inside the framed region.
* `:<dwell>` is a stop's auto-play time in seconds (omit for the default).
* `~auto=<start_id>` marks an auto-generated flow (regenerable from that
  start node).
* `~detail=<full|summary|auto>` sets how the flow's stops render under
  level-of-detail: `full` = as authored, `summary` = containers collapse
  to headline tiles, `auto` = follow the app's global LoD toggle (also the
  unset default). Per-step `detail=` overrides the flow.
* `~focus=<none|complete>` fades distraction: `complete` keeps only
  elements *completely* inside the framed viewport at full opacity and
  blends out partially visible ones (connectors stay opaque only when both
  ends are fully shown). Per-step `focus=` overrides the flow.
* A bookmark **description** (the playback/slide caption) renders in full,
  wrapped — keep it ≤ **280 chars**; `grafli export --check` flags longer
  ones.
* `@ footer` is a board-global markdown branding line rendered at the
  bottom of every exported content slide; `@ title-bg thumbnail-art`
  gives the export's title slide a faint thumbnail-collage backdrop.

## Quoted-text escaping

Single-line quoted slots (box/arrow/bookmark/flow labels, descriptions,
note text, the footer) support two escapes: `\n` for a newline and `\"`
for a literal quote. Triple-quoted note blocks take quotes and newlines
literally — prefer them for multi-line or quote-heavy text.
