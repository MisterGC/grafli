# Suggestions demo

Open this in the reading view to try track-changes:

    textli examples/suggestions-demo.md
    # then press ⌘R to switch to the reading view

In the reading view, **removed** text keeps the body ink but wears a strong
strike line, and **added** text is in a subtle zen red. Step through the changes
and accept or reject each — or preview the clean result.

## Keys

- `]s` / `[s` — jump to the next / previous suggestion
- `a` — accept the suggestion under the caret (then it advances to the next)
- `x` — reject it (and advance)
- `⇧A` / `⇧X` — accept all / reject all
- `s` — author your own: select a span and press `s`, type the replacement
  (empty = delete); with no selection, `s` inserts at the caret
- `gc` — changes overview: a jump-list of every change and comment
- `p` — preview the clean prose with every suggestion accepted (source untouched)
- `]c` / `[c`, `Enter` — the existing comment navigation still works

## Try it

The quarterly {~~numbers~>figures~~} look off this {==quarter==}{>>is this the
Q2 dip again?<<}, so we should {++double-check the ledger ++}and revisit the
{--clearly --}stale forecast.

Our north-star metric is {~~daily active users~>weekly active users~~}; the
{++newly proposed ++}guardrail metric is crash-free sessions.

We should {~~ship on Friday~>ship on Monday~~} to avoid a {--risky --}weekend
deploy, and {++notify on-call ++}before the rollout starts.

The API returns {~~a list~>a paginated list~~} of results; the client must
{++handle the cursor and ++}retry on {~~5xx~>429 and 5xx~~} responses.

This sentence has a {==deliberate highlight==}{>>this is a comment, not a
suggestion — Enter reveals it<<} so you can see comments and suggestions side by
side.

### A longer rewrite

{~~The onboarding flow is fine.~>We are replacing this whole sentence with a much
longer rationale so you can see that a block-sized rewrite reads as plain zen-red
body text — no wash, no special case — the same treatment as a one-word edit,
just more of it.~~}

### A few more to burn through

- Rename {~~the util module~>the helpers module~~} for clarity.
- Drop the {--now-unused --}legacy adapter.
- Add {++a smoke test and ++}a changelog entry before tagging.

### Not a suggestion (inside code)

The markup itself is left literal inside code, so this is documentation, not an
edit:

```
{~~old~>new~~}  {++inserted++}  {--deleted--}
```

Inline too: write `{++like this++}` to propose an insertion.
