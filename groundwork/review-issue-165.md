---
kind: review
project: grafli
issue: 165
pr: 181
status: awaiting-review
statuses: drafting, awaiting-review, addressed
verdict: needs-discussion
---

# Review of PR #181 — grafli#165

The PR makes a flow step `<board>#<bookmark>` a stop in another board. Playback enters that board through the board stack, and `Esc` ends the tour back on the board the flow belongs to. Leaving a tour with `gd` or `Return` keeps its stop in the stack frame, and `gu` back resumes it. PDF/PPTX export, `grafli export --check` and `grafli render --step` render each such stop from its own board. Verdict: needs discussion. Playback and export do what the issue asks and the whole suite passes (1145 passed, exit 0). Two things need the owner's word, though. The third box asks for a 3-page PDF and the branch writes 4 pages (a title page plus one page per stop). And D8 is narrowed: it said "navigate freely", and now only `gd`/`Return` leave a tour. Both readings are reasonable, and both are written down on the issue, but nobody has confirmed them. Apart from that, one example in the new docs gives a path that does not resolve, and that has to be fixed.

## Acceptance

### a test plays a 3-stop tour root → sub-board → sub-sub-board in order and returns to the root
**Met:** yes
**Evidence:** `tests/test_tour_across_boards.py::test_a_tour_plays_down_three_boards_in_order_and_returns_to_the_root` steps System → `System-res/combat.grafli` → `System-res/combat-res/impact.grafli` and asserts stop index and label, breadcrumb `System › combat` and board path `["System", "combat", "impact"]`. `Esc` then lands on `System.grafli` with `_flow_player is None` and an empty board path. `test_stepping_back_climbs_the_boards_again` covers `←` back up. Full suite in this worktree: `python -m pytest -q` → `1145 passed, 1 warning in 33.89s`, exit 0.

### leaving at stop 2 and `gu` back resumes at stop 2
**Met:** yes
**Evidence:** `tests/test_tour_across_boards.py::test_leaving_at_stop_two_and_gu_back_resumes_at_stop_two` leaves at stop 2 with `gd` into `detail.grafli` and checks the toast "Tour paused at stop 2 — gu resumes it". After `gu` it is back on `combat.grafli` at `(1, "The blow")`, and `Space` goes on to stop 3. `test_return_on_a_level_leaves_the_tour_too` tests the same with `Return`. I also ran my own script for a tour in `loop` mode: it was left with `gd` and resumed with `gu` at `combat.grafli (1, 'The blow') mode loop timer True`.

### the PDF export of that tour has 3 pages; the board is written as `v3`
**Met:** no
**Evidence:** The `v3` half is met: `tests/test_tour_export.py::test_the_tour_board_is_written_as_v3` reads a `#!grafli v2` header and writes `#!grafli v3` (`grafli/format.py:1094`, `"cross-board stops": (3, uses_cross_board_stops)`). The page count is not: `test_the_pdf_has_a_page_per_stop_after_the_title` asserts `(slides, overloaded) == (4, [])` and `_page_count(...) == 4  # title + 3 stops`. The PR comment on #165 reads "3 pages" as one page per stop and keeps the title page so plain tours export as before. That reading is reasonable, but it is a change to the box, so the owner has to accept it before this box is ticked. The alternative is a title-less export, which is not what this PR does.

## Design

### The docs' example tour names the sub-sub-board by a path that does not exist in a vault
**Severity:** should-fix
**Kind:** must-fix
**Evidence:** `docs/bookmarks-flows.md:152` shows `@ flow blow "A blow lands" overview combat#lunge combat-res/impact.grafli#hit`. `board_target_path` (`grafli/resources.py:161-168`) resolves a relative path against the folder of the flow's own board. In a vault, `combat`'s sub-board lives one folder lower. I ran the resolver for a board at `/m/System.grafli`: the example resolves to `/m/combat-res/impact.grafli`, but the board is at `/m/System-res/combat-res/impact.grafli`. A vault name is no way round it either, because it resolves only in the flow board's own vault: `board_target_path(home, "impact")` → `/m/System-res/impact.grafli`. The PR's own tests had to write the full `System-res/combat-res/impact.grafli#i1` (`tests/test_tour_across_boards.py:40`). Someone who copies the docs' pattern gets the toast "impact.grafli is gone". The fix: correct the example to `<board>-res/combat-res/impact.grafli#hit`, and say in that paragraph, in `docs/format.md` and in the skill's `references/format.md` that a vault name means a sub-board of the flow's own board, and that anything deeper needs a relative path.
**Backlog:** new. #36 is about older docs drifting from the format, not about this new text.

### The Flows tab shows every cross-board stop as fine, typos included
**Severity:** should-fix
**Kind:** follow-up
**Evidence:** `grafli/flowspanel.py:591-598`: `elif "#" in step.ref:` labels the step `↪ <bookmark>  in <board>`, with the comment "named, not flagged — it is fine". It never checks that the board or the bookmark exists. My script changed the refs to `combat#typo` and `nowhere#x`, and the panel showed `['↪ typo  in combat', '↪ x  in nowhere']` with no `⚠`. A missing bookmark on the same board still gets `⚠ <ref>` (`:599-602`). `grafli export --check` does catch the broken stop (`test_export_check_flags_a_stop_in_a_missing_board`), but the editor shows nothing until the tour is played or exported. The fix: resolve the stop the way the export check does (`grafli/app.py:1411` `_step_bookmark`) and show `⚠` when that fails.
**Backlog:** new. #59 asks for flow validation in `grafli diagnose` (the CLI), not in the Flows tab.

