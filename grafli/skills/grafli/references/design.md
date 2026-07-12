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
  `*lightbulb` idea node, `*lead:database` labelled items, a bold heading over a
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
  concept in the middle, contributing ideas around it. A `*lightbulb` (or
  other fill symbol) turns the center box into a framed concept node.
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

@ box leaf "Photosynthesis" 420,270 220x140 %highlight *lightbulb

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

### Sketchnotes — moved to the genre playbooks

Sketchnote guidance (the job, archetypes, feature palette, the
master-sketchnoter review) lives in `references/genres.md` alongside the
infographic and software-diagram playbooks. Open that file before authoring
a sketchnote; this file keeps the universal design principles it builds on.
