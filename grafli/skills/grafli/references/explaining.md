# Explaining a subject — maps you read level by level

When the user wants to **understand, learn, explain or review** a subject —
a codebase, a system, a protocol, a concept — build an **explanation map**:
a small overview board whose parts you enter to see their detail, tours that
walk through what happens in order, and optional overlay files that colour
the map with analysis data. The reader learns by looking and by asking on
the map, not by reading long text. Code is one kind of subject; the rules
below hold for any.

A map is built only from what every board has: boxes, arrows, notes, `&doc`
/ `&graph` / `&link` attachments, element ids, bookmarks and flows. What
makes it an explanation map is how you split the subject and what you put
on each level.

## The top board — the problem and its layers, not internals

The top board is where the reader decides whether they follow you. Open
it with what they came with, not with what an implementer asks ("what is
generated, what is written once" is a question for a level further down).
The top board shows three things, in this order:

1. **The problem** — one sentence: what the subject is for, the need it
   answers. A plain note at the top, the largest text on the board.
2. **The shape of the answer** — one sentence: how the subject answers it,
   in the words of its layers ("one plain-text file, a canvas that draws
   it, exports that carry it out"). A `~small` note under the problem.
3. **The layers of the problem** — drawn as **stacked full-width
   containers**, one per layer, the way people recognise a layer diagram:
   the same width, one under the other, the layer's name on the left, its
   colour from the map's palette (`%name ^left`, see "A resting colour per
   layer" below). Each layer holds its few parts as `!flat` boxes. Zoomed
   out, `^left` keeps each container a band with its name on the left, so
   the board still reads as a stack of named layers.

* **One concrete case on every layer.** Pick one small, real instance of
  the subject and say in one `~small` note per layer what it is on that
  layer — the same case all the way down the stack. The general concept
  stays the subject; the case makes it graspable.
* **Say it is an example, not the scope.** A note under the answer names
  the case and says so ("Example, not the scope: …"), so the reader does
  not take the map for a map of that one case.
* **Mechanisms go one level down.** How a part works — its algorithm, its
  data, what is generated from what — lives in the part's `&graph`
  sub-board or `&doc`, never on the top board.

The problem note is the top board's question note (see the next section):
the top board's question is "what is this for, and what is it made of?".

GUI: select a layer's parts, <kbd>Ctrl</kbd>+<kbd>G</kbd> wraps them in a
new container; on the container <kbd>s</kbd> <kbd>e</kbd>, Label → left,
<kbd>s</kbd> <kbd>c</kbd> the layer's palette entry, and resize it to the
width of the other layers; on its parts <kbd>s</kbd> <kbd>e</kbd>,
Background → flat. A single box dragged onto a layer nests in it.

## The level — one question, one split, its evidence

Every board of the map is a **level**. Before you place anything, write
down three things:

1. **The question the level answers** — one sentence, shown on the level as
   a small note at its top-left (`Q` is for open questions, so use a plain
   note: `"How does a blow reach the camera?"`). If you cannot state it, the
   level has no job — merge it into its parent.
2. **The split** — the parts this level divides its subject into, about
   nine at most (5–9 reads at a glance; more means a missing level).
3. **The evidence for the split** — why these parts and not others. For
   code: `@path:line` refs to where each part lives, in a `code:` note or the
   box's doc. For a concept: the source (the spec section, the paper, the
   chapter). Evidence lets the reader **reject an arbitrary split** instead
   of learning it; a split you cannot back with evidence is a guess — mark
   it with a `Q:` note rather than presenting it as fact.

Then per part:

* **One-line labels.** A box names its part in the fewest words —
  `impact()`, `Bit stream`, `Router`. Text stays one line per box on the
  canvas.
* **Text on demand: the box's own `&doc`.** When a part needs a few
  sentences of explanation, give the box `&doc:<name>` and write the
  explanation into `<stem>-res/<name>.md`. Open the doc with **one sentence
  that says what the part is**: the app shows that sentence, cut to one
  line, under the label when the box is shown in full detail, and
  <kbd>g</kbd><kbd>v</kbd> opens the whole doc in a panel beside the box.
  The canvas stays a picture; the reading is one key away.
* **A deeper level when relationships matter.** When a part has inner
  parts that relate to each other — more than a list could say — give it
  `&graph:<name>` and build the sub-board `<stem>-res/<name>.grafli` as the
  next level, with its own question. The box then fills with a miniature of
  the sub-board once it is large enough on screen, the label on a band on top; size such a box wider and
  taller than a plain node so the miniature has room. <kbd>g</kbd><kbd>d</kbd>
  (or <kbd>Return</kbd>) zooms into it, <kbd>g</kbd><kbd>u</kbd> comes back
  as the reader left, and the status bar shows the path of labels entered
  through.
* **One attachment per element.** A box that needs both an explanation and
  a deeper level gets the level (`&graph`); its explanation moves into the
  sub-board — as the level's question note plus the docs of its parts.
* **Pseudocode is structure**, not prose: an algorithm stays in a `code:`
  note beside its box, where it renders as scannable pseudocode.

## Relationship kinds on the arrows

An arrow on a map says what kind of relationship it is. Use the semantic
prefixes where one fits, a plain verb where none does — and one vocabulary
across all levels of a map:

| Relationship | Arrow label |
|---|---|
| calls | `call: <what>` |
| signals / emits | `event: <what>` |
| data flows | `data: <what>` |
| needs / depends on | `depends: <what>` |
| generated from | `generated from` |
| runs on | `runs on` |

A level whose arrows all say `uses` explains nothing; name the call, the
signal, the data.

## A resting colour per layer — readable before any overlay is on

A map whose boxes are all outlines reads as nothing until the reader
presses <kbd>A</kbd>. Give the map a **resting scheme**: one colour per
layer of the subject (for code: the format, the canvas, the app shell, the
exports — whatever the subject's own layers are), the same colour on every
board of the map. Overlays are drawn over it while on and the map returns
to it when they are off. Outline stays the default for plain boards; the
resting scheme is a convention of explanation maps, not of every board.

* **Name the layers once, in the map's palette.** Write
  `<stem>-res/palette.json` beside the top board, one entry per layer,
  its `label` the layer's name — the legend shows it
  (see "Map palette" in `references/format.md`). Every board of the map
  resolves `%name` against it, so the colours stay the same on every level.
  Pick quiet theme tokens (`%highlight`, `%soft`, `%rose`, `%muted`,
  `%base`): they follow light and dark, the label stays readable on them,
  and the loud tokens (`%primary`, `%accent`) stay free for emphasis.
  3–5 layers; a sixth colour is a missing level.
  GUI: the palette is a data file with no in-app editor, like an overlay
  file; the app watches it and recolours the open board when it changes.
* **Fill each part box with its layer.** A box on the canvas takes its
  layer's entry: `%canvas`. A box that sits in a layer container
  (`>parent`) gets the lighter tint of the container's colour instead: the
  container carries the layer (`%canvas ^left !flat`), the box inside is
  `!flat` with no colour of its own, and the container's colour shows
  through it lighter. A box that is not a part — a link back to the map,
  a pointer out — stays an outline.
  GUI: select the layer's boxes, <kbd>s</kbd> <kbd>c</kbd>, pick the entry
  below the theme colours, <kbd>Enter</kbd>. For the container form:
  <kbd>s</kbd> <kbd>e</kbd> on the container, Background → flat and
  Label → left; on its boxes, <kbd>s</kbd> <kbd>e</kbd>, Background → flat,
  and leave their colour unset.
* **Label and doc line as one block near the top.** `^topcenter` puts the
  label at the top of the box with the `&doc` first sentence right under
  it, so a filled box is found at a glance and reads as part of its layer;
  centred text in empty space doesn't.
  GUI: <kbd>s</kbd> <kbd>e</kbd>, Label → top-center, <kbd>Enter</kbd>.
* **Show the key.** <kbd>Shift</kbd>+<kbd>M</kbd> (or *Legend* in the side
  panel) shows the layers the board uses; `grafli render --legend` and
  `grafli export --legend` draw it into a picture or a deck.

A board that uses a palette name is written `#!grafli v4`; the app writes
the header itself when you save.

## Slide-grade boards — a claim, three weights, a path

A board where every box has the same size, colour and weight reads as a
wall: the reader cannot tell what the board says or where to start. A
level reads like a good slide when it states its point, makes one or two
parts loud and the rest quiet, and shows the order to read it in. Each
move below is an opt-in modifier on a box, note or arrow; a board that
uses none of them looks as before. Every modifier here is written
`#!grafli v4` — the app writes the header when you save.

* **A claim headline per board.** Above the level's question note, put
  one sentence that states what the level shows — a claim the reader can
  check against the board ("One parse feeds every view"), not a topic
  ("Parser"). It is the largest text on the board, in the proportional
  face, without a plate: `@ note claim … "<claim>" ~xlarge !sans !bold
  !flat`. On the top board the problem note is the headline (see "The top
  board" above).
  GUI: <kbd>t</kbd>, click, type the claim; <kbd>s</kbd> <kbd>t</kbd>,
  pick a large row and the Bold column, <kbd>Tab</kbd> to sans,
  <kbd>Enter</kbd>; <kbd>s</kbd> <kbd>e</kbd>, Background → flat.
* **Three visual weights.** Give every element one of three weights and
  keep to them on every level:
  * *Emphasis* — the one or two parts the claim is about. A loud theme
    token the palette leaves free (`%primary`, `%accent`) with `!ink`, so
    the label sits in a light ink straight on the dark fill, and `!sans`
    for the title: `%primary !ink !sans`.
  * *Normal* — the parts of the split, in their layer's palette colour
    (see "A resting colour per layer").
  * *Muted* — context the reader needs to place things but should not
    dwell on: no fill, `~small`. A part that is later or optional also
    gets `!dashed` (or `!dotted`) so its outline says so.

  GUI: emphasis — <kbd>s</kbd> <kbd>c</kbd>, pick the token,
  <kbd>Enter</kbd>; <kbd>s</kbd> <kbd>e</kbd>, Label ink → on fill;
  <kbd>s</kbd> <kbd>t</kbd>, <kbd>Tab</kbd> to sans. Muted —
  <kbd>s</kbd> <kbd>t</kbd>, a small row; <kbd>s</kbd> <kbd>e</kbd>,
  Outline → dashed.
* **Quiet evidence.** The evidence for the split (`code:` note, refs)
  stays on the board but out of the way: `~small`, at the bottom or the
  edge, never between the parts. Arrows that only point at evidence or
  context stay quiet too — `%muted !thin`, or the muted annotation look a
  note connector gets by itself.
  GUI: <kbd>s</kbd> <kbd>t</kbd>, a small row; on a connector
  <kbd>s</kbd> <kbd>e</kbd>, Thickness → thin, and <kbd>s</kbd>
  <kbd>c</kbd> for `%muted`.
* **Numbered paths.** When the claim is about an order, number the parts
  along it with filled numbers before the label: `*lead:solid-1`,
  `*lead:solid-2`, … The reader follows 1, 2, 3 before reading anything
  else. Outlined numbers (`*lead:3`) are for side remarks, `*lead:solid-0`
  for a step zero. Give the path a tour whose stops go in the same order,
  so the numbers and the tour tell the same story.
  GUI: <kbd>s</kbd> <kbd>i</kbd>, <kbd>Tab</kbd> to lead, type the digit,
  <kbd>f</kbd> fills it, <kbd>Enter</kbd>.
* **Category bars with matching connectors.** When the parts a step leads
  to fall into kinds (in the app / outside it, read / write), put a thin
  bar over each kind's column — a box about 36 high, the column's width,
  in the kind's palette entry, its label in ink on the fill: `%export !ink
  !sans`. Every connector into that kind takes the same entry, so the
  colour carries the kind from the bar to the arrow. Pin the sides when a
  column reads left to right (`~from=right ~to=left`), and use dot ends
  (`!dot`) for a "feeds each of these" fan-out.
  GUI: <kbd>n</kbd>, click, name the bar, resize it to the column;
  <kbd>s</kbd> <kbd>c</kbd>, the palette entry; <kbd>s</kbd>
  <kbd>e</kbd>, Label ink → on fill. Select the connectors
  (<kbd>Shift</kbd>+click), <kbd>s</kbd> <kbd>c</kbd> the same entry;
  <kbd>s</kbd> <kbd>e</kbd>, Ends → dot, Leaves from → right, Enters at →
  left.
* **Status labels.** A part's resting state — `live`, `draft`,
  `deprecated` — is a one-word pill on the box's bottom edge:
  `~status=live`, coloured with `~status=draft:%rose`. It shows in every
  view and export, with no overlay on. Use one small vocabulary per map;
  states that need analysis data (coverage, findings) stay overlays.
  GUI: <kbd>s</kbd> <kbd>s</kbd>, type the word, <kbd>Enter</kbd>, then
  the colour grid colours the pill (<kbd>Esc</kbd> keeps it uncoloured).
* **Cards.** A part shown with its inner parts — a data structure and
  its fields — stays a node with `!card`: it keeps its fill, border and
  title at the top centre while it holds children, where a plain box with
  children turns into a flat container. Use a container for a layer, a
  card for a part.
  GUI: <kbd>s</kbd> <kbd>e</kbd>, Background → card.

Keep it to one emphasis, one path and one set of category bars per
board; a board that uses every move at once is a wall again.

## A map across repos — one board per repo, a bench board linking in

When the subject spans several repos (a game and its engine, a client and
its schema), give **each repo its own map** in that repo, and write one
**bench board** that shows the repos as boxes with the relationships
between them. A bench box links into a place of a repo's map with a board
link that ends in `#<id>`:

```
@ box engine "clayground" 400,0 240x120 &link:~/dev/gamedev/clayground/mgc/learn/map.grafli#camera
```

The link opens that board framed on its bookmark `<id>` — or, without one,
its element `<id>` — selected; <kbd>g</kbd><kbd>u</kbd> comes back. Point at
a **bookmark** when you can: it is named for the reader and survives the
target board's layout changing. Inside one map, `&graph:<name>#<id>` does
the same for a sub-board. A board using a `#<id>` link carries a
`#!grafli v3` header (see "Board links into a bookmark or element" in
`references/format.md`).

## Tours for order

Structure says **where** a thing is; a tour says **how it behaves** — what
happens when a request arrives, a blow lands, a value is encoded. Author it
as a flow (`references/presenting.md`), with these map-specific moves:

* **A tour crosses levels.** A stop `<board>#<bookmark>` lies in another
  board — a sub-board's name, or a `.grafli` path relative to the flow's
  board for anything deeper. Playback enters that board for the stop (the
  breadcrumb shows it) and the next stop continues the same flow. Keep the
  flow on the board the tour starts on.
* **A step that is a call is an arrow.** Give the arrow `~id=<id>` and put
  that id in a bookmark's focus: the stop frames the arrow's two ends and
  draws the arrow in the tour accent, thicker, with the rest dimmed — "this
  step is this call".
* **The box-pair pattern** — for an arrow that has no id (for instance
  because the board should stay `#!grafli v2`): a stop that frames the two
  boxes alone, `@caller,callee ~iso`, with the caption naming the call.
* **The reader can leave and come back.** During a tour,
  <kbd>g</kbd><kbd>d</kbd> or <kbd>Return</kbd> on a box with a level enters
  it with the tour paused; <kbd>g</kbd><kbd>u</kbd> back resumes at that
  stop. On a selected box, <kbd>g</kbd><kbd>t</kbd> lists the tours with a
  stop framing it (or a box it sits in) — so give every part a tour plays
  through a bookmark that frames it, and the structure and the tours link
  up by themselves.

One tour per question the reader will have ("what happens when …"), each
3–9 stops; a caption says what this stop shows in one or two sentences.

## The ask-on-the-map loop

The map is where the reader asks and where you answer:

* **A `Q:` note on an element is a question to you.** The reader drops it
  next to (or dotted-arrowed to) the part they don't understand.
* **You answer on the map, in one of three ways — never with a paragraph:**
  1. **Deepen the element into a level** — when the answer is "it has parts
     that relate": add `&graph:<name>` and build the sub-board, its question
     being the reader's question.
  2. **One line** — when the answer is a fact: reply in the note as a
     thread (`Q: …\nAI: …`, see "Collaborating on a board" in `SKILL.md`),
     one line; or, when the box has no doc yet, give it one whose first
     sentence is the answer.
  3. **A tour** — when the answer is "it happens in this order": author the
     flow, and reply in the note with one line naming it ("see the tour
     *A blow lands*").
* **Close the loop visibly.** The answered `Q:` shows the thread or the
  pointer; the reader sees the answer on reload without asking in chat.
* **Your own open points go on the map the same way:** a `Q:` note where
  the split is uncertain, a `T:` note where a part is not yet mapped.

If an answer would need a paragraph, the map is missing a level or a tour —
add that instead.

## Overlay files — analysis data with provenance

Analysis data about the subject — tests, findings, recent changes, how well
the reader understood a part — goes into **overlay files** beside the board,
never into the `.grafli`: one `<stem>-res/<name>.overlay.json` per overlay,
keyed by element id (boxes, notes, arrows with `~id=`). The reader presses
<kbd>A</kbd> to cycle off → Connectivity → each overlay → off. The full
schema is in "Overlay files" in `references/format.md`; on a map:

* **Always write the provenance**: `producer` (the script or agent and its
  version that made the data), `created`, and — when the data comes from a
  repo — `source` with the repo and the revision you analysed. The legend
  then marks the overlay **stale** once the repo's `HEAD` moves on.
* **Declare every state as a category**, including "unexamined" or
  "analysis failed"; an element without an entry is drawn as no data.
* **An entry's `note` is one line, its `refs` the evidence** (`@path:line`);
  the legend shows them for the selected element and a click opens a ref.
* Regenerate the file rather than editing it by hand — it is derived data.

## Keeping a map current — marking it stale

A map of code is true at one revision. Record it:

* Put the revision you mapped in a `#` comment at the top of each board
  (`# source: ~/dev/shapes-and-stone @ a1b2c3d`) and in each overlay's
  `source`. The board's refs then resolve against that repo, so write them
  from its root (`@src/Player.qml:88`), never with `../` prefixes.
* `grafli diagnose` warns `stale-source` when the repo's `HEAD` is no longer
  the board's revision, and the app says so when the board opens — that is
  the cue to re-check the map.
* **After the subject changes**, re-check the parts the change touches.
  Update what you verified and the revision; for the parts you could not
  re-check, write a freshness overlay (categories such as `current`,
  `stale`, `unchecked`) so the reader sees with <kbd>A</kbd> where the map
  can no longer be trusted, and add a `T:` note on each stale part.
* Never silently leave a map at an old revision with a new one in its
  comment.

## Checklist before handing over a map

* The top board states the problem, the shape of the answer and the
  layers as stacked full-width containers; its one example case says it
  is an example; mechanisms are a level down.
* Every level has its question note and evidence for its split.
* No level has more than about nine parts; every label is one line.
* Every box doc opens with one sentence that says what the part is.
* Arrows name their relationship kind, with one vocabulary across levels.
* Every part box rests in its layer's palette colour, label and doc line
  at the top; the palette's labels name the layers.
* Every board states its claim in a headline; one or two parts carry
  the emphasis, context is muted, evidence is small and at the edge.
* An order the claim is about is numbered along its path and has a tour
  in the same order.
* Every question the reader will have that is about order has a tour.
* Every `Q:` note is answered with a level, a line or a tour.
* Overlays carry `producer`, `created` and `source`.
* `grafli diagnose` passes on every board, `grafli export --check
  --all-flows` on every board with flows, and `grafli render --lod` reads true zoomed out.
* To share the map with someone without grafli,
  `grafli export-html <board>.grafli <out>.html` writes every reachable
  board, its docs, overlays and tours into one offline page.

## Example — the top board of a code map

The subject is grafli itself. `map-res/palette.json`:

```json
{
  "entries": {
    "export": {"color": "%muted", "label": "Exports"},
    "shell": {"color": "%rose", "label": "App shell"},
    "canvas": {"color": "%soft", "label": "Canvas"},
    "format": {"color": "%highlight", "label": "Format"}
  }
}
```

`map.grafli`:

```
#!grafli v4
# What is grafli for, and what is it made of? — top board of a map of grafli
# source: ~/dev/grafli @ a1b2c3d

@ note problem 0,-260 "Problem: a diagram that an agent and a person both edit, and that still reads like a whiteboard"
@ note answer 0,-200 "Answer: one plain-text file, a canvas that draws and edits it, exports that carry it out" ~small
@ note case 0,-140 "Example, not the scope: one box, API, followed through every layer" ~small

@ box export "Exports" 0,-60 1140x180 %export ^left
@ box render "Render" 30,0 240x90 ^topcenter !flat &graph:render >export
@ box slides "PDF / PPTX" 300,0 240x90 ^topcenter !flat &graph:slides >export
@ box html "HTML page" 570,0 240x90 ^topcenter !flat &doc:html >export
@ note case_export 850,15 "API is a box on a slide" ~small >export

@ box shell "App shell" 0,140 1140x180 %shell ^left
@ box window "Window" 30,200 240x90 ^topcenter !flat &doc:window >shell
@ box stack "Board stack" 300,200 240x90 ^topcenter !flat &graph:stack >shell
@ box autosave "Autosave" 570,200 240x90 ^topcenter !flat &doc:autosave >shell
@ note case_shell 850,215 "Moving API is saved to the file" ~small >shell

@ box canvas "Canvas" 0,340 1140x180 %canvas ^left
@ box items "Items" 30,400 240x90 ^topcenter !flat &graph:items >canvas
@ box edit "Edit modes" 300,400 240x90 ^topcenter !flat &doc:edit >canvas
@ box lod "Zoom levels" 570,400 240x90 ^topcenter !flat &doc:lod >canvas
@ note case_canvas 850,415 "API is drawn and dragged" ~small >canvas

@ box format "Format" 0,540 1140x180 %format ^left
@ box parser "Parser" 30,600 240x90 ^topcenter !flat &graph:parser >format
@ box writer "Writer" 300,600 240x90 ^topcenter !flat &doc:writer >format
@ box vault "Resource vault" 570,600 240x90 ^topcenter !flat &doc:vault >format
@ note case_format 850,615 "API is one line: @ box api …" ~small >format

@ note evidence 0,760 """
code:
split by the modules that own each layer
  @grafli/format.py
  @grafli/view/
  @grafli/app.py
  @grafli/pdfexport.py
""" ~small
```

The problem and the shape of the answer come first; the four layers are
stacked full-width containers in their palette colours, the name on the
left; one box, `API`, is followed through every layer and the board says
it is an example; how parsing, items, the board stack and rendering work
is a level down (`&graph`), what a part is a doc away (`&doc`). Zoomed out
(`grafli render --lod map.grafli out.png`) the board is four named bands.

## Example — a slide-grade level

The `Parser` box of the top board above, one level down. It uses the
same `map-res/palette.json`; `map-res/parser.grafli`:

```
#!grafli v4
# One parse feeds every view — the Parser level of the map of grafli
# source: ~/dev/grafli @ a1b2c3d

@ note claim 0,-200 "One parse feeds every view: the canvas and every export draw the same Board" ~xlarge !sans !bold !flat
@ note question 0,-140 "How does a line of text become what every view draws?" ~small

@ box file ".grafli file" 0,0 180x90 %format ^topcenter *lead:solid-1 &doc:file
@ box parse "parse()" 320,0 180x90 %format ^topcenter *lead:solid-2 &doc:parse
@ box writer "serialize()" 320,170 180x70 ~small &doc:writer
@ box board "Board" 640,-40 260x260 %primary !card !ink !sans *lead:solid-3
@ box boxes "Boxes" 670,30 200x40 !flat >board
@ box notes "Notes" 670,90 200x40 !flat >board
@ box arrows "Arrows" 670,150 200x40 !flat >board

@ box app "In the app" 1020,-40 240x36 %canvas !ink !sans
@ box canvas "Canvas" 1020,10 240x80 %canvas ^topcenter *lead:solid-4 &doc:canvas ~status=live
@ box out "Outside the app" 1020,130 240x36 %export !ink !sans
@ box render "render" 1020,180 240x60 %export ^topcenter &doc:render ~status=snapshot
@ box slides "PDF / PPTX" 1020,260 240x60 %export ^topcenter &doc:slides ~status=snapshot
@ box html "HTML page" 1020,340 240x60 %export ^topcenter &doc:html ~status=snapshot

@ arrow file -> parse "data: text" ~id=read
@ arrow parse -> board "data: Board" ~id=build
@ arrow board -> canvas %canvas !dot ~from=right ~to=left ~id=draw
@ arrow board -> render %export !dot ~from=right ~to=left
@ arrow board -> slides %export !dot ~from=right ~to=left
@ arrow board -> html %export !dot ~from=right ~to=left
@ arrow board -> writer %muted !thin
@ arrow writer -> file %muted !thin

@ note evidence 0,460 """
code:
split by where the Board is made and read
  @grafli/format.py:915
  @grafli/format.py:1505
  @grafli/view/selection.py:263
  @grafli/app.py:1915
  @grafli/app.py:2202
""" ~small

@ bookmark b_read "The file" @read "The board is one plain-text file; parse() reads it line by line."
@ bookmark b_build "One Board" @build "parse() builds one Board: its boxes, notes and arrows."
@ bookmark b_draw "Drawn" @draw "The canvas draws that Board; render and the exports read the same one."
@ flow parse_path "From text to the canvas" b_read b_build b_draw
```

The headline states the claim, the question note sits under it. `Board`
is the one emphasis — a `!card`, so it stays a node while it shows its
inner parts — and the numbers 1–4 walk the path the tour plays arrow by arrow. The two
category bars head their columns, and each connector into a column takes
the bar's colour. `serialize()` is muted context, the evidence note is
small at the bottom edge, and the status pills say which view follows
the file live. `grafli diagnose --strict` passes on it.

## Example — a mechanism, one level down

`fight-res/palette.json`:

```json
{
  "entries": {
    "actors": {"color": "%soft", "label": "Actors"},
    "rules": {"color": "%highlight", "label": "Game rules"},
    "view": {"color": "%rose", "label": "Presentation"}
  }
}
```

`fight.grafli`:

```
#!grafli v4
# How does a blow reach the camera? — Shapes & Stone fight path
# source: ~/dev/gamedev/shapes-and-stone @ a1b2c3d

@ note question 0,-120 "How does a blow reach the camera?" ~small
@ box enemy "Enemy lunge" 0,0 200x80 %actors ^topcenter &doc:enemy
@ box player "Player.takeDamage" 380,0 220x80 %actors ^topcenter &doc:player
@ box impact "impact()" 800,0 260x160 %rules ^topcenter &graph:impact
@ box camera "Camera" 1240,0 200x80 %view ^topcenter &doc:camera
@ note evidence 380,240 """
code:
split by the files that own each step
  @src/Enemy.qml:120
  @src/Player.qml:88
  @src/Game.qml:2233
""" ~small
@ arrow enemy -> player "call: hit(dmg)" ~id=hit
@ arrow player -> impact "call: impact()" ~id=apply
@ arrow impact -> camera "event: shake" ~id=shake

@ bookmark b_hit "The hit" @hit "The lunge calls the player's hit handler with the damage."
@ bookmark b_apply "Applying it" @apply "takeDamage hands the blow to the game's impact routine."
@ bookmark b_inside "Inside impact()" @impact "impact() runs hit-stop, the network message and the camera kick."
@ bookmark b_shake "The shake" @shake "impact() signals the camera to shake."
@ flow blow "A blow lands" b_hit b_apply b_inside b_shake
```

Each `&doc` file starts with the one sentence the canvas shows; `impact`
gets a level because its three effects relate; the evidence note backs the
split; the tour walks the call chain as arrow stops; each box rests in its
layer's colour, and the `impact` sub-board uses the same palette entries.

A complete map in three levels — box docs, deep links, a tour across the
levels, a resting colour per layer and a generated overlay — ships as
`examples/navigation-map.grafli` in the grafli repository.
