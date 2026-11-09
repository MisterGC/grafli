# Diagram design principles

The grafli is a box-and-arrow tool — no freeform shapes, and the only
automatic placement is a layered layout (`=` in the app). These
constraints make intentional design essential: position has to mean
something, and you decide what.

## 1. Visual hierarchy

Every diagram needs a clear reading order:

* **Size for importance**: critical components get larger boxes
  (e.g., `250x120`), minor ones stay at `150x60` or smaller.
* **Color for category**: assign one color token per semantic group
  and stay consistent — don't use more than 3–4 colors per diagram.
* **Containers recede on their own**: a grouping box with no colour
  draws a quiet plate and outline behind its children, so they stand
  out. `!flat` on a container changes nothing; leave a container
  uncoloured unless its colour carries meaning.
* **Visual weight**: darker / saturated colors (`%primary`,
  `%accent`) feel heavier and anchor the eye — place them at focal
  points. Lighter tokens (`%muted`, `%subtle`, `%base`) recede;
  `%subtle` is the quietest filled grey, just off an unfilled box.

### Typography scale

| Role | How to set | Rendered size |
|------|------------|---------------|
| Diagram title | `~xxlarge` note | 40 pt |
| Top-level container label | box with children (no `~size`), bold | 16 pt |
| Component box label | (default, no `~size`) | 13 pt |
| Nested container label | box with children one level in / deeper, bold | 15 / 14 pt |
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

* Leave a container's size unset: its title is bold and steps down by
  level (16, 15, 14 pt), always above the 13 pt labels inside it; where a
  label inside is as large, the title takes a point more. A
  `~large` section heading still works; give it the 60 px top margin.
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

## 2. Pick the encoding from the question

A board says more than the text beside it when position means
something. Before you place a box, decide what x and y stand for: an
axis, an order, containment, a side. The catalogue below is the short
list. Each encoding answers one kind of question; pick the one whose
question matches the board's.

| Encoding | The question it answers | Position means | Placed by |
|---|---|---|---|
| matrix on two axes | Where does each item sit on two forces? | x and y are the two forces | hand |
| layered dependencies | What may depend on what? | the layer; every arrow points down | layered layout |
| containment | What lives inside what? | nesting is ownership | layered layout, per container |
| mirror | Are two paths symmetric? | the side; the same step sits at the same height | hand |
| proportional strip | How is a whole split by size? | width is the quantity | hand |
| before / after | What does this change change? | the column is the state; unchanged parts go quiet | hand |
| sequence | In what order does it happen? | x (or y) is the step | layered layout |

**When nothing fits.** Then the board is a plain graph: let its
dominant edge kind set the flow direction and lay it out as layered
dependencies. If even that adds nothing, the content is a list or a
table — say so instead of drawing it.

**Units per view.** A view holds at most 9 units — a unit is what the eye
counts: a box, a container read as one, a note. More goes a level down
(a `&graph` sub-board, a container whose detail moves into a `&doc`)
or into a list note. A thing with no edge is not a unit of the picture:
it goes into a list note, not a box. The exception is a box an encoding
places by its rule — an item on a matrix's two axes, a field in a
proportional strip: its position is the relation, so it counts as
related and stays a box.

**Layered layout** means `grafli layout <file>` (or `=` in the app on a
selection), then a touch-up by hand. **Placed by hand** means the
coordinates are the content: compute them from the encoding's rule
(below) and do not run the layered layout over them — it ranks boxes
by their edges and would erase the axis, the mirror or the widths.

### Matrix on two axes

*Where does each item sit on two forces?* Name both axes with a thin
arrow and a small label; place each item by its two values; emphasise
the corner the claim is about. Axis arrows run between plain notes.

