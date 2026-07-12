# Thinking boards — structure a problem, not a system

A thinking board's output is different from a diagram's: it helps the
**human think** when they look at it. You are not documenting something
that exists — you are giving an open problem a shape the eye can work
on. Trigger phrases: "help me think through X", "let's weigh the
options", "map out the unknowns", "should we do A or B".

Two rules override your normal instincts on every thinking board; the
patterns below build on them.

## Rule 1 — deliberate incompleteness

An agent that fills every corner forecloses the human's thinking. On a
thinking board, unfinished is a feature:

* **Seed structure, don't complete it.** Lay out the frame (the poles,
  the options, the question) and a first pass of content — then stop.
* **Leave labeled empty space.** An empty container titled "what's
  missing here?" or an option column with only a heading is an
  invitation; a fully filled board is a verdict.
* **Pose questions instead of answering ones not yet asked.** A `Q:`
  note where you'd normally write a conclusion keeps the decision with
  the human.
* **Stop at the skeleton unless asked to elaborate.** Depth arrives via
  Rule 2, on demand.

## Rule 2 — progressive elaboration

Start with a **≤7-node core**. Deepen only where the human pulls:

* A `T:` note the human drops on a node means "go deeper here" — expand
  that node (pros/cons note, evidence, a sub-board), then clear the task.
* Moves the human makes are signals: a box dragged toward a pole is a
  stance; two options dragged together are being compared; an enlarged
  node matters more now. Read positions before adding anything.
* Use the depth ladder (`references/design.md`): label → note → `&doc`
  → `&graph`. The top view of a thinking board stays one glance wide.

## Pattern: decision board

The question is the title. One column per option; criteria as a row of
short notes; a status note tracks the state.

```
@ note title 300,-80 "Which queue backs order events?" ~xxlarge
@ note status 1050,-70 "status: open" %clay !bold

@ box opt_a "Kafka" 0,60 300x620 %muted ^topleft ~large !flat
@ note a_pro 20,140 """
md:
**For**
- replay + retention give us audit for free
- team ran it before
""" ~small ~width=40 >opt_a
@ note a_con 20,340 """
md:
**Against**
- heaviest ops footprint of the three
""" ~small ~width=40 >opt_a

@ box opt_b "SQS" 350,60 300x620 %muted ^topleft ~large !flat
@ note b_pro 370,140 """
md:
**For**
- zero ops, pay-as-you-go
""" ~small ~width=40 >opt_b

@ box opt_c "Redis Streams" 700,60 300x620 %muted ^topleft ~large !flat

@ note crit 0,740 "criteria: ops burden - replay - cost at 10x - team skills" !italic
@ note q1 1050,140 "Q: is replay a hard requirement or nice-to-have?" ~width=32
@ arrow q1 -> opt_a !dotted
```

Note what's *not* filled in: SQS has no "against" yet, Redis Streams is
an empty column, the status is open. When the human decides, the status
note flips to `decided: <option>` and goes `!bold`; the losing columns
stay on the board — they're the record of what was considered. This maps
directly onto an ADR when the decision lands.

## Pattern: tension map

Two poles; options placed **spatially between them** — position *is* the
data. This uses the canvas's unique property (no auto-layout means every
x-coordinate is a statement) for what it's best at.

```
@ note title 250,-80 "How much to invest in the editor?" ~xxlarge
@ box pole_a "Ship fast" 0,100 200x80 %clay !bold
@ box pole_b "Build to last" 1200,100 200x80 %teal !bold
@ arrow pole_a -- pole_b

@ box o1 "patch the parser" 260,240 220x70 %soft
@ box o2 "extract a module" 640,240 220x70 %soft
@ box o3 "own package + API" 980,240 220x70 %soft

@ note inv 300,380 "drag an option left or right to take a stance - position is the point" !italic
```

The human thinks by *dragging* — and where they leave a box tells you
their stance without a word. Re-read positions before summarising.

## Pattern: question landscape

The investigation itself, as a board: central question, sub-questions
radiating, colored by state. The board *is* the status of the inquiry.

* Center: the driving question (`*lightbulb` fill symbol works well).
* Satellites: one box per sub-question — `%clay` open, `%teal`
  answered, `%muted` blocked/parked.
* An answered sub-question gets its answer as a threaded discussion
  note (`Q:` line + your `AI:` reply) anchored next to it; evidence
  attaches via `&doc:`/`&link:`.
* New sub-questions appear as the inquiry moves — append, don't reflow.

## Pattern: assumption / evidence board

Make the claims load-bearing and inspectable:

* One box per **claim**; a `code:` note beside it with `assert` for the
  claim, `risk` for what breaks if it's wrong.
* Dashed `verify:` arrows from evidence nodes (tests, measurements,
  documents via `&doc:`/`&link:`) to the claims they support.
* A claim with no incoming `verify:` arrow is visibly unsupported —
  that gap *is* the board's message. Don't paper over it; flag it with
  a `Q:` note asking for evidence or a decision to accept the risk.

## Working the session

A thinking board is a live collaboration surface (the etiquette in the
core applies). The loop that works: you seed the skeleton → the human
rearranges, drops `T:`/`Q:` notes → you elaborate exactly where pulled,
answer inline as threads, and keep your additions anchored to what they
concern. Never resolve the question yourself — when a decision falls
out, record it (status note, `!bold`), and offer to distill the board
into the durable artifact it earned: an ADR, a plan, a `&doc` summary.
