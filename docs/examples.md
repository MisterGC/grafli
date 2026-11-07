# Examples

The grafli source tree ships an [`examples/`](https://github.com/MisterGC/grafli/tree/main/examples)
directory with `.grafli` files you can open and explore.

## Architecture demo

`examples/architecture.grafli` exercises the full feature surface in a
single diagram:

- Visible nesting containers for layered architecture (frontend, API,
  core, data, observability)
- Semantic edge labels (`call:`, `data:`, `event:`, `state:`, `verify:`,
  `risk:`)
- Code-mode notes attached to specific services
- Tasks (`T:`), questions (`Q:`), and discussion notes
- A linked markdown resource (`examples/architecture-res/graphql.md`)

Open it from a clone:

```bash
git clone https://github.com/MisterGC/grafli.git
grafli grafli/examples/architecture.grafli
```

## Bookmarks & flows demo

`examples/flows-demo.grafli` is a small six-service architecture wired up with
**bookmarks** and two **flows** — a guided tour through the system and a
security-path walkthrough. Open it, toggle the side panel with <kbd>\\</kbd>,
switch to the **Flows** tab, and play a flow; press <kbd>F5</kbd> to present one
fullscreen, or export it to a slide PDF:

```bash
grafli export grafli/examples/flows-demo.grafli tour.pdf --flow tour
```

See [Bookmarks & flows](bookmarks-flows.md) for the full feature.

## Presentation settings demo

`examples/presentation-demo.grafli` shows the
[per-stop detail & focus settings](bookmarks-flows.md#per-stop-detail--focus)
in one flow: the flow pins `~detail=full` as its default, the wide opening
stop overrides it with `detail=summary` (both containers fold to headline
tiles), and the closing stop repeats the previous framing with
`focus=complete` — everything the frame clips fades, while a fully framed
note stays crisp. The captions are written near the 280-character budget so
you can see them wrap in full during playback.

Play the `showcase` flow in the app, or verify single stops headless:

```bash
grafli render grafli/examples/presentation-demo.grafli /tmp/stop.png --step showcase:2
grafli render grafli/examples/presentation-demo.grafli /tmp/stop.png --step showcase:5
```

## Explanation map demo

`examples/navigation-map.grafli` is a map you read level by level: grafli's
own path from <kbd>Return</kbd> on a box to the board behind it. Its boxes
rest in one colour per layer of grafli — format, canvas, app shell, exports —
from `navigation-map-res/palette.json`, the same on every level;
<kbd>Shift</kbd>+<kbd>M</kbd> shows the legend. Select
**Open dispatch** and press <kbd>g</kbd><kbd>d</kbd> to zoom into its level,
again on **_enter_board** to reach the algorithm and its source refs, and
<kbd>g</kbd><kbd>u</kbd> to come back out. <kbd>g</kbd><kbd>v</kbd> peeks at a
box's doc, the `enter` tour crosses all three levels, and <kbd>A</kbd> cycles
to the **Tests** overlay, which `examples/navigation-map-overlay.py` writes.
To share it with someone without grafli:

```bash
grafli export-html grafli/examples/navigation-map.grafli map.html
```

## Slide-grade map demo

`examples/layers-map.grafli` explains grafli's own layers — format, view,
exports — the way a slide would: a claim first, then the layers as a stack
of bands in their colours from `layers-map-res/palette.json`, drawn as
layered dependencies. Every arrow points at what a part depends on and is
named for what it reads or draws; the one that points up the stack — the
view asking the PDF export for its slide shape — is drawn in rose, and the
claim says so. Select **Parser** or
**PDF / PPTX** and press <kbd>g</kbd><kbd>d</kbd> for a level with a claim
headline, one emphasised part, a numbered path and status labels (`live`
in the app, `snapshot` outside it); <kbd>Shift</kbd>+<kbd>M</kbd>
shows the legend and <kbd>A</kbd> cycles to the **Tests** overlay, which
`examples/layers-map-overlay.py` writes. The `entry` tour crosses both
levels and exports as a deck, one headline per stop:

```bash
grafli export grafli/examples/layers-map.grafli deck.pdf --legend
grafli render grafli/examples/layers-map.grafli tests.png --overlay tests
```

## Matrix and mirror demos

Two worked examples of the encoding catalogue on grafli's own subject.
`examples/outputs-matrix.grafli` places every way a board leaves the file
on two forces — who can change it while it is shown, and how much of the
map it carries — so the empty corner the planned live tab fills is visible.
`examples/save-reload-mirror.grafli` puts reloading an outside write and
saving side by side, the same step at the same height: both meet in
`merge_boards()`, and the step only saving has, `atomic_write()`, leaves a
gap on the reload side.

```bash
grafli render grafli/examples/outputs-matrix.grafli matrix.png
grafli render grafli/examples/save-reload-mirror.grafli mirror.png
```

## Fan-out demo

`examples/source-and-builds.grafli` is six boxes and five arrows: one
canonical source package (the filled box) fans out to its builds, and
releases tie packages together. Position carries the claim — left is the
canonical item, right is what is derived from it — and the labels carry
the cardinality (`1`, `N`, `N:N included in`), drawn bold. It is the
board grafli's render is compared with a hand-made sketch on:

```bash
grafli render grafli/examples/source-and-builds.grafli fan-out.png
```

## Try it yourself

The format is small enough that the fastest way to learn is to read a
file and edit it. Start from the example, then:

1. Press <kbd>n</kbd> to drop a new box.
2. Press <kbd>Ctrl</kbd>+<kbd>l</kbd> to spawn a connected box to the
   right.
3. Press <kbd>e</kbd> on an arrow and prefix the label with `call:`,
   `data:`, or `event:` to see edge chips render live.

For more on annotations, see [Text annotations](text-annotations.md).
