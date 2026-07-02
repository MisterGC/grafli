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
@ flow     <id> "<label>" <bookmark_ref>[:<dwell>] ... ["<description>"]
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
the slide.

## Dedicated slide regions

For a real deck, don't contort the working board into slides. Keep the board
a board, and lay out a **separate slide region** off to the side (or below):
a row of 16:9 containers, each a purpose-built slide mixing prose notes and
small focused diagrams, plus text-slide notes for agenda/summary. The flow
then mixes stops on the *live* diagram (the system as drawn) with the
purpose-built frames. The deck is a view of the board — the board doesn't
become the deck.

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
  *why this stop matters*, not what's already visibly labeled.
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

* `grafli export <file> --check [--flow <id>] [--json]` dry-runs the export
  and reports: slide count, **overloaded slides** (text that can't fit at
  the legible floor — an overloaded slide is hard for an audience anyway),
  **dangling refs** (a flow step naming a missing bookmark, a bookmark
  anchoring a deleted id), and missing vault docs. Exit 1 means fix and
  re-check.
* `grafli render <file> stop.png --bookmark <id>` renders one stop exactly
  as framed (honouring `~pad` and `~iso`) — look at the slides that matter
  before shipping the deck.

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
