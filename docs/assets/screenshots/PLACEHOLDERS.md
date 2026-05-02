# Screenshot recipe for the landing page

The v0.1.0 landing page uses **four static PNGs**, all sourced from the same
file: `examples/showcase.grafli`. That file is laid out as three
spatially-separated regions; one region is captured twice (with different
runtime states) to cover all four shots.

## Producing the four images

```bash
grafli examples/showcase.grafli
```

For each shot: select an element in the target region (click it), then
press <kbd>Z</kbd> to fit-zoom to the selection's parent area. Adjust the
zoom and pan until the framing matches the description. Capture with your
OS screenshot tool (macOS: <kbd>⌘</kbd>+<kbd>Shift</kbd>+<kbd>4</kbd>) at
~1600 px wide, save under `docs/assets/screenshots/`.

| # | File | Region | Runtime state | What to capture |
|---|---|---|---|---|
| 1 | `hero.png` | 1 — *Baker's day* (`y ≈ 0`) | default | The six routine states (Sleep → Bake → Shop → Lunch → Deliver → Dinner) chained left-to-right with the loop arrow back to Sleep, the `step:` / `state:` / `event:` chips on the arrows, and the attached `code:` note for the *Bake bread* state. |
| 2 | `annotations.png` | 2 — *Threat reaction* (`y ≈ 900`) | default | The six behavior boxes (Sense → Assess, branching to Flee / Fight / Call guards, plus Hide), the chip arrows (`call:`, `event:` ×3, `step:`, `risk:`, `verify:` ×2), the `T:` and `Q:` notes, the `Designer:`/`Reviewer:` discussion thread, and the `code:` note attached to *Assess danger*. |
| 3 | `heatmap.png` | 3 — *Town life* (`y ≈ 1900`) | press <kbd>A</kbd> to toggle the complexity heatmap | All 16 entities visible: 5 NPCs (Baker, Smith, Innkeeper, Guard, Priest), 5 workplaces, 3 shared spaces (Market / Square / Well), 3 events (Festival, Bandit raid, Trade day). The most-connected NPCs (Priest, Guard) and events (Festival) glow as hot nodes. |
| 4 | `jump-labels.png` | 3 — *Town life* (`y ≈ 1900`) | press <kbd>Ctrl</kbd>+<kbd>J</kbd> to enter jump mode | The same town ecosystem with one- or two-character jump labels overlaid on every visible NPC, location, and event. |

All four shots come from one file, so any later format/feature change
re-renders them in one place.

## Theming and sizing

- Light theme by default; dark variants welcome but optional.
- Aim for ~1600 px wide. The Material theme will downscale on smaller
  screens.

## Wiring an image into the page

Once a PNG is in `docs/assets/screenshots/`, replace the matching
`<div class="grafli-screenshot">…</div>` block in `docs/index.md` with:

```markdown
![alt text](assets/screenshots/hero.png)
```
