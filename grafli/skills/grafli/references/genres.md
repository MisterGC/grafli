# Genre playbooks — sketchnote, infographic, software diagrams

One rule stands above everything in this file: **a good grafli makes the
reader get it from the picture.** Text may accompany for detail — it is
never the medium. If your draft only works when the reader reads every box,
it isn't done.

The second rule: **constraint is the feature.** Each genre below has a
*closed* feature palette. Stay inside it. When something seems
inexpressible, find a recipe within the boundaries (size, position, color,
symbols, numbers) before wishing for a new feature — the boundaries are
what keep boards instantly readable.

Picking the genre:

| You are making… | Genre |
|---|---|
| a memory page for a talk, workshop, book chapter | **Sketchnote** |
| one claim/subject explained visually to a general audience | **Infographic** |
| an answer to an engineering question about a system | **Software diagram** |

Each playbook has the same spine: the job → layout archetypes → feature
palette (use/avoid) → expert review → exemplar.

---

## Sketchnote — capture a talk so it's remembered

### The job (the 10-second read)

Weeks later, a glance at the page brings back the talk: the thesis (title),
3–5 takeaways, and the one thing to act on. Optimise for **recall**, not
completeness — if you're transcribing, you're not sketchnoting.

### Layout archetypes

1. **Banner + sections** — a display-lettered title band, 2–4 lettered
   section columns (WHY / HOW / …), a takeaway band at the bottom. The
   default for structured talks. (See the exemplar.)
2. **Center-out map** — the thesis as a big fill-symbol node in the middle,
   takeaways radiating outward. For idea talks without a linear arc.
3. **The numbered loop/arc** — when the talk *is* a process, make the
   process the centerpiece: boxes in a cycle or arc, `*badge:1…n` carrying
   the order.

### Feature palette

| Use | Avoid |
|---|---|
| display lettering: `~2xl`…`~4xl` `!flat` notes with `!bold` `!shadow` / `!outline` for title + section headers | containers as structure (at most one lane, e.g. a practices list) |
| fill symbols (`*person`, `*brain`, `*plant`…) for concepts that ARE iconic — caption ≤ 2 words | `code:` notes (unless the talk was about code) |
| `*lead:` on every headline point — the memory hook | arrow webs; more than ~6 arrows total |
| `*badge:` emphasis (star/flame/heart) and number badges for order | uniform grids of same-size boxes — size IS the memory cue |
| handwritten notes, one `md:` quote, one `md:` checklist | paragraphs in boxes; >25 elements on the page |
| 3–4 colors: neutral field + 1–2 accents + one highlight | a fifth color |
| a v2 `@ flow` tour to replay the page section by section | |

### Review as a master sketchnoter

Persona: you summarize dozens of talks a year; your pages get shared more
than the slides. Ask, in order:

1. **Cover test** — do the title and the biggest elements alone state the
   talk's thesis?
2. **Count test** — 3–5 takeaways, each ownable at a glance? (More: cut.)
3. **Squint test** — blur the text; does hierarchy survive on size, color
   and symbols alone?
4. **Hook test** — does every takeaway carry exactly one memory hook
   (symbol, number, or color)? Orphan text boxes fail.
5. **Arc test** — is the reading order obvious with no instructions?

Pass bar: *would you pin it to your wall and share it after the
conference?* Fix the first failing test and re-render; don't polish past
two rounds — sketchnotes want personality over perfection.

### Exemplar

`examples/sketchnote-demo.grafli` — banner + sections + numbered loop, with
a guided `tour` flow.

---

## Infographic — one claim, made visible

### The job (the 10-second read)

A general audience gets the **"so what" of one claim** in a glance and can
verify it in a minute. Numbers are the heroes; pictures make them
comparable; words only caption.

### Layout archetypes

1. **Hero number + breakdown** — one display-size number/fact on top,
   locked up with the claim on a shared baseline, a panel row beneath that
   decomposes or evidences it. Inside panels, numbers dominate: give count
   boxes short number-first labels at `~large` ("20 semantic") and put the
   descriptor in a small note beneath — a label has one font size, so split
   number and descriptor across elements.