```
@ note title 0,-80 "Only the CDN pays off right away" ~xlarge !flat !bold
@ note o 0,500 "·" !flat
@ note xe 750,500 "effort →" ~small !flat
@ note yp 0,0 "↑ payoff" ~small !flat
@ arrow o -> xe !thin
@ arrow o -> yp !thin
@ box cdn "CDN in front" 50,50 200x80 %highlight !bold
@ box redis "Redis tier" 450,100 200x80
@ box memo "memoize hot calls" 100,300 200x80 %muted
@ box rewrite "rewrite the query layer" 450,350 250x80 %muted
```

A tension map (`references/thinking.md`) is the one-axis case.

### Layered dependencies

*What may depend on what?* One full-width `!flat` container per layer,
top to bottom; every arrow points down. An arrow that has to point up
is the finding — draw it `%rose` and say so in the headline instead of
hiding it.

```
@ box ui "UI" 0,0 700x160 %secondary ^topleft ~large !flat
@ box app "app shell" 50,60 200x80 >ui
@ box export "exports" 400,60 200x80 >ui
@ box core "core" 0,300 700x160 %tertiary ^topleft ~large !flat
@ box view "view" 225,360 250x80 >core
@ box store "store" 0,600 700x160 %subtle ^topleft ~large !flat
@ box format "format" 225,660 250x80 >store
@ arrow app -> view "depends: renders"
@ arrow export -> view "depends: draws"
@ arrow view -> format "depends: reads"
```

### Containment

*What lives inside what?* Nesting is the relation: a child is owned by
its parent, so "contains" needs no arrow. Arrows are left for what
crosses a boundary, and a thing that is deliberately outside (not
stored, not owned) sits outside, `!dashed`.

```
@ box server "server" 0,0 600x300 %tertiary ^topleft ~large !flat
@ box room "room, one per board" 20,60 560x220 %secondary ^topleft !flat >server
@ box file "board.grafli" 40,110 220x80 >room
@ box vault "its vault" 300,110 220x80 >room
@ box presence "presence, not stored" 850,110 300x80 %muted !dashed
@ arrow presence -> room "data: 1 cursor per guest"
```

### Mirror

*Are two paths symmetric?* The shared thing in the middle, one path
down each side, the same step at the same height on both. A step one
side has and the other lacks leaves a visible gap, and that asymmetry
is the claim — emphasise it.

```
@ note hr 0,-60 "read" ~large !flat
@ note hw 600,-60 "write" ~large !flat
@ box f "file" 300,0 200x80 %primary
@ box parse "parse" 0,200 200x80
@ box board_r "Board" 0,400 200x80
@ box merge "merge3 + write" 600,200 200x80 %highlight !bold
@ box board_w "Board" 600,400 200x80
@ arrow f -> parse "data: lines"
@ arrow parse -> board_r "data: elements"
@ arrow board_w -> merge "data: elements"
@ arrow merge -> f "data: lines"
```

### Proportional strip

*How is a whole split by size?* Boxes side by side with no gap, each as
wide as its share at one fixed scale (say it in a comment). A 3-bit
field and a 16-bit field never get the same box.

```
# scale: 30 px per bit
@ box ver "ver 4" 0,0 120x80
@ box flags "flags 4" 120,0 120x80
@ box len "len 8" 240,0 240x80
@ box id "id 16" 480,0 480x80 %highlight !bold
@ note b0 0,90 "bit 0" ~small !flat
@ note b32 900,90 "32" ~small !flat
```

### Before / after

*What does this change change?* Two columns, the same element at the
same position in both. Unchanged parts are `%muted` on both sides;
what changes is emphasised in the after column; what goes away is
`!dashed` in the before column.

```
@ note hb 0,-60 "before" ~large !flat
@ note ha 400,-60 "after" ~large !flat
@ box p0 "parser" 0,0 250x80 %muted
@ box v0 "view" 0,200 250x80 %muted
@ box l0 "preview links" 0,400 250x80 %muted !dashed
@ box p1 "parser" 400,0 250x80 %muted
@ box v1 "view + server" 400,200 250x80 %highlight !bold
@ box l1 "live session" 400,400 250x80 %highlight !bold
@ arrow p0 -> v0
@ arrow v0 -> l0
@ arrow p1 -> v1
@ arrow v1 -> l1 "data: frames"
```

