# Pair grafli with your AI

grafli isn't just a diagram editor — it's the canvas your coding agent
uses to **communicate complex systems back to you**. A `.grafli` file
is plain text, line-oriented, and small enough that an LLM can read,
modify, and produce it in seconds. The bundled grafli **skill**
teaches the agent how to do that *well*.

![How the grafli skill works — pipeline from user prompt through trigger check, planning loop, render-and-verify loop, to a clean .grafli output](assets/screenshots/skill-pipeline.png)

The diagram above is itself a `.grafli` (`examples/skill-explained.grafli`)
authored under the same skill it describes — meta-correct, and a small
demonstration that the workflow holds.

## Why a skill is needed

Without guidance, a generic LLM will invent broken `.grafli` syntax,
fight the renderer's layout model, and produce diagrams that look
plausible in the conversation but render as overlapping boxes and
crossed arrows in the actual app.

The skill gives the agent:

- **Tight format reference** — every keyword, modifier, and edge style.
- **A planning loop** — "what question does the diagram answer?"
  before any boxes get placed, so the diagram has a point.
- **Layout discipline** — grid alignment, container margin model,
  flow direction, fan-out handling, the typography scale.
- **Code-mode authoring style** — predicate-style names, contract
  keywords for review focus, when to use a code-block versus split
  the logic into multiple nodes.
- **Common-mistakes checklist** — quote escaping, disconnected nodes,
  truncated labels, deprecated keywords. The things that recur.

## Install

The skill ships **inside the Python package**. Pull it out and place
it where your AI tool expects skills:

```bash
# Save to a file
grafli skill -o SKILL.md

# Pipe straight into the right place
grafli skill > ~/.claude/skills/grafli/SKILL.md

# Print the path of the bundled copy (so you can symlink it)
grafli skill --where

# Show install hints + per-tool docs URLs
grafli skill --help
```

| AI tool | Where the skill goes | Docs |
|---------|---------------------|------|
| Claude Code | `~/.claude/skills/grafli/SKILL.md` (or per-project under `.claude/skills/...`) | <https://code.claude.com/docs/en/skills> |
| OpenCode | `~/.config/opencode/skills/grafli/SKILL.md` | <https://opencode.ai/docs/skills> |
| Codex CLI | append to `~/.codex/AGENTS.md` (or per-repo `AGENTS.md`) | <https://agents.md/> |

A symbolic link keeps the on-disk skill in sync with `pip install --upgrade grafli`. A copy is fine if your platform doesn't support
symlinks comfortably (Windows non-developer mode).

## What the skill triggers on

The skill is deliberately **scoped narrowly** to avoid polluting
unrelated conversations. It activates on **explicit visualization
requests** — phrases like:

- "draw a diagram of …"
- "visualize the …"
- "sketch / map out / graph this"
- "make a grafli for …"
- working on existing `.grafli` files

It does **not** activate on generic "review this code", "explain this
function", or "summarize this module" requests unless the user also
asks for a visual or diagram. Keeping the trigger tight keeps your
agent fast and focused on the task at hand.

## A typical session

Once the skill is installed, the agent:

1. Listens for a visualization request.
2. Asks any clarifying question (the planning loop).
3. Produces a `.grafli` file using `Write`.
4. Optionally launches the desktop app or renders headless to PNG /
   SVG via `grafli render`, and shows you the result.
5. Iterates on the layout / labels based on feedback.

The agent's output is just text. You can edit it, diff it, version it,
and re-render any time. There is no proprietary format or cloud
service in the loop.

## Render-on-demand for your CI

Because `grafli render` is a non-interactive subcommand, your CI can
re-render diagrams on every push:

```bash
grafli render docs/architecture.grafli docs/architecture.svg
```

Pair this with a markdown reference to the SVG and the diagram in
your design doc stays in sync with the source — the same workflow as
docs-as-code, but for system pictures.

## Combining the skill with code-mode notes

The skill encourages **graph + code-mode** as the default pattern for
review-oriented diagrams: the graph carries *who calls whom*, while
each box has a 5–9 line code-mode note describing *what one function
does*. Together they answer questions neither could answer alone:

- Where could an open redirect hide? (graph locates the box, code
  note shows the `risk` line.)
- What contracts are covered by tests? (`verify:` arrows from a tests
  box mirror the `verify:` lines inside each code-mode note.)
- What's the failure mode of this saga? (each `pre` / `post` / `risk`
  contract is visible at a glance.)

This pattern is the headline differentiator versus generic diagram
tools — and the skill is what gets your agent to produce it cleanly
from a one-line prompt.
