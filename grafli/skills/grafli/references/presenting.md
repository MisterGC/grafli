# Presenting a board — flows, slides, export

When the user asks you to **explain, walk through, narrate, or present** a
graph, don't dump the whole picture — author a **flow**: an ordered sequence
of saved viewpoints with narration. It plays in-app (manual step or auto-play,
`p` cycles paused/playing/loop), presents fullscreen (`F5`), and exports to
**PDF and PPTX slide decks**. It lives in the same `.grafli` file as plain
text, so you write it the same way you write boxes.

## The directives

```
@ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] [~iso] ["<description>"]
@ flow     <id> "<label>" <ref>[:<dwell>][:detail=<v>][:focus=<v>] ... [~detail=<v>] [~focus=<v>] ["<description>"]
@ footer   "<markdown>"
@ title-bg thumbnail-art
```

(Full grammar in `references/format.md`. Adding the first bookmark/flow to a
v1 file? Bump the header to `#!grafli v2` yourself.)

* A **bookmark** is one viewpoint. `@<ids>` is a **semantic anchor** — list
  the box / note ids to frame; the app fits them at display time, so the
  bookmark stays correct when the layout changes. **Always anchor on ids —
  never raw coordinates.** You know the ids; you don't know good pan/zoom
  numbers. (`~view=x,y,w,h` exists for a node-less viewpoint, but you'll
  rarely want it — prefer anchors.)
* A **flow** lists bookmark ids in order. `:<dwell>` is that stop's auto-play
  time in seconds (omit for the default); it only matters for auto-play /
  booth playback.
* A stop may lie in **another board**: `<board>#<bookmark>`, with `<board>`
  the name of a sub-board of the flow's own board, or a `.grafli` path
  relative to the flow's board file for anything deeper — on
  `System.grafli`: `combat#lunge`, `System-res/combat-res/impact.grafli#hit`. Use it for a tour that
  crosses levels (a request path, "a blow lands"); author the bookmark in
  that board, keep the flow on the board the tour starts on, and bump its
  header to `#!grafli v3`. Playback enters the board for that stop; the
  slide export renders it from there.