### Sequence

*In what order does it happen?* One row (or column), position is the
step, `step:` labels number the edges. Leave room between boxes for the
labels — about twice a box's width. A side path branches perpendicular
to the row; a loop back is the minority arrow.

```
@ box edit "edit in app" 0,0 200x80
@ box timer "autosave timer" 450,0 200x80
@ box merge "3-way merge" 900,0 200x80 %highlight !bold
@ box write "write file" 1350,0 200x80
@ arrow edit -> timer "step: 1 dirty"
@ arrow timer -> merge "step: 2 fire"
@ arrow merge -> write "step: 3 result"
```

## 3. Layout strategy

The layered layout places a graph by its edges (`grafli layout`, `=`
in the app; see step 5 of the loop in `SKILL.md`). It does not know
what position should mean, so the grid and the flow below
are yours to set: an encoding whose coordinates are the content is
placed by hand, and every layout gets a touch-up pass. Think in grids
and flows.

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

## 4. Containers (`>parent`)

Nesting with `>parent` is the primary way to show logical grouping
(layers, services, bounded contexts).

```
@ box backend "Backend" 20,250 520x200 %tertiary ^topleft ~large !flat
@ box api "API" 40,310 220x100 %accent >backend
@ box auth "Auth" 280,310 220x100 %accent >backend
```

* A container with no colour is already a quiet plate with an
  outline, not a competing box; `!flat` adds nothing to it.
* Its label is a bold top-left header, sized by level; `~large` on a
  top-level container makes a bigger section heading.
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
reflow the whole diagram, and never run the layered layout over a board
a human placed. A clean fit is *your* arithmetic: compute the absolute
`x,y` from the neighbours and emit it directly (there is no "place
near X" token — you do the resolution once, at write time, and the file
stays plain coordinates a human can read and drag).

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

## 5. Arrow discipline

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

## 6. Notes and annotations

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
* Keep notes short — if you need a paragraph, it belongs in a `&doc`
  (the box's own, or a doc-bodied note), not in a note's text.

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
  id); on a box/image/arrow it opens in the editor. A box shows the
  doc's first sentence on one line below its label (when the box has
  room for the whole sentence; it is never cut) — a container or a
  `!card` with children too, under its title — and `gv` peeks the whole
  doc — so open the doc with one
  sentence that says what the box is.
- `&graph:<name>` — a sub-board at `<stem>-res/<name>.grafli`; its own
  resources nest at `<stem>-res/<name>-res/`.
- `&graph:<name>#<id>` / `&link:<path>.grafli#<id>` — open that board
  framed on its bookmark (else element) `<id>`; the way to point from one
  map into one place of another board (a `#!grafli v3` file, see
  `references/format.md`).

Content attachments live only in the `<stem>-res/` vault, so a board
plus its vault is the complete, copyable unit. Legacy untyped `&url`
values still parse and are classified on load. An attachment is distinct
from `# annotation`: it's visible/clickable; an annotation is invisible
authoring metadata.

## 7. Common patterns

Most technical diagrams reduce to one of these shapes, and the format
covers the common types directly: **architecture** (layered containers),
**flow / pipeline** (L→R chain), **hub-and-spoke** (gateway / event bus),
**state machines** and **sequences** (nodes + transition arrows, or a
`code:` note with `state from -> to` lines), **ER / class** (boxes +
labelled relationship arrows), and **mind maps / concept boards** (center
node + radiating ideas — see "Visual notes" below). Pick the shape from
the question, then the flow direction. When position should carry
meaning of its own — an axis, a side, a size — pick from the encoding
catalogue in section 2 instead.

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
renders as its own canvas, and the viewer follows the link. Once the box
is large enough on screen it shows a miniature of the sub-board filling
the box, with the label on a band across its top — give a box you expect people to enter room for one (wider and
taller than a plain node).

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
