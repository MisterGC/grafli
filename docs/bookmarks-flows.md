# Bookmarks & flows

Big diagrams are hard to take in all at once. **Bookmarks** save labeled
viewpoints of a graph; **flows** string them into a guided tour you can step
through, auto-play, present fullscreen, or export as a PDF. They live inside
the `.grafli` file, so they version, diff, and travel with the diagram — and
an AI can author them as plain text.

## Concepts

- A **bookmark** is a named viewpoint: a label, an optional description, and
  a *semantic anchor* — the item ids it frames. The actual pan/zoom is
  computed at display time by fitting those items, so a bookmark stays correct
  when you move boxes around.
- A **flow** is an ordered list of bookmark references, each with an optional
  auto-play dwell time. One bookmark can appear in several flows.

Both are written into the file (which bumps the header to `v2`). See the
[file format](format.md#bookmarks-and-flows-v2) for the exact syntax.

## Capturing bookmarks

| Key | Action |
|-----|--------|
| <kbd>g</kbd><kbd>b</kbd> | Bookmark **what's shown** — anchors to the selection, else everything visible. Falls back to the exact viewport if nothing is on screen, so it never fails. |
| <kbd>g</kbd><kbd>B</kbd> | Bookmark the **exact viewport** — a hand-tuned framing reproduced pixel-faithfully. |
| <kbd>g</kbd><kbd>f</kbd> | Start / stop **flow recording** — each capture while recording is appended to the flow. |

On capture a blue frame briefly flashes around what the bookmark anchors, so
you can confirm it grabbed the right region. Notes are valid anchors, so a
node-less, note-only bookmark works too.

### Scoping a step to a selection

With an explicit **selection**, <kbd>g</kbd><kbd>b</kbd> scopes the step to
exactly those items: the thumbnail and the exported PDF render **only** the
selected items (and the arrows between them), not everything inside the framed
region. So you can show a single child of a parent without the parent and its
siblings bleeding in. No selection keeps the default "everything visible"
framing. The capture badge confirms the scope (e.g. *scoped: 1 item*).

### Text slides (clickable links)

Select a **single text note** and capture it with **no description**, and that
step becomes a **text slide**: the note's Markdown is rendered in the PDF as
real, selectable text with **clickable links** — not a flattened image. Use it
to author link-rich slides straight from the graph. The text reflows to the
slide width and shrinks to fit one page, so it reads as a slide rather than a
screenshot of the note. The capture badge says *text slide*, and the step's
card in the Flows tab is marked **text**. Add a description (or scope to more
than the one note) and it reverts to a normal diagram slide.

## The Flows tab

Toggle the side panel with <kbd>\\</kbd> and switch to the **Flows** tab. Flows
and the bookmarks list are collapsible (collapsed by default). Each entry is a
small slide-style card showing a live thumbnail of what it frames.

- **Click a card** to select it — the canvas flies there, and the card is
  highlighted.
- **Edit inline** — click the title or description to edit them in place;
  changes save on <kbd>Enter</kbd> / focus-out.
- When a step is selected, controls appear: reorder (<kbd>↑</kbd>/<kbd>↓</kbd>),
  remove (<kbd>✕</kbd>), and a **Dwell** field (auto-play seconds; blank uses
  the flow default).
- **Add a stop**: expand a flow and either pick a bookmark from the *add*
  dropdown, or select a step and press <kbd>g</kbd><kbd>b</kbd> while
  navigating — the new bookmark is inserted right after the selected step.
- **Rename a flow**: click the flow's title in its header band and type — it
  commits on <kbd>Enter</kbd> / focus-out. Clicking elsewhere on the band still
  expands/collapses it.
- **Flow description** (Markdown): expand a flow and edit the *Description*
  field below its header. It renders below the headline on the exported title
  slide, so it can carry emphasis, lists, and clickable links.
- **Footer** (Markdown, optional): the *Footer* field — shown when a flow is
  expanded — is **board-global** (one per `.grafli` file, shared by every
  flow). It renders as a small muted branding line at the bottom of every
  exported **content** slide (the title slide stays a clean cover); leave it
  empty for no footer.
- **Title background** (board-global): the *Title background* dropdown chooses
  the export title slide's backdrop — **Empty** (default) or **Thumbnail art**,
  a faint, procedurally-scattered collage of the flow's own slide thumbnails
  that fades to paper behind the title so the text stays crisp. The layout is
  seeded from the flow, so re-exports look identical.
- **Export this flow**: when a flow is expanded, an export (PDF) icon appears
  in its header next to ▶ and 🗑 — it exports that flow directly, skipping the
  flow picker.

## Auto-generated flows

If your diagram already encodes a path through arrows, you don't have to capture
each stop by hand. Select a start node and grafli can **walk the graph for you**,
one slide per node:

- **Generate**: select the start node, then press <kbd>g</kbd><kbd>F</kbd> (or use
  **＋ Auto-flow from selection** in the Flows tab). grafli follows the forward
  arrows, making one isolated step per node — a box becomes a titled focused
  diagram, a note becomes a [text slide](#text-slides-clickable-links), and a
  parent node expands to show its whole subtree.
- **Strict-forward only**: it follows an arrow only when its head points away
  from the current node and there's exactly **one** such arrow. It stops at the
  end of a chain, and when a node **forks** (several forward arrows) it stops
  there and tells you where — it never guesses a branch. Plain (`--`) and
  bidirectional (`<->`) connectors are not followed.
- **Re-generate**: the flow remembers its start node, so after you edit the
  diagram press the **↻** icon on the flow's header to rewrite the steps from
  scratch. Your **title page is kept** — the flow's name and description (and the
  board-global footer) survive; only the steps are regenerated.

!!! note "Notes as graph nodes"
    An arrow touching a note defaults to an *annotation* link (muted, "just
    extra text"), which auto-flow skips. Promote a connector to a **graph edge**
    — select it and press <kbd>s</kbd> then <kbd>a</kbd> — to make that note a
    first-class node that auto-flow and graph-nav follow. Once you promote one,
    new note connectors default to graph too, so a chain of connected notes
    becomes a flow. (Images aren't connectable yet — that's the next step.)

## Playback

Launch a flow with the ▶ button on its header (or present it, below). During
playback an on-canvas caption shows the current stop and its description.

| Key | Action |
|-----|--------|
| <kbd>Space</kbd> / <kbd>→</kbd> | Next stop |
| <kbd>←</kbd> | Previous stop |
| <kbd>t</kbd> | Toggle **smooth** camera ↔ **instant** cuts (flip mid-flow to step quickly, then settle) |
| <kbd>p</kbd> | Cycle **paused → playing → playing (loop)** — looping wraps to the first stop |
| <kbd>Esc</kbd> | Exit playback |

## Present mode

Press <kbd>F5</kbd> to present the current flow like a slide deck: all chrome
hides, the app goes fullscreen, and the flow opens on its first stop, paused.
Drive it with the keys above; <kbd>p</kbd> set to *loop* makes an unattended
booth screen. <kbd>Esc</kbd> exits and restores the editor.

## Export to PDF

Export a flow as a slide-style PDF — a title slide (with the flow's Markdown
description) followed by one slide per stop. Text is sized for *reading*, not
for maximal fill: a comfortable presentation body that grows to fill a sparse
slide but never balloons, and shrinks on a dense one only down to a legible
floor.

- **In the app**: the export (PDF) icon on an expanded flow's header (exports
  that flow), or the **Flow PDF** button in the side panel's Export section
  (prompts for a flow when there is more than one).
- **Headless / scripted**:

```bash
grafli export diagram.grafli tour.pdf --flow tour
```

`--flow` is optional when the file has a single flow.

### Composing slides

A slide is not a flat screenshot — the diagram is rasterized, but every **note
is redrawn as real, selectable text in place**, so links stay clickable and the
text is searchable. You can combine a diagram and prose on one slide and keep
both faithful: the note sits exactly where you drew it, with its arrows still
meeting it.

- **Container = slide.** To make a multi-element slide with a title, bundle the
  elements in a **container** (a parent box) and scope the step to it. The
  container's label becomes the slide title and its own border/fill are dropped
  — the container *is* the slide frame, so its contents fill the slide cleanly.
  No container and no manual label? The slide is untitled and the content speaks
  for itself (a note that leads with a `#` heading already reads as a title).
- **Slide-frame ratio.** Shape a container to the export aspect ratio so its
  contents fill the page without letterboxing: select it and press
  <kbd>d</kbd> then <kbd>r</kbd> (or the **Slide ratio** action in the side
  panel). It holds the width and sets the height to the slide ratio (accounting
  for the footer), works on a multi-selection, and is **re-applicable** — drag
  in too much and the box grows; press <kbd>d</kbd> <kbd>r</kbd> again to snap
  it back, and the overflow that spills past the frame is your cue to trim the
  text or split it across two notes/slides.
- **Description floats.** A step's description renders as a floating caption card
  over the slide (Markdown, clickable links) — exactly like the on-canvas
  playback caption — so it never steals space from the diagram.
- **Single-note steps** still become a full **text slide** (see *Text slides*
  above), and the board-global Markdown **footer**, if set, brands every content
  slide.
- **Overload warning.** If a slide's text overflows even at the legible floor,
  or an in-place note ends up too small to read, the export reports it (status
  line in the app, a warning line on the CLI) naming the slides to fix — an
  overloaded slide is hard for an audience anyway.

## Authoring flows with AI

Because bookmarks and flows are plain text with semantic anchors, an AI can
write an explanatory tour directly — start wide, zoom to the entry point,
follow the call chain, end on the data layer — and the per-stop descriptions
become both the on-canvas captions and the narration. See
[Pair with your AI](ai.md).
