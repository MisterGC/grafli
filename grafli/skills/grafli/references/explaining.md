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
  next level, with its own question. The box then shows a miniature of the
  sub-board once it is large enough on screen; size such a box wider and
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
  `source`.
* **After the subject changes**, re-check the parts the change touches.
  Update what you verified and the revision; for the parts you could not
  re-check, write a freshness overlay (categories such as `current`,
  `stale`, `unchecked`) so the reader sees with <kbd>A</kbd> where the map
  can no longer be trusted, and add a `T:` note on each stale part.
* Never silently leave a map at an old revision with a new one in its
  comment.

## Checklist before handing over a map

* Every level has its question note and evidence for its split.
* No level has more than about nine parts; every label is one line.
* Every box doc opens with one sentence that says what the part is.
* Arrows name their relationship kind, with one vocabulary across levels.
* Every question the reader will have that is about order has a tour.
* Every `Q:` note is answered with a level, a line or a tour.
* Overlays carry `producer`, `created` and `source`.
* `grafli diagnose` passes on every board, `grafli export --check` on
  every board with flows, and `grafli render --lod` reads true zoomed out.
* To share the map with someone without grafli,
  `grafli export-html <board>.grafli <out>.html` writes every reachable
  board, its docs, overlays and tours into one offline page.

## Example — the top level of a code map

```
#!grafli v3
# How does a blow reach the camera? — Shapes & Stone fight path
# source: ~/dev/gamedev/shapes-and-stone @ a1b2c3d

@ note question 0,-120 "How does a blow reach the camera?" ~small
@ box enemy "Enemy lunge" 0,0 200x80 &doc:enemy
@ box player "Player.takeDamage" 380,0 220x80 &doc:player
@ box impact "impact()" 800,0 260x160 &graph:impact
@ box camera "Camera" 1240,0 200x80 &doc:camera
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
split; the tour walks the call chain as arrow stops.