2. **Comparison panel** — two/three labeled columns (A vs B), same
   sub-structure per column so differences pop.
3. **"How it works in N steps"** — a single left-to-right or top-down strip
   of numbered stages (`*badge:1…n`), one pictogram per stage.

### Feature palette

| Use | Avoid |
|---|---|
| one hero fact at `~3xl`/`~4xl` — the claim, or the number that proves it | charts, axes, fake precision — grafli is not a plotting tool; use relative box size + the printed number |
| **size encodes magnitude**: box area tracks the value it represents | rainbow palettes; color without a meaning |
| fill symbols as pictograms — illustrate the category, don't decorate | arrows outside the how-it-works strip |
| number badges for steps and rankings | dense prose; more than one `md:` note |
| `!flat` containers as aligned panels — the grid IS the design | mixing archetypes on one page |
| color = category, applied identically in every panel | display lettering on more than title + panel headers |
| `@ footer` for the source/method attribution | |

### Review as an illustrator

Persona: an editorial illustrator; your infographics run where readers give
you three seconds before turning the page.

1. **So-what test** — one glance = one claim, sayable in one sentence?
2. **Size-honesty test** — do visual size differences match the numbers?
   (A 2× value must not read as 5×.)
3. **Pictogram test** — does every symbol illustrate its datum? Decoration
   fails.
4. **Grid test** — panels aligned, gutters even, nothing floats?
5. **Caption ratio** — numbers big, words few; could a caption be cut?

Pass bar: *would a stranger re-share it without the article?*

### Exemplar

`examples/infographic-demo.grafli`.

---

## Software diagrams — answer one engineering question

### The job (the 10-second read)

Every board answers **one question** — and the *shape of the graph* carries
the answer: a new team member gets the structure before reading a single
label in detail. Text is labels plus depth-on-demand (`code:` notes,
`&doc`, `&graph`) — never paragraphs on the canvas.

State the question in the title comment; if you can't, split the board.

Two rules that keep exemplar quality: the board never explains grafli
itself — authoring commentary lives in `#` comments, which don't render;
and when two same-row nodes feed one target, stagger their heights half a
step so neither arrow crosses the other's box.

### Pick the arrows by the question

A system has more relations than a board can carry. Each recipe below
says which of them become arrows: the ones its question asks about.
Every other relation still true of a box goes into that box's doc line
— the first sentence of its `&doc`, shown on one line under the label —
or is left out. An arrow that does not help answer the question is
noise, however true it is.

Each recipe also names the generic features it uses, so a person can
follow it by hand: containers, colours, icons, doc lines and arrows are
the same whether an agent or a human draws them.

### Sub-recipes

**Architecture** — *what exists and who talks to whom.*
Arrows: the relations the claim rests on — for "every write lands
through one merge", the paths a write takes and nothing else. A
relation the question does not ask about (who renders, who keeps
presence, who writes a config file) is a sentence in the doc line of
the box it belongs to. Uses:
* **layers as containers, their titles as headings** — one full-width
  `^topleft ~large !flat` container per layer, top to bottom; the
  title names the layer ("Who edits", "On disk"), so no separate
  heading note is needed;
* **kinds from the palette** — each kind of thing (a process of
  yours, a browser tab, a tool that is not yours, a file) is one
  entry in `<stem>-res/palette.json` with its colour, icon and
  outline; a box takes its kind with `%<kind>` and repeats nothing
  else (see "Map palette" in `references/format.md`);
