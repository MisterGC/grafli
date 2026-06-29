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

## Reading an existing board

When the user asks what a board shows, walks through it, or wants it
explained, reconstruct the model before answering — the file is the
source of truth, so read it directly. A few rules make the source
unambiguous:

* **Build the graph.** Each `@ box` / `@ note` is a node; each `@ arrow`
  is a directed edge (`->` / `<-` / `<->` / `--` line-only). Edge labels
  and semantic prefixes (`call:`, `data:`, `event:`, …) say what flows.
* **Find the entry point.** The node with no incoming arrow — or the one
  a label marks as the trigger / request ingress — is usually where the
  story starts; follow arrows from there in causal order.
* **Containers are grouping.** `>parent` nests a node inside a container
  (layer, service, bounded context); read the parent label as the group
  name.
* **Notes carry the detail.** Semantic prefixes are normalised on render
  (`TODO:` → `T:` task, `QUESTION:` → `Q:`); a `code:` note's first line
  is a function signature and the rest is scannable pseudocode; a note
  with 2+ `XX:` speaker prefixes is a threaded discussion; `md:` / `&doc`
  notes are Markdown bodies.
* **Flows are the author's own narration.** If the file has `@ bookmark`
  / `@ flow` directives, that ordered sequence of viewpoints *is* the
  intended explanation — follow it rather than inventing a reading order.
* **Attachments deepen a node.** `&doc:<name>` / `&graph:<name>` point
  into the `<stem>-res/` vault; open them when a node's detail matters.

## Collaborating on a board (human ↔ AI)

A `.grafli` is a shared workspace, not a one-shot render. A human edits
it in the desktop app (drag, click, type); you edit the same file with
`Read` / `Write` / `Edit`; it live-reloads both ways. So treat the board
as an **async work queue** — the canvas itself carries the open requests
and your replies, and the collaboration leaves a visible trail instead
of living only in chat.

**On opening a board (or when asked to "work" it), scan for open items
and act on them:**

* **`T:` / `TODO:` notes are tasks for you.** Do the work on the node
  the task is anchored to — the nearest box, the one joined by a dotted
  `note -> box` arrow, or its `>parent` — then **clear the task**: delete
  the `T:` note, or if it's a `- [ ]` item in an `md:` note, tick it to
  `- [x]`.
* **`Q:` / `QUESTION:` notes are questions for you.** **Answer inline**
  by turning the note into a short thread: keep the question and add your
  reply on a new line under a speaker tag. Two distinct tags (here `Q`
  and `AI`) make it render as a threaded exchange with coloured badges:
  ```
  @ note q1 600,200 "Q: which store backs sessions?\nAI: Redis - see the cache node, 30-day TTL."
  @ arrow q1 -> cache !dotted
  ```
* **`- [ ]` task lists in `md:` notes** — tick items to `- [x]` as you
  finish them (humans click them in the app; you edit the source — it's
  a one-character diff and a single undo step).

**Leaving requests for the human** is the same move in reverse: drop a
`Q:` note anchored to the node you need a decision on, or a `T:` note
naming what you'd do pending approval. Keep each to a short headline.

**Etiquette that keeps collaboration healthy:**

* **Respect human layout.** Humans place boxes deliberately. When you add
  or change an element, fit it into the existing arrangement — reposition
  only what your change requires, never reflow the whole board. (See
  "Adding a node to an existing board" for the placement arithmetic.)
* **Minimal diffs.** One element per line: touch only the lines your
  change needs. Rewriting untouched boxes/notes pollutes the human's git
  diff and review.
* **Make your trail visible on the canvas.** After acting, the board
  itself should show what you did — a ticked box, a cleared task, an
  inline answer — so the human sees it on reload without diffing the file.
* **Anchor, don't float.** A request or answer note belongs next to (or
  dotted-arrowed to) the node it's about, so it reads in context.

### Editing safely while the board is open

