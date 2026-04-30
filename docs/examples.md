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

## Try it yourself

The format is small enough that the fastest way to learn is to read a
file and edit it. Start from the example, then:

1. Press <kbd>n</kbd> to drop a new box.
2. Press <kbd>Ctrl</kbd>+<kbd>l</kbd> to spawn a connected box to the
   right.
3. Press <kbd>e</kbd> on an arrow and prefix the label with `call:`,
   `data:`, or `event:` to see edge chips render live.

For more on annotations, see [Text annotations](text-annotations.md).
