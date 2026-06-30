# Suggestions demo

Open this in the reading view to try track-changes:

    textli examples/suggestions-demo.md
    # then press ⌘R to switch to the reading view

In the reading view, **removed** text is struck out in red and **added** text is
written in blue handwriting. Step through the changes and accept or reject each.

## Keys

- `]s` / `[s` — jump to the next / previous suggestion
- `a` — accept the suggestion under the caret (then it advances to the next)
- `x` — reject it (and advance)
- `⇧A` / `⇧X` — accept all / reject all
- `]c` / `[c`, `Enter` — the existing comment navigation still works

## Try it

The quarterly {~~numbers~>figures~~} look off this quarter, so we should
{++double-check the ledger before the board call ++}and revisit the {--clearly --}stale
forecast.

Our north-star metric is {~~daily active users~>weekly active users~~}; the
{++newly proposed ++}guardrail metric is crash-free sessions.

This sentence has a {==deliberate highlight==}{>>this is a comment, not a
suggestion — Enter reveals it<<} so you can see comments and suggestions side by
side.

### A longer rewrite

{~~The onboarding flow is fine.~>We are replacing this whole sentence with a much
longer rationale so you can see that a long rewrite drops the handwriting font for
the body font on a faint blue wash, which stays readable in bulk.~~}

### Not a suggestion (inside code)

The markup itself is left literal inside code, so this is documentation, not an
edit:

```
{~~old~>new~~}  {++inserted++}  {--deleted--}
```

Inline too: write `{++like this++}` to propose an insertion.
