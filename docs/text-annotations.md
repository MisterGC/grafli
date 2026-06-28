# Text annotations

Notes in grafli are not just labels — a few lightweight conventions make
the *kind* of note visible at a glance, and let the format carry review
intent into git diffs.

## Tasks and questions

Lead a note (or a line in a multi-line note) with one of:

| Prefix | Aliases (case-insensitive) | Meaning |
|--------|-----------------------------|---------|
| `T:`   | `t:`, `TODO:`, `todo:`     | Task / TODO |
| `Q:`   | `q:`, `QUESTION:`, `question:` | Question / clarification |

Both render with distinct colors so review work is easy to spot when you
zoom out. Whatever form you type, the rendered badge is normalised to the
short form (`T:` / `Q:`) for visual consistency.

## Discussions

A note can hold a threaded conversation. Lines that look like
`<speaker>: <text>` render as conversation bubbles when more than one
speaker appears in the same note. Speaker names are flexible —
`AI:`, `Reviewer:`, `Alice:`, `Bob:` all work.

```text
@ note discussion 200,400 """
Reviewer: Why is this synchronous?
Author: Legacy constraint — see ticket #421.
AI: We could move it behind an event bus once #421 lands.
"""
```

## Code-mode notes

A note whose first non-empty line is `code:` renders as a stylized
pseudocode block. It's not executable — it's a minimal, scannable
language designed for review-oriented diagrams that pair with a PR.

### Structure

* The **first body line is the function signature** — rendered bold with
  a divider rule beneath it. Write it without any keyword prefix:
  `tokenize(raw) -> [Token]`.
* **Indentation carries block structure.** Two spaces per level. Indent
  guides are drawn automatically.
* Trailing `:` on keywords is **optional** — `if cond` and `if: cond`
  both render the same. Prefer the no-colon form for new notes.

### Keywords

Keywords come in two visual groups: blue **flow** keywords carry the
control / effect plumbing; red **contract** keywords mark things a
reviewer should spot first.

| Keyword | Use | Colour |
|---------|-----|--------|
| `if cond` / `else action` | Branching | blue |
| `for x in xs` / `while cond` | Iteration | blue |
| `try` / `catch err -> action` | Protected block / error handling | blue |
| `return expr` | Exit value | blue |
| `call f(args)` | Important call | blue |
| `await op` | Blocking / async wait | blue |
| `emit event(args)` | Event / message emission | blue |
| `state from -> to` | State transition / lifecycle | blue |
| `pre cond` / `post cond` | Pre- / postcondition | **red** |
| `assert cond` | Invariant / expected fact | **red** |
| `verify evidence` | Test / check / trace | **red** |
| `risk text` | Failure mode / review risk | **red** |
| `err expr` | Error / raise | **red** |
| `@path:line` | Clickable source reference (opens in editor) | blue, underlined |
| `# …` | Comment (italic, muted) | grey |
| `"..."`, `#FFF`, `42`, `true` | Literal values render as plain text | — |

Plain assignments need no keyword: `out = []` is unambiguous.

### Style

The snippet should reveal *what happens*, not literally mirror the
source. Optimise for visual understanding at a glance.

* **Prefer short predicates and named operations** over long OO chains.
  `blank(line)` reads faster than `line.stripped.isEmpty`. Even when the
  underlying code uses dot chains, the note should use the verb that
  captures the intent.
* **Keep one abstraction level per snippet.** Mixing real method names
  with prose verbs forces the reader to re-parse mid-line.
* **Drop boilerplate.** Wrappers, logging, telemetry, defensive copies —
  omit unless they're the point of the function.

If a note grows past ~10 lines, it's trying to be a graph. Split it.

### Example

```text
@ note logic 100,320 """
code:
handleRequest(req) -> Result
pre req.id is set
call validate(req)
verify test_api.py::test_handle_ok
risk silently drops malformed payloads
emit RequestAccepted(req.id)
return ok  @grafli/api.py:42
"""
```

## Markdown-mode notes

A note whose first non-empty line is `md:` (or `markdown:`) renders its
body as lightly formatted Markdown — for prose annotations that want a
bit of structure. It's a sibling of code-mode: a formatted block on the
same beige plate, sharing the near-black body text.

Markdown notes are small canvas annotations, not documents. The
*recommended* subset is GitHub-flavoured:

