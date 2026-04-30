# Text annotations

Notes in grafli are not just labels — a few lightweight conventions make
the *kind* of note visible at a glance, and let the format carry review
intent into git diffs.

## Tasks and questions

Lead a note (or a line in a multi-line note) with one of:

| Prefix | Meaning |
|--------|---------|
| `T:`   | Task / TODO |
| `Q:`   | Question / clarification |

Both render with distinct colors so review work is easy to spot when you
zoom out.

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
pseudocode block. The body is keyword-led, one instruction per line:

| Keyword | Use |
|---------|-----|
| `fn:`     | Function signature |
| `if:` / `then:` / `else:` | Branching |
| `for:` / `while:` | Iteration |
| `call:`   | Important call |
| `await:`  | Blocking / async wait |
| `emit:`   | Event / message emission |
| `try:` / `catch:` | Protected block / error handling |
| `set:`    | Assignment |
| `state:`  | State transition (`from -> to`) |
| `assert:` / `pre:` / `post:` | Invariants |
| `verify:` | Test / check / trace that proves behavior |
| `risk:`   | Failure mode / review risk |
| `return:` / `err:` | Exit value / error |
| `note:`   | Review note / assumption |
| `@path:line` | Reference to real source code |
| `# …`     | Comment (rendered dimmed) |

```text
@ note logic 100,320 """
code:
fn: handleRequest(req) -> Result
pre: req.id is not None
call: validate(req)            @grafli/api.py:42
verify: tests/test_api.py::test_handle_ok
risk: silently drops malformed payloads
emit: RequestAccepted(req.id)
return: ok
"""
```

The pseudocode is not executable — it's a minimal, scannable language
designed for review-oriented diagrams that pair with a PR.

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

## Markdown resources

Any element can link to a markdown file. Open the linked resource with
<kbd>E</kbd> on the selected element to edit it in a full-window zen
editor with vim-style keybindings.

The path is stored in the `.grafli` file; grafli tracks it and migrates
references when you rename the file.
