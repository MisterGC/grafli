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
[Take the tour :material-arrow-right:](#tour){ .md-button }
[GitHub :material-github:](https://github.com/MisterGC/grafli){ .md-button }

</div>

</div>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; hero shot: a real grafli session showing a system architecture diagram with semantic edge chips, a code-mode note, and the focus filter active.
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

## 30-second tour { #tour }

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; animated GIF: launch grafli, press <span class="grafli-keycap">n</span> to create a box, type a label, press <span class="grafli-keycap">Ctrl+L</span> to spawn a connected box to the right, repeat. End with a four-box diagram in under 10 seconds.
</div>

---

## Build by typing

Press <span class="grafli-keycap">n</span> to drop a box. Press <span class="grafli-keycap">o</span> to add one below the current selection. <span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">h</span> / <span class="grafli-keycap">k</span> / <span class="grafli-keycap">l</span> create a *connected* box to the left, up, or right — arrow included. Most diagrams take fewer keystrokes than describing them in prose.

<div class="grafli-feature" markdown>

<div markdown>
- **Modes** for spatial intent: Select (<span class="grafli-keycap">v</span>), Rect (<span class="grafli-keycap">n</span>), Text (<span class="grafli-keycap">t</span>), Connect (<span class="grafli-keycap">c</span>).
- **Directional creation**: spawn neighbors, connected by an arrow, with one chord.
- **Style and dimension sub-modes** (<span class="grafli-keycap">s</span> / <span class="grafli-keycap">d</span>) for color, size, and resize without leaving the keyboard.
- **Smart arrow routing** snaps edges to the nearest box boundary; bidirectional pairs merge automatically.
</div>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; screencast: directional creation with <span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">l</span> spawning connected boxes; show the arrow snapping cleanly between them.
</div>

</div>

## A file format you can read

```text
@ box frontend "Frontend" 100,100 160x60 %secondary
@ box backend  "Backend"  320,100 160x60 %primary
@ arrow frontend -> backend "REST API"
@ arrow backend  -> db      "data: queries" !dashed
@ note 100,240 "SPA with React"
```

One element per line. Stable IDs. Diffs that highlight what actually changed. The format is small enough to learn in a sitting and structured enough that an LLM can produce a valid diagram from a prompt.

<div class="grafli-feature" markdown>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; split view: `.grafli` source on the left, rendered diagram on the right; a one-line edit highlighted in both panels.
</div>

<div markdown>
- **Human-readable** — nothing is encoded; you can hand-edit any element.
- **Git-native** — line-oriented diffs reflect intent.
- **AI-ready** — LLMs reliably emit and modify the format from natural language.
- **External edits welcomed** — grafli watches the file and reloads automatically.
</div>

</div>

## Annotate with intent

Notes aren't just sticky labels. Grafli recognizes lightweight conventions and renders them with visual weight that matches their meaning.

<div class="grafli-feature" markdown>

<div markdown>
- **Tasks** (`T:`) and **questions** (`Q:`) get distinct colors so review work is visible at a glance.
- **Discussions** (`AI:` / `Reviewer:` …) format as threaded conversation bubbles inside a single note.
- **Code-mode notes** (lines starting with `code:`) syntax-highlight pseudocode with keywords like `fn:`, `if:`, `call:`, `verify:`, `risk:`, `@file:line` references.
- **Semantic edge labels** — prefixes like `data:`, `call:`, `event:`, `verify:`, `risk:` render as colored chips on the arrow itself.
- **Markdown resources** — attach a markdown note to any element and edit it in a full-window zen editor.
</div>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; collage: a code-mode note (`fn:`/`call:`/`verify:`), a `T:`/`Q:` pair, semantic edge chips on three arrows (`call:`, `data:`, `risk:`), and an inline discussion thread.
</div>

</div>

## Navigate diagrams that grew

Real diagrams sprawl. Grafli has navigation built for that.

<div class="grafli-feature" markdown>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; jump labels overlaid on every visible element via <span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">J</span>; one keystroke selects the target.
</div>

<div markdown>
- **Jump labels** (<span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">J</span>) — every visible item gets a one-or-two-key label; press it to select.
- **Search** (<span class="grafli-keycap">/</span>) by label, fuzzy-matched.
- **Graph navigation** — hold <span class="grafli-keycap">Alt</span>, see connector keys, follow edges chord by chord.
- **Hierarchy traversal** — <span class="grafli-keycap">P</span> parent, <span class="grafli-keycap">F</span> first child, <span class="grafli-keycap">Tab</span> cycle siblings, with a breadcrumb in the status bar.
- **Jumplist** (<span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">O</span> / <span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">I</span>) — vim-style viewport history.
- **Sub-graflis** — link any node to a deeper diagram in its own file. Click through, edit, return.
</div>

</div>

## Read complex diagrams

Two view modes turn a busy diagram into a focused one.

<div class="grafli-feature" markdown>

<div markdown>
**Subgraph focus** — <span class="grafli-keycap">B</span> on a node fades everything that isn't reachable from it. Cycle through *all* / *forward* / *backward* directions; toggle 1-hop vs unlimited depth with <span class="grafli-keycap">Shift</span>+<span class="grafli-keycap">B</span>. Clear with the same key.

**Complexity heatmap** — color every node by how many connections, parents, and children it has. Hot nodes glow; cold nodes fade. Find the parts of a diagram that need refactoring without reading every label.
</div>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; two stacked panels: top shows subgraph focus dimming unrelated boxes; bottom shows the complexity heatmap with a few hot nodes glowing red.
</div>

</div>

## Share, embed, export

<div class="grafli-feature" markdown>

<div class="grafli-screenshot" markdown>
PLACEHOLDER &mdash; example: <span class="grafli-keycap">Y</span> to copy diagram to clipboard, paste into a markdown file or chat; <span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">E</span> exporting a clean SVG.
</div>

<div markdown>
- **Yank as PNG** (<span class="grafli-keycap">Y</span>) — the whole diagram on your clipboard, ready to paste into a doc, chat, or PR.
- **SVG export** (<span class="grafli-keycap">Ctrl</span>+<span class="grafli-keycap">E</span>) — vector output for documentation pipelines.
- **Auto-save** — changes flush within 300 ms; no save buttons, no lost work.
- **External resources** — drop in images and markdown files; grafli tracks paths and migrates them when you rename.
</div>

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

Press <span class="grafli-keycap">F1</span> in-app for the full keybinding cheat sheet and text-annotation reference.

## Project

- [Source on GitHub](https://github.com/MisterGC/grafli)
- [PyPI](https://pypi.org/project/grafli/)
- [Issue tracker](https://github.com/MisterGC/grafli/issues)
- [Changelog](https://github.com/MisterGC/grafli/blob/main/CHANGELOG.md)

Released under the MIT License.