| Markdown | Renders as |
|----------|------------|
| `# ` / `## ` / `### ` | Headings (3 levels, bold) |
| `- ` / `* ` | Bullet list |
| `1. ` | Ordered list |
| `- [ ]` / `- [x]` | Task checkboxes — **click to tick/untick** |
| `> ` | Blockquote |
| `---` | Horizontal rule |
| ` ``` ` fenced / `` `code` `` | Code block / inline code (muted plate) |
| `**bold**`, `*italic*`, `~~strike~~` | Inline emphasis |
| `[text](url)` | Link — click to open (reuses the `&url` handling) |

Task checkboxes are **interactive**: click anywhere on a `- [ ]` / `- [x]`
line to tick or untick it — the note's source flips that one checkbox
(a one-character diff) and saves, no editor needed. A `[text](url)` link
on the same line still opens on click; the rest of the line toggles.

Heavier Markdown (tables, images, raw HTML, footnotes) is parsed by the
underlying engine but isn't part of the supported surface and rarely
fits a canvas annotation — if a note wants that much, it's a document;
link it as a [Markdown resource](#markdown-resources) instead.

```text
@ note plan 100,320 """
md:
# Release checklist
Ship **0.4.0** with the new *Markdown* note.

- [x] Parser + rendering
- [ ] Docs and changelog

> See the [tracking issue](https://github.com/MisterGC/grafli/issues/65).
"""
```

## Semantic edge labels

Arrow labels can carry a relationship kind via a one-word prefix. The
prefix renders as a colored chip and tints the edge:

| Prefix    | Meaning |
|-----------|---------|
| `call:`   | Function / RPC call |
| `data:`   | Data flow |
| `event:`  | Event emission |
| `state:`  | State change |
| `step:`   | Step in a sequence |
| `verify:` | Verification / test |
| `owns:`   | Ownership |
| `depends:`| Dependency |
| `risk:`   | Risk / hazard |
| `note:`   | Annotation |

```text
@ arrow frontend -> backend "call: POST /orders"
@ arrow backend  -> queue   "event: OrderCreated"
@ arrow worker   -> db      "data: persist order"
```

Unknown `word:` prefixes are left as plain label text — ordinary labels
with colons are not affected.

## Editing notes

Two ways to edit a note's text:

* <kbd>e</kbd> (or double-click) — a small **inline** vim editor right on
  the canvas; it grows to fit as you type. Best for quick edits.
* <kbd>E</kbd> — the **full-window zen editor** (iA-Writer style, vim
  keybindings) on the note's own text. Best for longer prose. Saving
  writes straight back to the note — no separate file is created.

Both open in INSERT mode; <kbd>Esc</kbd> drops to NORMAL, a second
<kbd>Esc</kbd> commits, <kbd>Shift</kbd>+<kbd>Esc</kbd> discards.

## Reading & commenting

In the full-window zen editor, <kbd>⌘</kbd>+<kbd>R</kbd> toggles a **rendered
reading view** — a clean read of the Markdown, vim-navigable
(<kbd>j</kbd>/<kbd>k</kbd>, <kbd>Ctrl</kbd>+<kbd>d</kbd>/<kbd>u</kbd>,
<kbd>gg</kbd>/<kbd>G</kbd>).

You can **comment on a span of text while reading**. Comments live inline in
the Markdown itself (as [CriticMarkup](http://criticmarkup.com/) —
`{==span==}{>>your comment<<}`), so they travel with the file and diff in git
— no sidecar. In the reading view the comment body is **hidden** and the
commented span wears a **subtle highlight**; the text stays the focus, and a
comment only surfaces when you ask for it.

The reading view is **caret-based and vim-navigable** —
<kbd>h</kbd>/<kbd>j</kbd>/<kbd>k</kbd>/<kbd>l</kbd>, <kbd>w</kbd>/<kbd>b</kbd>/<kbd>e</kbd>,
<kbd>0</kbd>/<kbd>$</kbd>, <kbd>gg</kbd>/<kbd>G</kbd>, and half/full-page jumps move a
caret through the rendered text.

| Key | Action |
|-----|--------|
| <kbd>v</kbd> | Enter **visual mode** — extend a selection with the motions above (you can see the text the whole time, no label clutter) |
| <kbd>c</kbd> | Comment the visual selection — type the comment (<kbd>Esc</kbd> to save). You never type the markup yourself |
| <kbd>]</kbd><kbd>c</kbd> / <kbd>[</kbd><kbd>c</kbd> | Step to the next / previous comment |
| <kbd>Enter</kbd> | Reveal & edit the active comment inline; <kbd>Esc</kbd> returns to undisturbed reading |
| <kbd>Shift</kbd>+<kbd>D</kbd> | Delete the active comment (the highlight and body are removed) |

Clearing a comment's text and committing also deletes it. Because comments are
plain CriticMarkup, you (or a collaborator, or an AI) can also read and edit
them directly in the source.

## Markdown resources

Boxes and images can link to a separate markdown file. Open (or create)
the linked resource with <kbd>E</kbd> on the selected element to edit it
in the full-window zen editor.

The path is stored in the `.grafli` file; grafli tracks it and migrates
references when you rename the file.
