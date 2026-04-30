# File format

A `.grafli` file is line-oriented plain text. One element per line. Lines
that start with `#` are comments. Order does not affect rendering — the
layout is encoded in each element's coordinates.

## Header

```text
#!grafli v1
```

The first line is a shebang-style header that identifies the format and
its version. It is required.

## Element types

```text
@ box <id> "<label>" <x>,<y> <w>x<h> [color] [^anchor] [~size] [!style] [>parent]
@ note [<id>] <x>,<y> "<text>" [color] [~size] [!style] [>parent]
@ arrow <from> <op> <to> ["label"] [!style] [~size]
```

| Element | Purpose |
|---------|---------|
| `box`   | Rectangular container with a label. Can nest via `>parent`. |
| `note`  | Free-form text block. Supports tasks, questions, code-mode, and discussions (see [Text annotations](text-annotations.md)). |
| `arrow` | Directed/bidirectional connector between two elements. |

### Arrow operators

| Operator | Meaning |
|----------|---------|
| `->`     | Right (from → to) |
| `<-`     | Left  (from ← to) |
| `<->`    | Bidirectional     |
| `--`     | No arrowhead      |

### Modifiers

- `<color>` — built-in tokens: `%primary`, `%secondary`, `%tertiary`,
  `%accent`, `%subtle`, `%muted`, or any `#rrggbb` hex value.
- `^anchor` — `topleft`, `top`, `topright`, `left`, `center`, `right`,
  `bottomleft`, `bottom`, `bottomright`. Controls how a box's label is
  placed.
- `~size` — `xsmall`, `small`, `medium`, `large`, `xlarge`.
- `!style` — `flat`, `dashed`, plus arrow-specific styles.
- `>parent` — nest this element inside the box with the given ID.

## Block text

When a note's text contains quote characters or spans multiple lines, use
triple quotes:

```text
@ note logic 100,320 """
code:
fn: handleRequest(req)
call: validate(req)
emit: RequestAccepted(req.id)
return: ok
"""
```

The serializer auto-promotes single-line notes that contain `"` to the
triple-quoted form.

## A complete example

```text
#!grafli v1
# A small architecture sketch

@ box frontend "Frontend" 100,100 160x60 %secondary
@ box backend  "Backend"  320,100 160x60 %primary
@ box db       "Database" 320,240 160x60 %subtle

@ arrow frontend -> backend "call: REST API"
@ arrow backend  -> db      "data: queries" !dashed

@ note 100,240 "SPA with React"
```

## Why plain text

- **Git-native** — every change is a line-level diff with intent baked in.
- **Editor-friendly** — open with any text editor; grafli watches the
  file and reloads automatically.
- **AI-ready** — the format is small enough that LLMs reliably read,
  modify, and emit valid diagrams from natural language.
