---
name: grafli
description: >
  Author and edit `.grafli` files — plain-text, line-oriented diagrams
  rendered by the grafli desktop app. Trigger only on EXPLICIT
  visualization requests: "draw / diagram / sketch / visualize / map
  out / graph this", "show me as a diagram", "make a grafli", or when
  working on existing `.grafli` files. Do NOT trigger on generic "review
  this code", "explain this function", "summarize this module" requests
  unless the user also asks for a visual or diagram. When unsure, ask
  the user a one-line clarifier before pulling this skill in.
  ALSO use when asked to EXPLAIN, walk through, narrate, tour, or
  present an existing diagram/graph — author `@ bookmark` / `@ flow`
  directives that turn it into a guided sequence of viewpoints.
---

# Grafli (`.grafli`) authoring

Read, create, and modify `.grafli` files using the built-in `Read` /
`Write` / `Edit` tools. If the user has the desktop app open on the
file, it live-reloads — no need to ask them to refresh.

## Plan before you write

Skills produce noticeably better grafli when the model **plans first**
instead of writing code. Walk through these steps before you produce
any `@ box` / `@ arrow` / `@ note` lines:

1. **Question.** What single question does the diagram answer?
   ("How does an OAuth callback flow?" / "Which services own which
   data?") If you can't state the question in one sentence, ask the
   user.
2. **Cast.** List every actor / component / state as a flat bullet
   list. No coordinates yet.
3. **Flow direction.** Pick **one** for the whole diagram:
   * Left-to-right — pipelines, request flows, timelines.
   * Top-to-bottom — hierarchies, layer architectures, call stacks.
   * Center-out — hub-and-spoke (gateway, event bus, orchestrator).
4. **Containers.** Group related items into `!flat` containers
   (services, layers, bounded contexts) before placing children.
5. **Place children inside containers**, sized and aligned to the
   grid (multiples of 50). Use the container margin model below.
6. **Arrows last.** Every arrow gets a label unless its meaning is
   obvious from context. Use semantic edge prefixes (`call:`, `data:`,
   `event:`, etc.) where they fit.
7. **Notes for the human.** Add `T:` tasks and `Q:` questions as
   short headlines next to the relevant node. For pseudocode,
   assertion lists, behavioral specs, sequence sketches, or any
   other multi-line detail, use a `code:` note; for prose with light
   structure (rationale, checklists, review notes), use an `md:`
   Markdown note — those are the right home for content too long for
   a box label. **Never inline that detail into a box label itself.**
   Boxes are identifiers; notes are bodies. If you find yourself
   writing more than a short phrase inside a `@ box` label, stop and
   move it to a note.
8. **Re-read.** Pretend you're the user opening the file: does the
   eye land on the right entry point? Are arrows crossing? If yes,
   reposition before saving — repositioning beats decoration.
9. **Render and verify.** Use `grafli render <file>.grafli /tmp/check.png`
   to produce a headless PNG and *look at it*. This is the single
   highest-leverage feedback step — most layout problems (overlaps,
   arrows crossing boxes, undersized containers, truncated labels) are
   obvious in the rendered image but invisible in the source. Render
   after every non-trivial edit, fix what you see, render again. Don't
   declare a diagram done without at least one render-and-look pass.
10. **Diagnose.** Run `grafli diagnose <file>.grafli` (add `--json`
    for machine-readable output) for static checks the eye misses:
    children outside parents, sibling overlaps, cramped containers,
    likely-truncated labels, arrow labels crowding endpoints or hiding
    arrowheads, missing `@path` / image refs. Each finding carries a
    `fixable` flag and a `severity`:

    * `severity: error` (e.g. `invalid-parent-ref`) — always fix.
    * `fixable: true` — usually a real geometry mistake. Try to fix.
    * `fixable: false` — heuristic or possibly-intentional (a
      placeholder reference, an artistic crowding choice).
      Acknowledge once and move on.

    **One pass, then stop.** Run diagnose, address the obvious
    findings, run it once more to confirm. If the same warnings
    persist, accept them as known limitations and ship — do not
    keep reshuffling the diagram trying to drive the count to zero.
    Diagnostics are guidance, not a gate.

## File format quick reference

```
# Comments and titles
@ box <id> "<label>" <x>,<y> <w>x<h> [%color] [^anchor] [~size] [!style] [&attach] [>parent] [# annotation]
@ arrow <from_id> (->|<-|<->|--) <to_id> ["label"] [@dx,dy] [!style] [~size] [# annotation]
@ note <id> <x>,<y> "<text>" [~size] [&attach] [>parent] [# annotation]
@ note <id> <x>,<y> [~size] &doc [>parent]        # doc-bodied: body = <stem>-res/<id>.md
@ image <id> "<relative_path>" <x>,<y> <w>x<h> [>parent] [# annotation]
@ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] ["<description>"]
@ flow <id> "<label>" <bookmark_ref>[:<dwell>] ... ["<description>"]
```

`&attach` is a typed attachment: `&link:<url>` (the only kind that may
point outside the board), `&doc:<name>` (a markdown document at
`<stem>-res/<name>.md`), or `&graph:<name>` (a sub-board at
`<stem>-res/<name>.grafli`). See "Attachments" below.

The last two are **flows** — see "Explanatory flows" below. A file that
uses them carries a `#!grafli v2` header (emitted automatically).

* One element per line — minimal git diffs.
* `#` lines are comments / metadata.
* Coordinates: `x,y` position (floats OK), `wxh` size.
* IDs are short lowercase identifiers (`auth`, `db`, `api-gw`).
* Modifiers in `[]` are optional and order-sensitive as shown.
* Multi-line text: use `\n` in labels and note text.

## Common mistakes — check before you save

These are the failure modes that recur most often. A 30-second checklist
catches them before the user opens the file.

* **Quote characters in note text.** The format does **not** escape
  `"` inside a note. Either drop the quotes (`order created`) or use a
  triple-quoted block (`"""..."""`).
* **Modifiers on triple-quoted notes go AFTER the closing `"""`.**
  Putting them between the coordinates and the opening `"""` silently
  drops the entire note from the render. Correct form:
  ```
  @ note id 100,200 """
  code:
  ...
  """ ~small
  ```
* **Code-mode notes auto-widen to fit their longest line.** When notes
  are placed side-by-side (multi-column phases), a long line in one note
  pushes its background into the neighbour's column. If `box_w=220` and
  `gap=40`, the column budget is **260 px**; at default note size that
  is roughly **24 chars per line**, at `~small` it is roughly **32**.
  The rightmost column also has to fit inside the container's right
  margin. **Default to `~small` whenever a code-mode note sits in a
  multi-column phase** — it shrinks both width and height, leaves
  margin to spare, and stays readable.
* **Disconnected boxes.** Every box should either have an arrow,
  sit inside a container, or be a deliberate standalone label. Drifting
  orphans look like errors.
* **Children outside the parent.** A box with `>parent` must visually
  fit inside the parent's rect after the margin model. Re-check the
  parent's `<w>x<h>`.
* **Cramped containers.** Children must not overlap the parent's
  headline. Top margin is **60 px** for `~large`, **40 px** for
  default.
* **Truncated labels.** A box should comfortably fit its label.
  Minimum `200x80` for default 13 pt text; bigger for `~large`. If
  the label is long, shorten it or grow the box.
* **`then` keyword in code-mode notes.** `then` exists for
  back-compat but is deprecated for new notes — use indentation
  (`if cond:` then indented body) instead.
* **`set` / `note` / `fn` keywords.** All removed from code-mode
  v3. The first body line is the function signature; plain
  assignments need no keyword (`out = []`); comments use `# …`.
* **Same text size for a heading and its children.** A container
  heading must be visually subordinate to *or* distinct from child
  labels.
* **Rainbow diagrams.** Stop at 3–4 semantic colors. Each color
  should encode information.

## Box syntax

```
@ box <id> "<label>" <x>,<y> <w>x<h> [%color] [^anchor] [~size] [!flat] [*icon] [&attach] [>parent]
```

| Modifier | Values | Effect |
|----------|--------|--------|
| `%color` | color token or `#RRGGBB` | fill color |
| `^anchor` | `^topleft`, `^topcenter` | label alignment (default: center) |
| `~size` | `~small`, `~large`, `~xlarge`, `~xxlarge`, `~xxxlarge` | text size (default: medium) |
| `!flat` | `!flat` | no border, semi-transparent fill |
| `!bold` / `!italic` | `!bold`, `!italic` | text emphasis layered on `~size` (combine for headings/asides) |
| `*icon` | `*bulb` (fill), `*lead:gear` (lead) | visual-vocabulary glyph — fill: big icon + caption; lead: small icon left of the label |
| `&attach` | `&link:<url>`, `&doc:<name>`, `&graph:<name>` | typed attachment (see "Attachments") |
| `>parent` | `>parent_id` | nest inside parent box |

Visual-vocabulary icons (`*name`, on boxes and notes): `person`, `gear`,
`cloud`, `database`, `warning`, `bulb`, `check`, `cross`, `money`, `clock`,
`doc`, `lock`, `flag`, `star`, `link`, `question`. Placement: bare `*name`
*fills* the element (big glyph, label/text becomes a caption) — a framed
concept node on a box (`*bulb` = idea), a borderless marker on a note.
`*lead:name` puts a *small* glyph left of the label, which stays primary — for
labeled items (`*lead:database` → a "Postgres" node) and flagging existing
nodes (`*lead:warning`). Use fill for visual graphs, lead for accents.

Container behavior: when a box has children, its anchor auto-switches
to `^topleft` and text defaults to `~small` (10 pt). Set `~large`
explicitly on top-level containers for a more prominent heading.
Child positions use absolute coordinates — see the container layout
model in the design principles below.

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
@ arrow <from_id> (->|<-|<->|--) <to_id> ["label"] [@dx,dy] [!style] [~size] [# annotation]
```

| Feature | Syntax | Effect |
|---------|--------|--------|
| Direction | `->` | forward (arrowhead at target) |
| Direction | `<-` | backward (arrowhead at source) |
| Direction | `<->` | bidirectional |
| Direction | `--` | line only (no arrowheads) |
| Label offset | `@dx,dy` | shift label position by `dx,dy` px from center |
| Style | (default) | solid line |
| Style | `!dashed` | dashed line |
| Style | `!dotted` | dotted line |
| Style | `!thick` | double-width solid line |
| Text size | `~size` | as for boxes |
| Annotation | `# text` | authoring metadata (indicator dot, not visible text) |

Arrows auto-route from box edge to box edge. Opposite arrows
(`A->B` and `B->A`) merge into a single bidirectional line.

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
| `~size` | `~small`, `~large`, `~xlarge`, `~xxlarge`, `~xxxlarge` | text size |
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

* The `.grafli` format does not escape `"` inside note text. Avoid
  embedding string literals that need quote characters; drop the
  quotes or rewrite the line.
* Indent nested blocks with **two spaces**.

### Markdown-mode notes (`md:`)

A markdown note renders its body as a small subset of Markdown. Use it
for **prose annotations with light structure** — rationale, checklists,
review notes — where code-mode would be the wrong shape and a plain note
too flat. It's a sibling of code-mode: a formatted block on the same
beige plate, with near-black body text.

**Canonical form: doc-bodied** — `@ note <id> <x>,<y> &doc` with the
body in `<stem>-res/<id>.md` (pristine markdown, no sentinel). Prefer it
when authoring: write the `.md` file, then the one-line note. The legacy
inline form — first non-empty line `md:` (or `markdown:`) — still parses
everywhere and is auto-converted to doc-bodied on the app's first save.

Supported (GitHub-flavoured) subset:

| Markdown | Renders as |
|----------|------------|
| `# ` / `## ` / `### ` | Headings (3 levels, bold) |
| `- ` / `* ` / `1. ` | Bullet / ordered list |
| `- [ ]` / `- [x]` | Task checkboxes |
| `> ` | Blockquote |
| `---` | Horizontal rule |
| ` ``` ` / `` `code` `` | Code block / inline code (muted plate) |
| `**bold**`, `*italic*`, `~~strike~~` | Inline emphasis |
| `[text](url)` | Clickable link (reuses `&url` handling) |

Honours `~size` / `~width` and drag-to-resize like other notes. Keep
notes small — tables, images, and raw HTML are parsed but rarely fit a
canvas annotation; if a note wants that much, link a `.md` resource
instead. The `.grafli` format does not escape `"`, so avoid quote
characters in inline text (the same constraint as code-mode).

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

Notes with 2+ distinct speaker prefixes (2-3 uppercase letters
followed by `: `) render as threaded conversations. Each speaker
gets a colored badge and block-indented body text.

```
@ note n1 500,300 "GC: How does a user specify the label content?\nCC: Most discoverable: action from inspection panel.\nUser inspects feature, sees attribute.\n\nCan be session-only or persisted.\nGC: Makes sense, what about batch mode?"
```

Rules:

* A line starting with `XX: ` (2-3 uppercase letters + colon +
  space) starts a new speaker block.
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

Plus arbitrary `#RRGGBB` hex. Stick to **3–4 colors per diagram**;
each should encode something semantic (layer, ownership, status).

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

---

# Diagram design principles

The grafli is a box-and-arrow tool — no auto-layout, no curved lines,
no freeform shapes. These constraints make intentional design
essential.

## 1. Visual hierarchy

Every diagram needs a clear reading order:

* **Size for importance**: critical components get larger boxes
  (e.g., `250x120`), minor ones stay at `150x60` or smaller.
* **Color for category**: assign one color token per semantic group
  and stay consistent — don't use more than 3–4 colors per diagram.
* **`!flat` for containers**: use flat style on grouping boxes so
  they recede visually and children stand out.
* **Visual weight**: darker / saturated colors (`%primary`,
  `%subtle`) feel heavier and anchor the eye — place them at focal
  points. Lighter tokens (`%muted`, `%base`) recede.

### Typography scale

| Role | How to set | Rendered size |
|------|------------|---------------|
| Diagram title | `~xxlarge` note | 40 pt |
| Top-level container label | `~large ^topleft !flat` box | 18 pt |
| Component box label | (default, no `~size`) | 13 pt |
| Nested container label | `^topleft !flat` box (auto-default `~small`) | 10 pt |
| Context annotation | note (default) | 13 pt |
| Small annotation | `~small` note | 10 pt |

Key rules:

* Top-level containers should use `~large` explicitly — the
  auto-default `~small` is too subtle for section headings.
* Component boxes inside containers should stay at default (13 pt) —
  they're the primary content the reader focuses on.
* Never use the same text size for a container heading and its
  children — the heading must be visually subordinate to or
  distinct from child labels.
* Emphasis (`!bold`, `!italic`) layers on top of size. Use `!bold`
  for the one or two things that must stand out (a title, the key
  node) and `!italic` for secondary asides — sparingly. If everything
  is bold, nothing is.

### Visual vocabulary & emphasis — use only when it earns its place

Glyph icons (`*name`) and text emphasis (`!bold` / `!italic`) are powerful
for *explaining a concept* but are noise on a *technical diagram*. Match the
tooling to the intent — this is a judgment call, and the default is restraint:

* **Structural / technical diagrams** — state machines, architecture, data
  flow, ER / class, sequence. Keep them clean: boxes, labels, arrows, and
  one colour per category. Skip glyphs and emphasis almost entirely. Uniform
  weight reads as "a system," and a gear icon on a "Scheduler" node adds
  nothing the label doesn't already say. At most a *sparing* flag — a bold
  title box, `*lead:warning` on a genuinely risky node.
* **Concept explanations / visual notes / teaching** — mind maps, idea
  boards, walkthroughs, retrospectives, "how it works" sketches. Lean in: a
  `*bulb` idea node, `*lead:database` labelled items, a bold heading over a
  small italic aside. Here recognition and hierarchy are the whole point, and
  sketchnote-style glyphs + emphasis make the board graspable at a glance.

Each channel carries one meaning — colour = category, size = importance,
weight = emphasis, glyph = concept or flag. You rarely need more than one on
an element. If a glyph or a bold doesn't make the diagram *easier to
understand*, leave it off.

## 2. Layout strategy

You are the layout engine. Think in grids and flows.

**Grid alignment**:

* Align positions to multiples of 50.
* Default box: `200x100`, horizontal gap ~100 px, vertical gap
  ~150 px.
* Keep consistent spacing — irregular gaps look unintentional.

**Flow direction** — pick **one** per diagram:

* **Left-to-right** — pipelines, request flows, timelines.
* **Top-to-bottom** — hierarchies, layer architectures, call stacks.
* **Center-out** — hub-and-spoke (gateway, event bus, orchestrator).

**Lanes and rows**: group related boxes into horizontal or vertical
bands. Use a `!flat` container box behind each group to make lanes
explicit.

**Canvas margins**: leave ~50 px around the outermost elements so
the diagram doesn't feel cramped against the title or the edge.

## 3. Containers (`>parent`)

Nesting with `>parent` is the primary way to show logical grouping
(layers, services, bounded contexts).

```
@ box backend "Backend" 20,250 520x200 %tertiary ^topleft ~large !flat
@ box api "API" 40,310 220x100 %accent >backend
@ box auth "Auth" 280,310 220x100 %accent >backend
```

* Make the container `!flat` so it's a subtle background, not a
  competing box.
* Use `^topleft` so its label is an unobtrusive header.
* Use `~large` on top-level containers for a readable section
  heading.
* Give children a contrasting color from the container.

### Container margin model

Child coordinates are absolute, so prevent children from overlapping
the parent headline:

* **Top: 60 px** from parent top edge for `~large` headings, **40 px**
  for `~small` / auto headings.
* **Sides: 20 px** from parent left and right edges.
* **Bottom: 20 px** minimum from parent bottom edge.

**Sizing formulas:**

* **Single-row container** —
  * width = `left_margin + (n × child_w) + ((n-1) × gap) + right_margin`
  * height = `top_margin + child_h + bottom_margin`
* **Multi-row container** —
  * height = `top_margin + (rows × child_h) + ((rows-1) × row_gap) + bottom_margin`

Example for 3 children, 2 rows, 220×100 boxes, 40 px gaps,
`~large` heading:

* width = `20 + 3×220 + 2×40 + 20 = 780`
* height = `60 + 2×100 + 1×40 + 20 = 320`

### Alignment within containers

* All children in a **row** share the same Y coordinate.
* All children in a **column** share the same X coordinate.
* Use consistent child box sizes within one container — mixed sizes
  look accidental unless intentional (e.g., a wider "main" component
  flanked by smaller helpers).

## 4. Arrow discipline

* **Label every arrow** that isn't self-explanatory from context —
  "queries", "REST", "events" tell the reader what flows.
* **Use styles semantically** and consistently:
  * Solid (default) — primary / synchronous flows.
  * `!dashed` — optional, async, or secondary paths.
  * `!dotted` — event-driven, pub / sub, background.
  * `!thick` — critical path, main user-facing flow.
* **Minimize crossing**: rearrange box positions to reduce arrow
  crossings — this matters more than perfect grid alignment.
* **Long arrows mean you're crossing something.** If an arrow is
  much longer than your average box-to-box gap, it's probably
  jumping over another box. Reposition the source or target;
  don't just let the arrow route through.
* **Fan-out (3+ outgoing arrows from one node).** This is one of
  the most common AI mistakes. Three options, in order:
  * If the targets share a logical relationship, this is a
    **hub-and-spoke** pattern — use the dedicated layout (centre +
    satellites).
  * If the calls run in parallel, place the targets
    **perpendicular to the primary flow** — stack them vertically
    if the main flow is L→R, horizontally if it's T→B. Don't
    line them up along the main flow direction (one of the arrows
    will inevitably cross another box).
  * If the calls are sequential, **chain the targets** along the
    main flow with the box passing through, not branching.
* **Flow in one direction**: most arrows should follow the diagram's
  primary flow (LR or TB). Reverse arrows (callbacks, responses)
  are OK but should be the minority.
* **Use `<->` sparingly**: bidirectional is for synchronous
  request-response pairs or mutual dependencies; overuse makes flow
  direction ambiguous.
* **Crossing containers**: avoid; reposition first. If unavoidable,
  prefer crossing the lighter `!flat` containers rather than primary
  boxes.

## 5. Notes and annotations

Notes are badge-style labels — blue text by default, with colored
badge chips for semantic prefixes.

* **`T:` / `TODO:`** — task (red badge). An agent can execute and
  remove it.
* **`Q:` / `QUESTION:`** — question (purple badge). An agent can
  answer inline.
* **Discussion** — `XX: ... \n YY: ...` (auto-detected, 2+ speakers).
* **Plain text** — informational annotation (blue).
* **`code:`** — pseudocode block (see Code-mode notes above).

### Note positioning

Place notes deliberately:

* **Diagram title** — `~xxlarge`, top-centre, ~40 px above the first
  row.
* **Section labels** — near groups they describe.
* **Element annotations** — above, below, or to the side of the box
  they annotate, with ~30–40 px gap. Be consistent within one
  diagram (don't put some notes above and some below the same row).
* **Code-mode notes** are usually placed directly below their target
  box, aligned to the same x-coordinate. Reserve a vertical band
  beneath the row for them.
* **Note-to-element arrows** — when a note isn't directly adjacent
  to its target, use `@ arrow note_id -> box_id !dotted` to make
  the linkage explicit.
* Keep notes short — if you need a paragraph, it belongs in
  documentation, not on the diagram.

### Attachments (`&`)

Every element can carry **one** typed attachment:

```
@ box api "API" 100,100 200x100 &link:https://docs.example.com
@ box orders "Orders" 100,250 200x100 &doc:orders-spec
@ box auth "Auth" 100,400 200x100 &graph:auth-flow
@ note n1 350,100 "See spec" &link:https://spec.example.com
@ note plan 350,250 &doc
```

- `&link:<url>` — opens externally; the **only** kind that may point
  outside the board.
- `&doc:<name>` — a markdown document at `<stem>-res/<name>.md` (bare
  name, no path/extension). On a **note** it is rendered as the body
  (that's what a markdown note is — bare `&doc` names it after the note
  id); on a box/image/arrow it opens in the editor.
- `&graph:<name>` — a sub-board at `<stem>-res/<name>.grafli`; its own
  resources nest at `<stem>-res/<name>-res/`.

Content attachments live only in the `<stem>-res/` vault, so a board
plus its vault is the complete, copyable unit. Legacy untyped `&url`
values still parse and are classified on load. An attachment is distinct
from `# annotation`: it's visible/clickable; an annotation is invisible
authoring metadata.

## 6. Common patterns

### Architecture (layered)

Top-to-bottom flow. One `!flat` container per layer. Arrows flow
downward between layers. Use `~large` on each layer container.

```
@ box frontend "Frontend" 20,20 500x200 %secondary ^topleft ~large !flat
@ box web "Web App" 40,80 200x100 %highlight >frontend
@ box mobile "Mobile" 280,80 200x100 %highlight >frontend

@ box backend "Backend" 20,270 500x200 %tertiary ^topleft ~large !flat
@ box api "API" 40,330 200x100 %accent >backend
@ box auth "Auth" 280,330 200x100 %accent >backend

@ box data "Data" 20,520 500x200 %subtle ^topleft ~large !flat
@ box db "PostgreSQL" 40,580 200x100 %primary >data
@ box cache "Redis" 280,580 200x100 %primary >data

@ arrow web -> api "REST"
@ arrow mobile -> api "GraphQL"
@ arrow api -> auth "validate"
@ arrow api -> db "queries"
@ arrow auth -> cache "sessions"
```

### Flow / pipeline (left-to-right)

Horizontal chain. Boxes in a row, arrows left-to-right. Side loops
branch down.

```
@ box build "Build" 50,100 150x80 %secondary
@ box test "Test" 300,100 150x80 %tertiary
@ box stage "Stage" 550,100 150x80 %highlight
@ box prod "Production" 800,100 150x80 %primary

@ arrow build -> test
@ arrow test -> stage "pass"
@ arrow stage -> prod "approve"

@ box rollback "Rollback" 550,280 150x80 %accent
@ arrow prod -> rollback "alert" !dashed
@ arrow rollback -> stage "redeploy"
```

### Hub-and-spoke

Central element, satellites around it.

```
@ box hub "API Gateway" 250,200 200x100 %primary
@ box web "Web" 50,50 150x70 %secondary
@ box mobile "Mobile" 450,50 150x70 %secondary
@ box db "Database" 50,380 150x70 %subtle
@ box cache "Cache" 450,380 150x70 %highlight

@ arrow web -> hub "HTTPS" !thick
@ arrow mobile -> hub "HTTPS" !thick
@ arrow hub -> db "queries"
@ arrow hub -> cache "read" !dashed
```

### Legend box

When using multiple arrow styles or color meanings, add a legend.

```
@ box legend "Legend" 50,500 280x200 %muted ^topleft ~small !flat
@ note n10 70,545 "→  solid = synchronous" ~small
@ note n11 70,575 "⇢  dashed = async" ~small
@ note n12 70,605 "⋯  dotted = event-based" ~small
@ note n13 70,635 "━  thick = critical path" ~small
```

### Sub-graflis

If a single box's internal logic would need 5+ children to depict,
link a sub-grafli with `&graph:<name>` instead of stuffing it into
the parent diagram. The sub-board lives at `<stem>-res/<name>.grafli`,
renders as its own canvas, and the viewer follows the link.

```
@ box orders "Order Processing" 100,100 220x100 &graph:orders-flow
```

## 7. Things to avoid

* **Rainbow diagrams**: more than 4 colors creates noise, not
  information.
* **Unlabeled arrows**: an arrow without a label is a relationship
  without meaning.
* **Massive flat layouts**: if you have 15+ boxes at the same level,
  group them into containers.
* **Tiny containers**: don't nest a single box — nesting implies
  grouping of multiple elements.
* **Decoration for its own sake**: every visual choice (color, size,
  style) should encode information.
* **Glyphs / bold on technical diagrams**: don't sprinkle `*icons` or
  emphasis on a state machine or architecture diagram — they're for
  explaining concepts, not labelling a system (see "Visual vocabulary
  & emphasis — use only when it earns its place").
* **Cramped containers**: children must never visually overlap the
  parent's headline — follow the container margin model.
* **Uniform text sizes**: if every element uses the same font size,
  nothing is emphasized — use the typography scale.
* **Orphaned elements**: boxes floating far from their logical group
  look accidental — keep related items close and aligned.
* **Undersized boxes**: a box should comfortably fit its label.
* **Text bodies inside box labels**: bullet lists, pseudocode,
  assertion checklists, multi-paragraph descriptions belong in a
  `code:` or plain note next to the box, not crammed into the box
  label. If a box label needs more than a short phrase to identify
  the node, the extra content is a note opportunity.

---

# Explanatory flows (guided tours)

When the user asks you to **explain, walk through, narrate, or present** a
graph, don't dump the whole picture — author a **flow**: an ordered sequence
of saved viewpoints with narration. It plays in-app (manual step or auto-play,
`p` cycles paused/playing/loop), presents fullscreen (`F5`), and exports to
PDF slides. It lives in the same `.grafli` file as plain text, so you write it
the same way you write boxes.

## The two directives

```
@ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] ["<description>"]
@ flow     <id> "<label>" <bookmark_ref>[:<dwell>] ... ["<description>"]
```

* A **bookmark** is one viewpoint. `@<ids>` is a **semantic anchor** — list
  the box / note ids to frame; the app fits them at display time, so the
  bookmark stays correct when the layout changes. **Always anchor on ids —
  never raw coordinates.** You know the ids; you don't know good pan/zoom
  numbers. (`~view=x,y,w,h` exists for a node-less viewpoint, but you'll
  rarely want it — prefer anchors.)
* A **flow** lists bookmark ids in order. `:<dwell>` is that stop's auto-play
  time in seconds (omit for the default); it only matters for auto-play / booth
  playback.

## Compose the narrative deliberately

This is the whole point — the *order and framing* are the explanation:

1. **Open wide.** First stop frames the entire graph (or its top-level
   containers) so the viewer gets the map.
2. **Go to the entry point.** Where the story starts — the request ingress,
   the user, the trigger.
3. **Follow the path.** One stop per meaningful hop, in causal / temporal
   order. Frame just the 1–3 items that matter at each step (anchor on those
   ids), not the whole graph — that zoom *is* the focus.
4. **End on the payoff.** The data store, the result, the conclusion.

## Narration — and when to stay silent

* Each stop's **description is the narration**: it's the on-canvas caption
  during playback and the slide caption in the PDF. Write *why this stop
  matters*, not what's already visibly labeled.
* **Let the graph speak when it already does.** If the framed boxes, arrows,
  and notes already carry the point, give the stop a **blank label and no
  description** — it exports as a clean diagram-only slide. Add words only to
  say something the picture doesn't.
* **Reuse** a bookmark across flows when the same viewpoint serves two
  different narratives.

## Verify

* Confirm every `@<id>` in a bookmark and every bookmark id in a flow exists
  in the file (a dangling ref renders an empty / "missing" stop).
* Preview the tour as slides and look at it:
  `grafli export <file>.grafli /tmp/tour.pdf --flow <flow_id>`.

## Worked example

```
#!grafli v2
@ box client "Client" 0,0 160x80
@ box api "API Gateway" 280,0 180x80
@ box auth "Auth Service" 280,160 180x80
@ box db "Postgres" 560,160 180x80
@ arrow client -> api "request"
@ arrow api -> auth "verify token"
@ arrow auth -> db "user lookup"

@ bookmark bm_all "The system" @client,api,auth,db ~pad=80 "Three services behind one gateway."
@ bookmark bm_in "Entry point" @client,api "Every request lands at the gateway first."
@ bookmark bm_authz "" @api,auth
@ bookmark bm_data "Data layer" @auth,db "Auth resolves the user against Postgres."
@ flow tour "How a request flows" bm_all bm_in:6 bm_authz:5 bm_data:8 "From the front door through auth into the data layer."
```

`bm_authz` is intentionally graph-only: the two boxes and the "verify token"
arrow already tell that part of the story, so it needs no caption.

---

# File operations

## Create a new grafli file

Use `Write` to create the file with header comments and elements:

```
# Title
# optional description

@ box ...
@ arrow ...
@ note ...
```

## Modify an existing grafli file

Use `Edit` to change specific lines — the desktop app live-reloads.

To remove an element, replace the line with empty string.

## Per-project convention

Default diagram: `.grafli` (dotfile) in the project root. Named
files (e.g., `architecture.grafli`) can coexist for versioned
diagrams.

## Launch the viewer

```bash
grafli <file.grafli>
```

After creating a new `.grafli`, launch the viewer in background.
Use `pgrep` to avoid duplicates — the app auto-reloads on file
changes.

```bash
pgrep -f "grafli.*<file.grafli>" || grafli <file.grafli> &
```

## Headless render — your self-check tool

`grafli render` produces a PNG / SVG without opening a window. Treat
it as your **primary feedback loop**, not an export afterthought:
text-only inspection of `.grafli` source misses layout problems that
become obvious in the rendered image (overlaps, crossings, undersized
containers, fan-out tangles, label truncation).

```bash
grafli render input.grafli /tmp/check.png        # quick visual check
grafli render input.grafli output.svg            # final deliverable
grafli render input.grafli /tmp/check.png --width 1600   # higher detail
```

Workflow:

1. Write or edit the `.grafli`.
2. Render to a scratch path (`/tmp/check.png` is fine).
3. Open / inspect the image. Look for:
   * Boxes overlapping each other or their parent's headline.
   * Arrows passing through unrelated boxes (long arrows are the tell).
   * Fan-out tangles (3+ outgoing arrows colliding with siblings).
   * Labels that don't fit their boxes.
   * Containers sized too tightly for their children + margins.
4. Fix the source, render again. Repeat until clean.

If you're producing a diagram for a user who can't run grafli,
rendering to SVG and embedding it in their document is often the most
useful end result.
