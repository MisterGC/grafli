---
name: grafli
description: >
  Author and edit `.grafli` files — plain-text, line-oriented diagrams
  rendered by the grafli desktop app. Trigger on visualization requests,
  explicit or indirect: "draw / diagram / sketch / visualize / map out /
  graph this", "show me as a diagram", "make a grafli", "put it on a
  board / whiteboard", or when working on existing `.grafli` files.
  ALSO trigger when asked to EXPLAIN, walk through, narrate, tour, or
  PRESENT an existing diagram/graph (author `@ bookmark` / `@ flow`
  guided tours, exportable as slides), and on THINKING-BOARD requests —
  "help me think through X", "weigh the options", "map the unknowns",
  "should we do A or B" — where a human would go to a whiteboard: author
  a board that structures the problem. Do NOT trigger on generic "review
  this code", "explain this function", "summarize this module" requests
  unless the user also asks for a visual, a board, or a diagram. When
  unsure, ask the user a one-line clarifier before pulling this skill in.
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
  "Adding a node to an existing board" in `references/design.md` for the
  placement arithmetic; `grafli inspect <file>` reports the geometry —
  container inner rects, sibling gaps, the next free slot — so you don't
  re-derive it by hand.)
* **Read the human's non-verbal signals.** Spatial arrangement, chosen
  colors, sizes, and `!bold` are the human *thinking on the canvas* —
  semantics to preserve and interpret, not noise to normalize. Two boxes
  dragged close together are related even without an arrow; a node the
  human enlarged matters more now. Read positions before adding anything.
* **Minimal diffs.** One element per line: touch only the lines your
  change needs. Rewriting untouched boxes/notes pollutes the human's git
  diff and review.
* **Make your trail visible on the canvas.** After acting, the board
  itself should show what you did — a ticked box, a cleared task, an
  inline answer — so the human sees it on reload without diffing the file.
* **Anchor, don't float.** A request or answer note belongs next to (or
  dotted-arrowed to) the node it's about, so it reads in context.
* **Propose, don't restructure.** For a *contested* structural change —
  a new dependency, a split, a regrouping the human hasn't asked for —
  add it as a **proposal**: `!dashed` arrows and `%muted` boxes with a
  short `Q:` note ("proposed — accept?"). The human accepts by
  solidifying (or tells you to). Never unilaterally restructure a shared
  board; uncontested additions in your own task's scope don't need this.
* **Use `# annotation` for provenance.** The invisible annotation channel
  is where your rationale lives ("added per T: from the review round") —
  the visible canvas stays clean.
* **After a multi-step session, leave a "what I did" flow.** Author or
  update a small flow whose stops replay your changes in order, each
  caption saying what changed and why. The human reviews your session as
  a guided tour instead of a diff-hunt. (Skip it for one-line edits.)

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

### Source-file hygiene

The human reads and git-diffs the *source* too — keep the file as
comprehensible as the canvas:

* **Organize with section banners.** Group lines by board region under
  `# ── section ──` comment banners, in an order matching the board's
  layout; new elements land in the right section, not appended at the
  bottom.
* **IDs are stable.** Never rename an id during edits — arrows,
  bookmark anchors, and the human's muscle memory bind to it.
* **Deleting a node is a sweep, not a line.** Also remove its arrows,
  re-parent or remove its `>parent` children, and fix bookmark anchors
  that name it — then run `grafli diagnose` (dangling refs and dropped
  lines surface as errors) and `grafli vault <file> --clean` if the node
  carried a `&doc`/`&graph` attachment (removes now-orphaned vault docs;
  never automatic).
* **You own the header.** When you add the first `@ bookmark`/`@ flow`
  to a v1 file, bump the first line to `#!grafli v2` yourself.

