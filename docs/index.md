---
hide:
  - navigation
  - toc
---

<div class="grafli-hero" markdown>

# grafli

<p class="grafli-tagline">
A keyboard-driven, plain-text diagram tool for people who think faster than they click.
</p>

<div class="grafli-cta" markdown>

[Install grafli :material-download:](#install){ .md-button .md-button--primary }
[GitHub :material-github:](https://github.com/MisterGC/grafli){ .md-button }
[PyPI :material-package:](https://pypi.org/project/grafli/){ .md-button }

</div>

</div>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; `hero.png`: Region 1 of `examples/showcase.grafli` (clean architecture with `call:` / `data:` edge chips and a `code:` note attached to the order service).
</div>

## Why grafli

<div class="grafli-pillars" markdown>

<div class="grafli-pillar" markdown>
### Keyboard-first
Modal editing, vim muscle memory. Four primary modes — Select, Rect, Text, Connect — and you build entire diagrams without ever reaching for the mouse.
</div>

<div class="grafli-pillar" markdown>
### Less is more
A small, deliberate set of primitives — boxes, arrows, notes — composes into anything from a quick sketch to a layered architecture diagram. No menus to discover, no themes to fight.
</div>

<div class="grafli-pillar" markdown>
### Text for AI, git, humans
`.grafli` files are line-oriented plain text. Diffs make sense. LLMs can read and write them. You can edit them in your editor of choice. No binary blobs, no cloud lock-in.
</div>

</div>

## A file format you can read

```text
@ box web "Web App"        60,80   200x100 %secondary
@ box api "API Gateway"   380,80   220x100 %primary
@ box svc "Order Service" 720,80   220x100 %tertiary
@ box db  "PostgreSQL"    380,260  220x100 %subtle

@ arrow web -> api "call: REST"
@ arrow api -> svc "call: GraphQL"
@ arrow svc -> db  "data: queries"

@ note svc_code 1000,40 """
code:
fn: createOrder(req) -> Order
call: validate(req)
verify: tests/test_orders.py
emit: OrderCreated
return: order
"""
```

One element per line. Stable IDs. Diffs that highlight what actually changed. The format is small enough to learn in a sitting and structured enough that an LLM can produce a valid diagram from a prompt.

- **Human-readable** — nothing is encoded; you can hand-edit any element.
- **Git-native** — line-oriented diffs reflect intent.
- **AI-ready** — LLMs reliably emit and modify the format from natural language.
- **External edits welcomed** — grafli watches the file and reloads automatically.

## Annotate with intent

Notes aren't just sticky labels. Grafli recognizes lightweight conventions and renders them with visual weight that matches their meaning.

- **Tasks** (`T:`) and **questions** (`Q:`) get distinct colors so review work is visible at a glance.
- **Discussions** (`AI:` / `Reviewer:` …) format as threaded conversation bubbles inside a single note.
- **Code-mode notes** (lines starting with `code:`) render syntax-highlighted pseudocode with system-design keywords like `fn:`, `if:`, `call:`, `verify:`, `risk:`, plus `@file:line` references.
- **Semantic edge labels** — prefixes like `call:`, `data:`, `event:`, `verify:`, `risk:` render as colored chips on the arrow itself.
- **Markdown resources** — attach a markdown note to any element and edit it in a full-window zen editor.

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; `annotations.png`: Region 2 of `examples/showcase.grafli` (a `T:` task, a `Q:` question, an `AI:`/`Reviewer:` discussion, a `code:` note, and arrows carrying `call:` / `event:` / `risk:` / `verify:` chips).
</div>

## Read complex diagrams

Real diagrams sprawl. Two view modes turn a busy diagram into a focused one.

- **Subgraph focus** — <kbd>B</kbd> on a node fades everything that isn't reachable from it. Cycle through *all* / *forward* / *backward* directions; toggle 1-hop vs unlimited depth with <kbd>Shift</kbd>+<kbd>B</kbd>.
- **Complexity heatmap** — <kbd>A</kbd> colors every node by how many connections, parents, and children it has. Hot nodes glow; cold nodes fade. Find the parts of a diagram that need refactoring without reading every label.

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; `heatmap.png`: Region 3 of `examples/showcase.grafli` with <kbd>A</kbd> active. The `API` hub glows as the hottest node.
</div>

## Navigate diagrams that grew

- **Jump labels** (<kbd>Ctrl</kbd>+<kbd>J</kbd>) — every visible item gets a one-or-two-key label; press it to select.
- **Search** (<kbd>/</kbd>) by label, fuzzy-matched.
- **Graph navigation** — hold <kbd>Alt</kbd>, see connector keys, follow edges chord by chord.
- **Hierarchy traversal** — <kbd>P</kbd> parent, <kbd>F</kbd> first child, <kbd>Tab</kbd> cycle siblings, with a breadcrumb in the status bar.
- **Jumplist** (<kbd>Ctrl</kbd>+<kbd>O</kbd> / <kbd>Ctrl</kbd>+<kbd>I</kbd>) — vim-style viewport history.
- **Sub-graflis** — link any node to a deeper diagram in its own file. Click through, edit, return.

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; `jump-labels.png`: Region 3 of `examples/showcase.grafli` with <kbd>Ctrl</kbd>+<kbd>J</kbd> active. Every visible element carries a one- or two-character jump label.
</div>

## Where grafli fits

<div class="grafli-pillars" markdown>

<div class="grafli-pillar" markdown>
### System architecture
Lay out services, data flows, and ownership lines with semantic edge labels that survive into the file format.
</div>

<div class="grafli-pillar" markdown>
### Code review notes
Attach `T:` / `Q:` annotations and code-mode pseudocode summaries to any element. Pair the diagram with the PR.
</div>

<div class="grafli-pillar" markdown>
### Brainstorming
Modal creation is fast enough to keep up with thinking. Refactor by selection, not redrawing.
</div>

<div class="grafli-pillar" markdown>
### Living design docs
Embed a `.grafli` next to your markdown. Diff it. Render it on demand. Treat diagrams like the code they describe.
</div>

</div>

## Install { #install }

```bash
pip install grafli
grafli my-diagram.grafli
```

Requirements: Python 3.12+, PySide6 (Qt 6.7+).

Yank the diagram as PNG to your clipboard with <kbd>Y</kbd>; export SVG with <kbd>Ctrl</kbd>+<kbd>E</kbd>. Auto-save flushes within 300 ms. Press <kbd>F1</kbd> in-app for the full keybinding cheat sheet and text-annotation reference.

## Project

- [Source on GitHub](https://github.com/MisterGC/grafli)
- [PyPI](https://pypi.org/project/grafli/)
- [Issue tracker](https://github.com/MisterGC/grafli/issues)
- [Changelog](https://github.com/MisterGC/grafli/blob/main/CHANGELOG.md)

Released under the MIT License.
