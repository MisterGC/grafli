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
| 1 | `hero.png` | 1 — *Architecture* (`y ≈ 0`) | default | The four boxes (Web App / API Gateway / Order Service / PostgreSQL), the four labelled arrows including the `call:` and `data:` chips, and the attached `code:` note. |
| 2 | `annotations.png` | 2 — *Annotations* (`y ≈ 900`) | default | The four flow boxes, the three chip arrows (`call:`, `event:`, `risk:`), the dashed `verify:` arrow, the `T:` and `Q:` notes, the `AI:`/`Reviewer:` discussion thread, and the `code:` note. |
| 3 | `heatmap.png` | 3 — *System graph* (`y ≈ 1900`) | press <kbd>A</kbd> to toggle the complexity heatmap | All ~16 nodes visible; the `API` hub should glow as the hottest node. |
| 4 | `jump-labels.png` | 3 — *System graph* (`y ≈ 1900`) | press <kbd>Ctrl</kbd>+<kbd>J</kbd> to enter jump mode | One- or two-character jump labels overlaid on every visible element. |

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