**Revising markdown prose — propose, don't overwrite.** When you rewrite a
markdown doc or note body that a human will review (a `.md` doc body, or any
file opened in the zen/`textli` editor), prefer emitting the change as inline
[CriticMarkup](http://criticmarkup.com/) suggestions instead of silently
replacing the prose:

* `{++added text++}` — insert
* `{--removed text--}` — delete
* `{~~old~>new~~}` — replace *old* with *new*
* `{==span==}{>>a question or note<<}` — comment on a span (no change proposed)

In the reading view these render as **track changes** — struck removals, red
additions — and the human accepts or rejects each with one key. That turns a
"what did the agent change?" diff-hunt into a quick review, and the marks are a
stable on-disk contract that round-trips through the file and git. Use a plain
`Edit` when you're making an uncontested mechanical fix; reach for suggestions
when the human should get the final say on wording or substance.

Speaker tags (for discussions and `Q:` replies): **a label of 1–16
characters starting with an uppercase letter, then `: `** — `AI:`,
`User:`, `GC:`, `Reviewer:`. 2+ distinct tags in one note trigger the
threaded rendering.

## Plan before you write

Skills produce noticeably better grafli when the model **plans first**
instead of writing code. Walk through these steps before you produce
any `@ box` / `@ arrow` / `@ note` lines. (This is the workflow for a
*precise* diagram — architecture, design, behavior. For a fast, memory-
first **sketchnote**, skip the ceremony and use the sketchnote playbook
in `references/genres.md` instead.)

1. **Question.** What single question does the diagram answer?
   ("How does an OAuth callback flow?" / "Which services own which
   data?") If you can't state the question in one sentence, ask the
   user.
2. **Cast.** List every actor / component / state as a flat bullet
   list. No coordinates yet. A view the eye can hold has **~5–9 nodes
   per level** — if the cast overflows that, plan the depth ladder now:
   group into containers, or push detail into notes / `&doc` docs /
   `&graph` sub-boards (see "The right altitude" in
   `references/design.md`).
3. **Flow direction.** Pick **one** for the whole diagram —
   left-to-right, top-to-bottom, or center-out (see "Flow direction"
   under Layout strategy in `references/design.md` for which fits what).
4. **Containers.** Group related items into `!flat` containers
   (services, layers, bounded contexts) before placing children.
   A container with children gets the flat body, sharp corners and
   small top-left caption automatically. An **empty** layer band — a
   tier you want to show but have nothing to put in yet — has to ask
   for that look: `!flat ^topleft ~small`. Without it an empty band
   renders as a big rounded leaf node, which reads as a component
   rather than a layer.
5. **Place children inside containers**, sized and aligned to the
   grid (multiples of 50). Use the container margin model in
   `references/design.md`.
6. **Arrows last.** Every arrow gets a label unless its meaning is
   obvious from context. Use semantic edge prefixes (`call:`, `data:`,
   `event:`, etc.) where they fit. Pick a **routing** to match the
   board: leave it **direct** (the default) for conceptual maps and
   sketches, where a straight line reads as "these relate"; use
   `!ortho` on structural boards — architecture, deployment, wiring,
   anything on a grid — where right angles read as real connections
   and parallel runs look deliberate; use `!spline` for soft or
   secondary relationships, and for the one connector that has to
   cross the board without pretending to be part of the grid. Keep one
   routing per board unless a connector is deliberately a different
   *kind* of relationship — mixed routings with no meaning behind them
   just look untidy.
7. **Notes for the human.** Add `T:` tasks and `Q:` questions as
   short headlines next to the relevant node. For pseudocode,
   assertion lists, behavioral specs, sequence sketches, or any
   other multi-line detail, use a `code:` note; for prose with light
   structure (rationale, checklists, review notes), use an `md:`
   Markdown note — those are the right home for content too long for
   a box label. Boxes are identifiers, notes are bodies (see the Box
   section) — never inline multi-line detail into a box label.
8. **Re-read against the quality bar.** Pretend you're the user opening
   the file: the eye lands on the entry point, the board answers its one
   question, depth is on demand, no arrows crossing. If not, reposition
   before saving — repositioning beats decoration. (The full bar is in
   `references/design.md`.)
9. **Render and verify.** Use `grafli render <file>.grafli /tmp/check.png`
   to produce a headless PNG and *look at it*. This is the single
   highest-leverage feedback step — most layout problems (overlaps,
   arrows crossing boxes, undersized containers, truncated labels) are
   obvious in the rendered image but invisible in the source. Render
   after every non-trivial edit, fix what you see, render again. Don't
   declare a diagram done without at least one render-and-look pass.
   Targeted variants keep the loop cheap: `--focus <ids>` crops to the
   region you just edited; `--lod` renders the zoomed-out semantic-zoom
   reading (check it on any board with containers); `--bookmark <id>`
   renders one flow stop as framed.
10. **Diagnose.** Run `grafli diagnose <file>.grafli` (add `--json`
    for machine-readable output) for static checks the eye misses:
    **dropped lines** (`parse-error` — a malformed directive or
    misplaced modifier silently removes the element; always fix these
    first), children outside parents, sibling overlaps, cramped
    containers, likely-truncated labels, arrow labels crowding endpoints
    or hiding arrowheads, missing `@path` / image refs. Each finding
    carries a `fixable` flag and a `severity`:

    * `severity: error` (`parse-error`, `invalid-parent-ref`, …) —
      always fix.
    * `fixable: true` — usually a real geometry mistake. Try to fix.
    * `fixable: false` — heuristic or possibly-intentional (a
      placeholder reference, an artistic crowding choice).
      Acknowledge once and move on.

    **Let the tool do the mechanical part.** `grafli diagnose <file>
    --fix` applies the fixes that need no layout judgment — clamp a
    child back into its parent, grow a cramped container, widen a
    truncated box, swap a mistyped `%color`/`*icon` to the suggested
    token — and rewrites the file (add `--dry-run` to preview the
    plan first). Findings that DO need judgment (sibling overlaps,
    crowded arrow labels, unknowns without a close match) are left to
    you — in `--json` each finding carries a `fix` field with the
    concrete planned edit (or `null`), so decide from data, not
    prose. Preferred loop: author → `diagnose --fix` → `render` →
    judge the leftovers yourself.

    **One pass, then stop.** Run diagnose, address the obvious
    findings, run it once more to confirm. If the same warnings
    persist, accept them as known limitations and ship — do not
    keep reshuffling the diagram trying to drive the count to zero.
    Warnings are guidance; errors gate: the exit code is 1 when
    errors are present (`--strict` widens the gate to warnings —
    only for boards that must be spotless), so you can loop on
    "re-run until `diagnose` exits 0" without parsing output.
    (For flows/decks there is a matching check:
    `grafli export <file> --check` — see
    `references/presenting.md`.)
11. **Format before committing.** `grafli fmt <file>.grafli` rewrites
    the board in the canonical serialized form — integer coordinates,
    canonical token order and spacing — exactly what the app's own save
    produces, so hand-authored edits don't create noisy git diffs later.
    Line order, comments, and blank lines survive; files with malformed
    lines are left untouched (fix the reported lines first). `--check`
    makes it a CI gate: exit 1 when a file would change.

## File format quick reference

```
# Comments and titles
@ box <id> "<label>" <x>,<y> <w>x<h> [%color] [^anchor] [~size] [!flat !bold !italic] [*icon] [&attach] [>parent] [# annotation]
@ arrow <from_id> (->|<-|<->|--) <to_id> ["label"] [@dx,dy] [%color] [!dashed|!dotted] [!thin|!thick] [!spline|!ortho] [~size] [# annotation]
@ note <id> <x>,<y> "<text>" [~size] [&attach] [>parent] [# annotation]
@ note <id> <x>,<y> [~size] &doc [>parent]        # doc-bodied: body = <stem>-res/<id>.md
@ image <id> "<relative_path>" <x>,<y> <w>x<h> [!frame|!noframe] [>parent] [# annotation]
@ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] [~iso] ["<description>"]
@ flow <id> "<label>" <ref>[:<dwell>][:detail=<v>][:focus=<v>] ... [~detail=<v>] [~focus=<v>] ["<description>"]
@ footer "<markdown>"                             # board-global slide-export branding line
```

`@ image` takes a raster file or an `.svg`, path relative to the `.grafli`
file. A referenced file is watched while the board is open, so an external
edit refreshes the element in place — you can write an SVG into
`<stem>-res/`, reference it once, and keep revising the SVG afterwards.
By default a raster image gets a subtle border and an `.svg` renders bare
(transparent vector art sits directly on the canvas); `!frame` / `!noframe`
override that per image.

`&attach` is a typed attachment: `&link:<url>` (the only kind that may
point outside the board), `&doc:<name>` (a markdown document at
`<stem>-res/<name>.md`), or `&graph:<name>` (a sub-board at
`<stem>-res/<name>.grafli`). See "Attachments" in
`references/design.md`.

`@ bookmark` / `@ flow` / `@ footer` build **guided tours and slide
decks** — see `references/presenting.md`. A file that uses them carries
a `#!grafli v2` header (the app emits it; when *you* add the first one
to a v1 file, bump the header yourself).

* One element per line — minimal git diffs.
* `#` lines are comments / metadata.
* Coordinates: `x,y` position (floats OK), `wxh` size.
* IDs are short lowercase identifiers (`auth`, `db`, `api-gw`).
* `%color` is a fixed semantic palette (not literal color names):
  `%base %primary %secondary %tertiary %subtle %accent %highlight
  %muted %soft %clay %teal %rose %forest %plum`, or a raw `#RRGGBB`.
  An unknown token (e.g. `%green`) silently falls back to the default
  fill — `diagnose` flags it as `unknown-color`.
* Modifiers in `[]` are optional and order-sensitive as shown.
* Multi-line text: use `\n` in labels and note text; a literal quote
  inside quoted text is `\"` (triple-quoted blocks need no escapes).

## Common mistakes — check before you save

These are the failure modes that recur most often. A 30-second checklist
catches them before the user opens the file.

* **Quote characters in quoted text.** A `"` inside single-line quoted
  text must be escaped as `\"`; an unescaped one breaks the line (it
  surfaces as a `parse-error` in diagnose). For quote-heavy or
  multi-line text, prefer a triple-quoted block (`"""..."""`) — no
  escapes needed there.
* **Modifiers on triple-quoted notes go AFTER the closing `"""`.**
  Putting them between the coordinates and the opening `"""` silently
  drops the entire note from the render. Correct form:
  ```
  @ note id 100,200 """
  code:
  ...
  """ ~small
  ```
* **`@ box` and `@ note` order their arguments differently.** Box puts
  the label *before* the coordinates (`@ box id "label" x,y wxh`); note
  puts the coordinates *before* the text (`@ note id x,y "text"`). Writing
  a box coords-first demotes it to a comment. Notes also take **no**
  `wxh` — size is `~size`, wrap width is `~width=N`.
* **Code-mode notes auto-widen to fit their longest line**, so a long
  line spills into a neighbouring column when notes sit side-by-side.
  Default to `~small` (and cap `~width`) in multi-column phases — see
  "Sizing in multi-column phases" in `references/format.md` for the
  budget math.
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

## Reference files — open on demand

The core above is deliberately lean. Detailed syntax, design guidance,
and presentation authoring live next to this file — read them when the
task needs them:

* `references/format.md` — the full element syntax: box / arrow / note
  modifier tables, code-mode keywords, markdown-note subset, discussion
  notes, images, colors, glyphs, `>parent` nesting, attachments. Open
  when you write any element beyond the quick reference above.
* `references/design.md` — diagram design principles: visual hierarchy,
  typography, layout strategy, container margin model, arrow discipline,
  the pattern gallery (architecture, pipeline, hub-and-spoke, visual
  notes). Open before you lay out a new board or add meaningfully to an
  existing one.
* `references/genres.md` — the genre playbooks: sketchnote, infographic,
  software diagrams (behavioral / architecture / design). Each gives the
  10-second job, layout archetypes, a closed feature palette, and an
  expert review checklist. Open BEFORE authoring any board of these
  genres — the palette decides which features you may use, and the
  expert checklist is your self-review before shipping.
* `references/presenting.md` — flows, slide composition, and export:
  bookmarks (incl. `~iso` scoping), text slides, container-as-slide,
  auto-flows, narration craft, PDF/PPTX export (incl. corporate
  templates) and the `export --check` verify loop. Open when asked to
  explain, walk through, present, or build a deck from a board.
* `references/thinking.md` — thinking boards: decision boards, tension
  maps, question landscapes, assumption/evidence boards, and the
  deliberate-incompleteness rules. Open when the user wants to *think
  through* a problem — options, trade-offs, unknowns — rather than
  document a system.
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

To remove an element, delete its line — and sweep its dependents (see
"Source-file hygiene" above): arrows, children, bookmark anchors, vault
docs.

## Inspect geometry before placing

`grafli inspect <file> [--ids a,b]` prints the resolved geometry as
JSON: element bounds, each container's inner rect after the margin
model, its children's orientation and gaps, and the **next free slot**
(with a fits/doesn't-fit verdict). Use it instead of re-deriving
placement arithmetic from the source — you still write the plain
coordinates yourself.

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
grafli render input.grafli /tmp/check.png --focus api,auth  # crop to a region
grafli render input.grafli /tmp/check.png --lod  # zoomed-out (semantic zoom) reading
grafli render input.grafli /tmp/stop.png --bookmark bm_x  # one flow stop as framed
grafli render input.grafli /tmp/stop.png --step tour:3    # step 3 with its detail/focus resolved
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