### Where a stop lies is worked out in four places, and the other board is loaded three ways
**Severity:** consider
**Kind:** follow-up
**Evidence:** Each of these calls `split_step_ref` and then `board_target_path` itself:

- the player, `grafli/flows.py:418-447` (`_step_board` / `_step_bookmark`)
- the export check, `grafli/app.py:1411-1423` (a second, unrelated function also named `_step_bookmark`, with a different signature)
- `grafli/app.py:1949-1961` (`_cmd_render`)
- `grafli/slideplan.py:87-108` (`_stop_view`)

Three more places test "is this a cross-board stop" as `"#" in step.ref`: `grafli/format.py:478`, `grafli/flowspanel.py:591` and `:699`. The other board is loaded in three ways:

- bare `parse` in `grafli/app.py:1421` and `:1959`
- `parse` plus `classify_attachments` plus `load_docs` in `grafli/slideplan.py:115-117`, which repeats `_load_vault` (`grafli/app.py:1427-1433`) inline

The next change to stop addressing has to find all of these, for example a vault name resolving in the sub-board's vault, or a `graph:` spelling. The fix: keep one resolver next to `board_target_path` that takes the home board and a step and returns the path and bookmark id (or a `FlowStep` property for the board part), plus one loader for "a board file with its vault".
**Backlog:** new

### Auto-play, loop and some resume paths across boards have no test
**Severity:** consider
**Kind:** follow-up
**Evidence:** Neither `tests/test_tour_across_boards.py` nor `tests/test_tour_export.py` drives `_auto_advance`, `mode = "playing"`/`"loop"`, the "The paused tour is gone" branch of `_resume_tour` (`grafli/app.py:783-795`), or the Flows-tab rule that clicking a cross-board step does not switch boards (`grafli/flowspanel.py:699`). A grep for those names in both files returns nothing (exit 1). My script shows the first two work today: loop mode wraps from `impact.grafli` back to `System.grafli (0, 'The player')` with breadcrumb `[]`, and a resumed tour keeps `mode loop` with the timer running. No test holds that behaviour in place.
**Backlog:** new

**Dependencies:** the PR targets `issue-164`, the branch of grafli#180, and its body's single `Depends on: https://github.com/mistergc/grafli/pull/180` matches the plan's edge (missing: none, extra: none). `git merge-base --is-ancestor origin/issue-164 HEAD` succeeds. `BoardFrame` and `split_board_fragment` are not on `origin/main` (`git grep` there finds neither); they reach this branch through `issue-164`'s own stack, which is #180's dependency to declare, not this PR's. No `[DEPENDS]` finding.

## Performance

No findings.

## Scalability

No findings.

## Inherited design

### The flow player now relies on private attributes of the main window and fails silently without them
**Severity:** consider
**Kind:** follow-up
**Evidence:** The view mixins already reach into the window by duck-typed private attributes: `grafli/view/levels.py:73` and `:250` (`getattr(self.window(), "_file_path", None)`) and `grafli/view/resources.py:125` (`hasattr(window, "_enter_board")`). The change carries that pattern into `FlowPlayer`, which is not a view mixin: `grafli/flows.py:333`, `:430` and `:443` (`getattr(self.view.window(), "_tour_goto_board", None)`, `..."_file_path"...`), and `grafli/flowspanel.py:322-323` (`hasattr(window, "_paused_tour")`). If those attributes are missing, a stop in another board quietly resolves to `None` and shows as "(missing bookmark)". Nothing raises, and nothing names the dependency. The fix: hand the player a small navigator (the home path and a `goto_board(path) -> bool` callable) when `play_flow`/`resume_flow` create it.
**Backlog:** new

## Consistency

No findings.

## Not verified

- The level-zoom animation while a tour is left and resumed: every test and both of my scripts run with `transitions_enabled = lambda: False`. The PR also lists this as not verified.
- Leaving a tour by following a link with the mouse. It goes through `_enter_board` (`grafli/app.py:702-734`), which records `tour=self._view.tour_position()`, but no test or script of mine clicked a link.
- Whether the owner accepts the two readings recorded on #165 and in the plan's Drift line: 4 PDF pages (title + 3 stops), and D8 narrowed to `gd`/`Return` leaving the tour. D8 in `explorable-maps-2026-10-09.md` says "navigate freely (enter a level, follow a link, pan around)".
- The PR body's screenshots and the claim that `examples/showcase.grafli` renders byte-identical to `issue-164`: I did not open the images or rerun the sha1 comparison.
- In-app PDF/PPTX export of an unsaved board: `_file_path` is `None`, so `build_slide_plan` gets no `board_path` and cross-board stops become "(missing bookmark)" (`test_without_its_board_path_a_stop_elsewhere_is_missing`). I did not check whether the app tells the user.