* **the legend** — the palette's labels are the key; `grafli render
  --legend` (and `Shift+M` in the app) draws it, so write each label
  for a reader ("not grafli's: the presenter's session"), never a
  hand-drawn key note;
* **doc lines for secondary relations** — keep each first sentence
  short enough to fit the box whole (about 35 characters on a
  340-wide box): a sentence that does not fit is not drawn;
* every arrow labelled with a semantic prefix (`call:`, `data:`,
  `event:`) and its cardinality where it matters (`N tabs → edit
  ops`); the claim's arrow `!thick`, its box `!bold`;
* 5–9 boxes per level, deeper detail in `&graph` sub-boards; it must
  still read true zoomed out.

**State machine** — *which states can it be in, and what moves it.*
Arrows: every transition, the error and retry ones too — leaving one
out makes the machine wrong, not simpler. Uses the state-machine
encoding in `references/design.md`: transitions labelled `event
[guard] / action`, `!round` start dot and end states, self-loops for
transitions that stay, the main path left to right.

**Behavioral** — *what happens when.*
Arrows: the steps of one scenario, in causal order; nothing that is
true but not part of this run. Uses: left-to-right placement, the entry
point visually first; actors as boxes of a kind (`*lead:person`,
`*lead:robot`, best set on a palette entry); happy path solid,
alternates `!dashed`; a single `code:` note for the one non-obvious
algorithm; number badges when steps are discussed by number.

**Design** — *how it's built: modules, types, responsibilities.*
Arrows: dependency direction only; composition is nesting, not an
arrow. Uses: boxes that name modules/types (identifier in the label,
role in the box's doc line); if everything connects to everything you
are at the wrong altitude — go up one level or split. When proposing a
change, the diff convention: unchanged `%muted`, modified one accent,
new a second accent — and nothing else.

### Feature palette

| Use | Avoid |
|---|---|
| containers as layers, their `^topleft ~large` titles as headings | display lettering, `!shadow`/`!outline` |
| **icons encode kind**: one `*lead:` icon per kind of thing, set on the kind's palette entry and named by the legend | icons as decoration — an icon that encodes no kind, two kinds sharing one icon, fill symbols |
| palette kinds (colour + icon + outline) and `--legend` instead of a hand-drawn key | emphasis badges — a `*lead:warning` on a genuinely risky node is the ceiling |
| semantic edge prefixes + labels on every non-obvious arrow | an arrow for a relation the question doesn't ask about — it goes into a doc line |
| a box's doc line (`&doc` first sentence) for secondary relations; `&graph` for depth | handwritten flourish — restraint IS this genre |
| ≤4 colours, each encoding exactly one thing (kind, layer, status, diff) | duplicated nodes to dodge a crossing — fix the layout instead |
| `code:` / `md:` notes adjacent to nodes for depth (`~small` when they sit in a row); bookmarks + flows for walkthroughs | |
| `path:line` references in notes and docs where truth matters | |

The sketchnote and infographic playbooks keep their own rules: there a
symbol may illustrate a concept; here an icon only ever says what kind
of thing a box is.

### Review as a software architect

Persona: you review design docs for a living; you distrust any diagram you
can't falsify against the code.

1. **Question test** — can you state the one question this board answers?
   Is it the title?
2. **Onion test** — zoomed out (LoD / squint), is the layer story still
   true?
3. **Edge test** — is every arrow's meaning unambiguous from its label or
   prefix, and does every arrow help answer the question? A true but
   off-question relation belongs in a doc line.
4. **Altitude test** — 5–9 elements per level, everything deeper pushed
   into notes or sub-boards?
5. **Kind test** — does every icon and outline stand for a kind the
   legend names, and does every box of a kind carry it?
6. **Truth test** — do names and references match the code right now, and
   is at least one `path:line` anchor present where the diagram makes a
   verifiable claim?

Pass bar: *would you sign off a design review on the strength of this
board?*

### Exemplars

`examples/live-session.grafli` (architecture: layers as headings,
palette kinds with icons, the legend, doc lines for the secondary
relations — render it with `--legend`),
`examples/architecture.grafli` (architecture: semantic edges, a `code:`
note and a `&graph` sub-board),
`examples/oauth-callback.grafli` (behavioral). The state-machine
snippet in `references/design.md` is the state-machine exemplar.
