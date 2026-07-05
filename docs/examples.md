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

## Try it yourself

The format is small enough that the fastest way to learn is to read a
file and edit it. Start from the example, then:

1. Press <kbd>n</kbd> to drop a new box.
2. Press <kbd>Ctrl</kbd>+<kbd>l</kbd> to spawn a connected box to the
   right.
3. Press <kbd>e</kbd> on an arrow and prefix the label with `call:`,
   `data:`, or `event:` to see edge chips render live.

For more on annotations, see [Text annotations](text-annotations.md).