* A stop may frame an **arrow**: give it `~id=<id>` and list that id in the
  bookmark's focus (`@ bookmark b_call "The call" @call`). Playback frames
  its two ends and draws the arrow in the tour accent, thicker, with the
  rest dimmed — use it for a step of a runtime flow or pipeline ("this step
  is this call"). An arrow id makes the board `#!grafli v3`.
* `@ footer` (board-global, one per file) brands the bottom of every exported
  content slide with a small muted markdown line; the title slide stays a
  clean cover. `@ title-bg thumbnail-art` backs the title slide with a faint
  collage of the flow's own slide thumbnails.

## Scoped stops (`~iso`)

By default a stop shows **everything inside the framed region** — anchoring
one child of a container still shows its siblings bleeding in at the edges.
Add `~iso` to narrow the stop to *exactly* the anchored items (plus the
arrows between them):

```
@ bookmark bm_auth "Auth alone" @auth,db ~iso "Only these two, nothing else."
```

Use `~iso` when the stop's point is *this element, isolated*; skip it when
surrounding context helps.

## Per-stop detail & focus

Two presentation settings, set on the flow as the default and overridden per
step where one stop needs something else (unset = inherit: step ← flow ←
the app's global state). Both are honoured in playback, present mode,
PDF/PPTX export, and `grafli render`.

* **detail** — `full` renders the stop as authored; `summary` collapses
  containers to headline tiles (the zoomed-out semantic-zoom reading,
  regardless of zoom); `auto` follows the app's global LoD toggle. The
  classic pattern: `~detail=full` on the flow, `detail=summary` on the
  wide opening stop of a big board.
* **focus** — `complete` keeps only elements *completely* inside the framed
  viewport at full opacity and blends the partially visible edge-slivers
  out (a connector stays opaque only when both endpoints are fully shown);
  `none` is off. Use it when neighbours bleeding in at the frame's edges
  would distract from the stop's claim; skip it when that context helps.
  Note `~iso` is the stronger tool for *isolating anchored items* — `focus`
  merely de-emphasizes, keeping faint context visible.

```
@ flow tour "Demo" bm_wide:6:detail=summary bm_svc:detail=full bm_api:focus=complete ~focus=none
```

A `&doc` box's first sentence shows on a slide when the slide's frame keeps
it legible (judged on the slide shown 1280 px wide, the canvas's floor);
a wide opening stop drops it, a close stop on the box keeps it.

## Text slides

A bookmark that anchors a **single note** and has **no description** exports
as a **text slide**: the note's markdown renders as real, selectable text
with clickable links — not a flattened image. This is how you author agenda,
summary, link-list, or quote slides directly from the graph:

```
@ note agenda 2000,0 """
md:
# What we'll cover
1. The request path
2. Where it fails
3. [Runbook](https://wiki.example.com/runbook)
""" ~small
@ bookmark bm_agenda "" @agenda
```

Add a description (or anchor more than the one note) and it reverts to a
normal diagram slide.

## Container = slide

A stop whose anchor is a **container together with its contents**
(`@s1,s1_note,s1_box ~iso` — the container id *plus* its children; the
container alone is not enough) uses the container's label as the slide
title and its rect as the slide frame — the container's own border/fill
are dropped, so its contents fill the page cleanly. This is the tool for
composed, multi-element slides: bundle a mini-diagram and a prose note in
a container, anchor the container with its children, `~iso`, done. Don't
repeat the container's label as a heading inside a child note — the label
already becomes the slide title.

**Shape the container to the slide ratio** so the content fills the page
without letterboxing. For 16:9, height = width × 9/16, plus ~40 px if a
board-global footer is set (the in-app `d`+`r` keybind does exactly this
math). E.g. a 960-wide slide container: `960x540` (no footer) or `960x580`.
Content that spills past the frame is your cue to trim the text or split
the slide. Shape containers to the slide only in a slide region you build
for the deck; on a map, frame the stop with a bookmark instead (see
"Slides from a map" below).

## Dedicated slide regions

For a real deck, don't contort the working board into slides. Keep the board
a board, and lay out a **separate slide region** off to the side (or below):
a row of 16:9 containers, each a purpose-built slide mixing prose notes and
small focused diagrams, plus text-slide notes for agenda/summary. The flow
then mixes stops on the *live* diagram (the system as drawn) with the
purpose-built frames. The deck is a view of the board — the board doesn't
become the deck.

## Slides from a map — frame, legibility, headline

A map (an explanation map, an architecture board) is laid out for the
canvas, not for 16:9. A tour of it comes out as slides that are
overloaded (text too small to read) or thin strips (a wide row with
empty page above and below) when its stops frame the wrong region. Three
rules make a map's tour export as slides without touching the map.

* **Frame each stop with a bookmark, not by sizing containers.** Don't
  reshape a layer or a group to 16:9 to make it a slide: the map's
  layout serves every other view, and a container with its contents
  framed whole is usually too big for one slide anyway. Anchor the stop
  on the 2–6 ids the slide is about, `~pad=<n>` for room around them,
  `~iso` to drop the neighbours that would bleed in at the edges. Put a
  note that explains a part next to that part, so the stop that frames
  both stays small. A wide row is several stops, one per cluster, not
  one strip. GUI: select the ids, <kbd>g</kbd><kbd>b</kbd>.
* **Do the legibility arithmetic.** A slide's diagram area is about
  895 pt wide and, under a headline, about 425 pt high; the stop's frame
  (the anchored items plus `~pad` on each side, 60 px by default) is
  scaled to fit it. A note is legible on the slide when it lands at
  11 pt or more, so the frame may be at most `895 × size / 11` px wide
  and `425 × size / 11` px high, with `size` the note's text size in
  px:

  | Note size | px | Widest frame | Tallest frame (with headline) |
  |---|---|---|---|
  | `~small` | 10 | ≈ 810 px | ≈ 390 px |
  | default | 13 | ≈ 1,060 px | ≈ 500 px |
  | `~large` | 18 | ≈ 1,460 px | ≈ 700 px |

  A stop without a headline gets about a fifth more height. A frame much
  wider than 2:1 fills the width and leaves the page empty above and
  below — the strip; much narrower than 16:9 fills the height and leaves
  the sides empty. Aim the frame between 16:9 and 2:1. Only notes over
  80 characters count (a shorter note is an annotation on the picture),
  and `export --check` measures every one, so let the check judge the
  edge cases.
* **A headline per stop.** The bookmark's label is the slide's title:
  write it as a claim the slide shows ("Every view draws the same
  Board"), not a topic ("Views"), short enough for one line (about 35
  characters). The tour's stops read in order as the argument; the
  description stays for what the picture and the headline don't say,
  and is often empty.

### Example — a tour of grafli's pipeline

```
#!grafli v2
@ box file ".grafli file" 0,0 180x80
@ box parse "parse()" 280,0 180x80
@ box board "Board" 560,0 180x80
@ box canvas "Canvas" 880,-110 180x70
@ box render "render" 880,0 180x70
@ box slides "PDF / PPTX" 880,110 180x70
@ arrow file -> parse "text"
@ arrow parse -> board "Board"
@ arrow board -> canvas
@ arrow board -> render
@ arrow board -> slides

@ note why_text 0,140 "One plain-text file is the whole board: a diff shows every change, and git keeps its history without a save button."
@ note why_same 560,200 "Every view reads the same Board, so a slide can never show a different diagram than the canvas does."

@ bookmark b_all "One parse feeds every view" @file,parse,board,canvas,render,slides ~iso
@ bookmark b_text "The board is a text file" @file,parse,why_text ~iso
@ bookmark b_views "Every view draws the same Board" @board,canvas,render,slides,why_same ~iso
@ flow tour "From text to every view" b_all b_text b_views "How one file becomes the canvas, the renders and the slides."
```

The opening stop frames the whole pipeline, about 1,180 × 410 px — too
wide for a default note, so it is `~iso` on the boxes and the notes stay
out of it. The next two stops each frame one cluster with the note that
explains it, both inside 1,060 × 500 px. Every headline is a claim and
no stop needs a description. `grafli export map.grafli --check` prints
`No findings.` With the third stop unscoped and `why_same` 40 px lower,
its frame grows past 500 px high and pulls in `why_text`:

```
[overloaded] slide #3 Every view draws the same Board: note 'why_text' at 10.6 pt (floor 11 pt); note 'why_same' at 10.6 pt (floor 11 pt) — trim the text or split the slide
```

## Compose the narrative deliberately

The *order and framing* are the explanation:

1. **Open wide.** First stop frames the entire graph (or its top-level
   containers) so the viewer gets the map.
2. **Go to the entry point.** Where the story starts — the request ingress,
   the user, the trigger.
3. **Follow the path.** One stop per meaningful hop, in causal / temporal
   order. Frame just the 1–3 items that matter at each step (anchor on those
   ids), not the whole graph — that zoom *is* the focus.
4. **End on the payoff.** The data store, the result, the conclusion, the
   call to action.

## Narration — and when to stay silent

* Each stop's **description is the narration**: it's the on-canvas caption
  during playback and the floating caption card on the exported slide. Write
  *why this stop matters*, not what's already visibly labeled. The caption
  renders in full, word-wrapped — **budget it at ≤ 280 characters** (the
  format's `MAX_DESCRIPTION_CHARS`); `export --check` flags anything longer.
* **Let the graph speak when it already does.** If the framed boxes, arrows,
  and notes already carry the point, give the stop a **blank label and no
  description** — it exports as a clean diagram-only slide. Add words only to
  say something the picture doesn't.
* The **flow's own description** (markdown) renders on the title slide — it
  can carry emphasis, lists, and clickable links.
* **Reuse** a bookmark across flows when the same viewpoint serves two
  different narratives.

## Auto-flows — author the graph, get the tour

If the diagram encodes a single forward path, the tour can be generated: one
slide per node, following forward arrows (`g`+`F` in the app; the flow
regenerates after edits, keeping its title page). To author *for* auto-flow:

* Keep the spine a **single forward chain** — auto-flow follows an arrow
  only when exactly one forward arrow leaves the node; it stops at forks and
  does not follow `--` or `<->` connectors.
* Note/image connectors default to *annotation* links, which auto-flow
  skips. Promote a note or image to a first-class stop with `~kind=graph`
  on its arrow (see `references/format.md`).
* A box becomes a titled focused diagram, a note a text slide, a parent its
  whole subtree, a title-less image a full-bleed image slide.

## The deck's job shapes the authoring

* **Live talk** — you speak, slides support: sparse or blank captions,
  manual advance, one claim per slide, generous zoom.
* **Async walkthrough** — the deck explains itself: rich captions on every
  stop, dwell times set, a text slide up front for context and one at the
  end with links / next steps.
* **Booth / kiosk loop** — auto-play with `p` set to loop: short dwells
  (4–8 s), self-contained captions, an opening slide that hooks.

One claim per slide, always. If a caption needs two paragraphs, it's two
stops.

## Export

```bash
grafli export deck.grafli tour.pdf  --flow tour             # PDF slides
grafli export deck.grafli tour.pptx --flow tour             # branded PPTX
grafli export deck.grafli tour.pptx --flow tour --theme blank
grafli export deck.grafli tour.pptx --flow tour \
  --template corporate.pptx \
  --title-layout "Title" --content-layout "Content light"   # corporate deck
```

* **PDF** — title slide (flow label + markdown description), one slide per
  stop, descriptions as floating caption cards; notes are re-drawn as real
  selectable text in place, so links stay clickable and text searchable.
* **PPTX** — the same slides as an *editable* deck: title, caption, footer
  and every in-place note are native textboxes. `--template` drops the
  content into an existing corporate `.pptx` (its master, theme, fonts and
  placeholders are kept; grafli's chrome is dropped) — the corporate look
  applies with no manual restyling. `--flow` is optional when the file has
  a single flow.

## Verify — the deck has a check loop too

* `grafli export <file> --check [--flow <id> | --all-flows] [--json]`
  dry-runs the export and reports: slide count, **overloaded slides** (text
  that can't fit at the legible floor — an overloaded slide is hard for an
  audience anyway), **over-long captions** (a description past the 280-char
  budget), **dangling refs** (a flow step naming a missing bookmark, a
  bookmark anchoring a deleted id), and missing vault docs. Exit 1 means fix
  and re-check. An overloaded slide names each note under the floor with
  its size at that slide's frame —
  `[overloaded] slide #2 Overview: note 'evidence' at 2.2 pt (floor 11 pt)`
  — so fix that note: give it its own stop, frame it tighter, or trim it.
  `--all-flows` checks every tour of the board in one run (`--json` then
  emits a list, one report per flow).
* `grafli render <file> stop.png --step <flow>:<n>` renders step *n*
  (1-based) exactly as playback shows it — framing plus the step's resolved
  `detail`/`focus`. `--bookmark <id>` renders a bare bookmark (honouring
  `~pad` and `~iso`); add `--detail full|summary` / `--focus-mode complete`
  to preview a setting before writing it into the flow. Look at the stops
  that matter before shipping the deck.

## Worked example

```
#!grafli v2
@ box client "Client" 0,0 160x80
@ box api "API Gateway" 280,0 180x80
@ box auth "Auth Service" 280,220 180x80
@ box db "Postgres" 640,220 180x80
@ arrow client -> api "request"
@ arrow api -> auth "call: verify"
@ arrow auth -> db "data: user lookup"

@ footer "Acme Platform Team — internal"
@ bookmark bm_all "The system" @client,api,auth,db ~pad=80 "Three services behind one gateway."
@ bookmark bm_in "Entry point" @client,api "Every request lands at the gateway first."
@ bookmark bm_authz "" @api,auth
@ bookmark bm_data "Data layer" @auth,db ~iso "Auth resolves the user against Postgres — shown alone."
@ flow tour "How a request flows" bm_all bm_in:6 bm_authz:5 bm_data:8 "From the front door through auth into the data layer."
```

`bm_authz` is intentionally graph-only: the two boxes and the "call: verify"
arrow already tell that part of the story, so it needs no caption. `bm_data`
uses `~iso` to end on the payoff with everything else stripped away.