The desktop app autosaves and live-reloads, and it 3-way-merges your
external writes with the human's in-app edits — a true clash (you and the
human changing the same element at the same moment) is resolved
deterministically and flagged, never silently lost. You keep that machinery
in its clean-merge path by editing like a good concurrent citizen:

* **Re-read immediately before you write.** Between your last `Read` and
  your write the human (or the app's autosave) may have changed the file.
  Read right before you `Edit`/`Write` so you diff against the current
  state, not a stale snapshot.
* **Prefer a targeted `Edit` over a whole-file `Write`.** A small `Edit`
  touches only the lines it must, so it merges cleanly with a human
  editing a different part; a full rewrite is far likelier to collide.
* **Keep each change small and localized, then let it save.** Many small
  edits merge better than one big rewrite — and each is a cleaner undo
  step for the human.
* **Edit vault `.md` doc bodies directly, in place.** A doc-bodied note's
  body lives in `<stem>-res/<name>.md`; editing that file is the canonical
  path (line-by-line git diffs) and the app merges it with any unsaved
  zen-editor edit. Same rules apply: re-read the `.md` right before
  writing, prefer a localized `Edit`.

Small, current, localized edits avoid conflicts almost entirely — the
merge is the safety net, not the plan.

Speaker tags (for discussions and `Q:` replies): **a label of 1–16
characters starting with an uppercase letter, then `: `** — `AI:`,
`User:`, `GC:`, `Reviewer:`. 2+ distinct tags in one note trigger the
threaded rendering.

## Plan before you write

Skills produce noticeably better grafli when the model **plans first**
instead of writing code. Walk through these steps before you produce
any `@ box` / `@ arrow` / `@ note` lines. (This is the workflow for a
*precise* diagram — architecture, design, behavior. For a fast, memory-
first **sketchnote**, skip the ceremony and see "Sketchnotes — capturing
a talk for memory" instead.)

1. **Question.** What single question does the diagram answer?
   ("How does an OAuth callback flow?" / "Which services own which
   data?") If you can't state the question in one sentence, ask the
   user.
2. **Cast.** List every actor / component / state as a flat bullet
   list. No coordinates yet.
3. **Flow direction.** Pick **one** for the whole diagram —
   left-to-right, top-to-bottom, or center-out (see "Flow direction"
   under Layout strategy for which fits what).
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
   a box label. Boxes are identifiers, notes are bodies (see the Box
   section) — never inline multi-line detail into a box label.
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
@ box <id> "<label>" <x>,<y> <w>x<h> [%color] [^anchor] [~size] [!flat !bold !italic] [*icon] [&attach] [>parent] [# annotation]
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
* **Code-mode notes auto-widen to fit their longest line**, so a long
  line spills into a neighbouring column when notes sit side-by-side.
  Default to `~small` (and cap `~width`) in multi-column phases — see
  "Sizing in multi-column phases" for the budget math.
* **Disconnected boxes.** Every box should either have an arrow,
  sit inside a container, or be a deliberate standalone label. Drifting
  orphans look like errors.
* **Massive flat layouts.** 15+ boxes at the same level is noise —
  group them into `!flat` containers.
* **Tiny containers.** Don't nest a single box; nesting implies a
  grouping of multiple elements.
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

**Sizes, named and numeric.** `~size` takes a named token *or* a raw point
size like `~16` — both are valid in the file, and stepping a size in the app
(`j`/`k` in style mode) persists the numeric form, so a board you read may
carry `~16` / `~24`-style tokens. Use named tokens when authoring (they read
clearly); reach for numeric only to hit an in-between size. Boxes and notes
share one scale, and the bigger multi-x tiers accept short aliases:

| Token | pt | alias |
|-------|----|-------|
| `~small` | 10 | |
| (default) | 13 | |
| `~large` | 18 | |
| `~xlarge` | 24 | |
| `~xxlarge` | 32 | `~2xl` |
| `~xxxlarge` | 44 | `~3xl` |
| `~4xl` | 60 | `~xxxxlarge` |

`~4xl` is the hero tier — a full-page sketchnote title. Pair it with `!flat`
and display lettering (`!outline` / `!shadow`) for a banner header that sits
on the canvas.

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
* Notes render **handwritten** by default (a warmer, sketchnote feel);
  add `!mono` for code-like notes that need a monospace face. Box
  labels are always monospace (structure). Style mode → `t` opens a
  size × bold/italic text grid; `Tab` toggles a note's font, and (notes
  only) `o` toggles **outline** and `s` toggles **shadow** display lettering.
  Style mode → `c` on a note chooses its **background**: beige plate or none
  (`!flat`, text on the canvas).

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

### Adding a node to an existing board

When you add to a board someone else laid out, drop the new node into the
existing structure and leave everything else **byte-identical** — never
reflow the whole diagram. grafli has no auto-layout, so a clean fit is
*your* arithmetic: compute the absolute `x,y` from the neighbours and
emit it directly (there is no "place near X" token — you do the
resolution once, at write time, and the file stays plain coordinates a
human can read and drag).

**Next slot in a container** — the common case ("add another child"):

1. Read the container's existing children (boxes with `>container`). Note
   their shared width `w`, height `h`, and orientation: children sharing
   a Y are a **row**, children sharing an X are a **column**.
2. Recover the gap from two existing siblings —
   `gap = next.x - (prev.x + prev.w)` for a row (Y-equivalent for a
   column).
3. Place the new child one `gap` past the last sibling, on the row's Y
   (or column's X): `x = last.x + last.w + gap`, `y = last.y`. Match its
   `w`×`h` to the siblings.
4. **Check it still fits** inside the container minus margins (20 px
   sides / bottom). If it doesn't, this is the *only* time you touch an
   existing line: grow the **container's** `w` (or `h`) by `w + gap` per
   the sizing formula — don't move the siblings. If the row is truly
   full, start a new row at the same left X, one `row_gap` lower.

**A free-standing node near another** (no container): reuse the spacing
already between nearby nodes — don't invent a new rhythm. Below:
`x = anchor.x`, `y = anchor.y + anchor.h + gap`. Beside: `y = anchor.y`,
`x = anchor.x + anchor.w + gap`.

**Then verify.** Render and run `grafli diagnose` —
`children-outside-parent` or `sibling-overlap` findings mean the
arithmetic was off. Fix the one new node (or the one grown container),
never the whole board. The discipline: one new line, sized and aligned
to its neighbours, with at most one existing line changed — a clean,
reviewable diff that leaves the diagram as comprehensible as the human
left it.

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

Most technical diagrams reduce to one of these shapes, and the format
covers the common types directly: **architecture** (layered containers),
**flow / pipeline** (L→R chain), **hub-and-spoke** (gateway / event bus),
**state machines** and **sequences** (nodes + transition arrows, or a
`code:` note with `state from -> to` lines), **ER / class** (boxes +
labelled relationship arrows), and **mind maps / concept boards** (center
node + radiating ideas — see "Visual notes" below). Pick the shape from
the question, then the flow direction.

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

### Visual notes / concept boards

For explaining a *concept* rather than a *system* — a teaching sketch,
a mind map, a retrospective, a "how X works" board on any topic — flip
the defaults the technical patterns set. Here recognition and hierarchy
**are** the point, so lean into the sketchnote vocabulary the technical
diagrams hold back (see "Visual vocabulary & emphasis"):

* **Center the idea, radiate the rest.** A center-out layout: the
  concept in the middle, contributing ideas around it. A `*bulb` (or
  other fill glyph) turns the center box into a framed concept node.
* **Glyphs earn their place here.** `*lead:` icons label the satellites
  (`*lead:star` sunlight, `*lead:cloud` a gas) — recognition at a glance
  is exactly what a teaching board wants.
* **Emphasis carries hierarchy.** A `!bold` title, a small `!italic`
  aside; notes render handwritten by default, which suits the form. For a
  hand-lettered heading, give the title **display lettering** — `!outline`
  (hollow) or `!shadow` (depth) — and `!flat` so it sits on the canvas with
  no plate, like a sketchnoter's title. (Notes only; set live from style
  mode → `t` for outline/shadow, → `c` for the plate.)
* **One note for the takeaway.** A short `md:` note gives the
  one-sentence gist the picture is building toward.

```
@ note title 300,40 "How photosynthesis works" ~xxlarge !flat !bold

@ box sun "Sunlight" 100,150 180x80 %soft *lead:star
@ box water "Water  H2O" 100,300 180x80 %soft
@ box co2 "CO2 from air" 100,450 180x80 %soft *lead:cloud

@ box leaf "Photosynthesis" 420,270 220x140 %highlight *bulb

@ box sugar "Glucose  food" 780,230 180x80 %forest *lead:check
@ box o2 "Oxygen out" 780,420 180x80 %teal *lead:cloud

@ arrow sun -> leaf "light"
@ arrow water -> leaf "H2O"
@ arrow co2 -> leaf "CO2"
@ arrow leaf -> sugar "stored energy"
@ arrow leaf -> o2 "released"

@ note gist 100,600 """
md:
**Gist:** a leaf turns *light + water + CO2* into sugar it
can store, and breathes out the oxygen we need.
""" ~small
```

The same restraint rule still applies in reverse: every glyph and bold
should make the idea *easier to grasp*. A concept board that's lost its
hierarchy is as noisy as a state machine covered in icons.

### Sketchnotes — capturing a talk for memory

A conference sketchnote is a different job from a technical diagram: the
goal is **recall of a few take-aways**, not faithful structure. Optimise
for memory, and **skip the heavy ceremony** — the plan-first /
render / diagnose loop is for precise diagrams; a live sketchnote wants
speed and personality, so capture first and tidy later (if at all).

* **Reduce ruthlessly.** A talk has 3–5 things worth keeping. Capture
  those as headline boxes; let everything else go. If you're writing
  full sentences, you're transcribing, not sketchnoting.
* **Headline hierarchy.** One `~xxlarge !bold` title (the talk's thesis),
  a handful of `~large` key points, small notes for the supporting
  detail. Size *is* the memory cue — the biggest things are what you'll
  recall. For a hand-lettered banner feel, give a header note **display
  lettering**: `!outline` (hollow letters), `!shadow` (drop-shadow depth),
  or `!bold !shadow` (a 3D header) — layered on `~size`. Add `!flat` to drop
  the beige plate so the title sits **directly on the canvas**, the way a
  sketchnoter letters a heading. Use these on the title and section headers,
  not body text.
* **One glyph per point as a memory hook.** `*lead:` icons make a point
  recognisable at a glance weeks later (`*lead:warning` a pitfall,
  `*lead:bulb` the key insight, `*lead:check` a recommendation). Here
  glyphs *aid recall* — the opposite of the restraint a technical diagram
  needs.
* **Capture the arc, not the outline.** Hook → 2–4 key points → the
  one thing to remember. A loose top-to-bottom or center-out flow beats
  a rigid grid; don't agonise over coordinates.
* **Let a `md:` note hold a punchline** — a memorable quote or the single
  call-to-action, in the speaker's words.

```
@ note title 200,40 "Make it work, then make it fast" ~xxlarge !flat !bold !shadow

@ box hook "Premature optimisation = wasted weeks" 120,180 320x90 %soft ~large *lead:warning
@ box k1 "Measure before you tune" 120,330 320x80 %soft ~large *lead:bulb
@ box k2 "90% of time is in 10% of code" 120,470 320x80 %soft ~large *lead:clock
@ box k3 "A profiler beats a guess" 120,610 320x80 %soft ~large *lead:check

@ note punch 520,330 """
md:
> "Find the hot 10% with a profiler,
> leave the other 90% alone."
""" ~large
```

This isn't a diagram of the talk — it's the four things you want to walk
out remembering, sized so the eye (and memory) keeps them.

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
