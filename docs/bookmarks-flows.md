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

Export a flow as a slide-style PDF — a title slide followed by one slide per
stop (label, the framed diagram, and the description).

- **In the app**: the **Flow PDF** button in the side panel's Export section.
- **Headless / scripted**:

```bash
grafli export diagram.grafli tour.pdf --flow tour
```

`--flow` is optional when the file has a single flow.

## Authoring flows with AI

Because bookmarks and flows are plain text with semantic anchors, an AI can
write an explanatory tour directly — start wide, zoom to the entry point,
follow the call chain, end on the data layer — and the per-stop descriptions
become both the on-canvas captions and the narration. See
[Pair with your AI](ai.md).
