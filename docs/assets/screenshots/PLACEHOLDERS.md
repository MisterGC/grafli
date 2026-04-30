# Screenshot checklist for the landing page

Each placeholder block on `docs/index.md` corresponds to one item below.
File names are suggestions — keep them descriptive and they'll render fine
when dropped in.

| # | Suggested file | What it should show |
|---|---|---|
| 1 | `hero.png` | Real grafli session: system architecture diagram with semantic edge chips, a code-mode note, and the focus filter active. Window chrome optional but nice. |
| 2 | `tour.gif` | 30-second screencast: launch grafli → `n` → label → `Ctrl+L` repeat → end with a four-box diagram. Aim for ≤ 5 MB. |
| 3 | `directional-creation.gif` | Spawn connected boxes via `Ctrl+h/k/l`. Show arrows snapping cleanly. |
| 4 | `format-split.png` | Side-by-side: `.grafli` source on the left, rendered diagram on the right; one edited line highlighted in both. |
| 5 | `annotations-collage.png` | One frame containing: a code-mode note, `T:` and `Q:` notes, three arrows with `call:` / `data:` / `risk:` chips, and a discussion thread (`AI:` / `Reviewer:`). |
| 6 | `jump-labels.png` | `Ctrl+J` jump-mode labels overlaid on every visible element. |
| 7 | `focus-and-heatmap.png` | Stacked panels: top = subgraph focus dimming unrelated boxes; bottom = complexity heatmap with hot nodes glowing. Two separate PNGs is fine too. |
| 8 | `share-export.png` or `.gif` | `Y` copying to clipboard, then `Ctrl+E` exporting SVG. A two-panel still also works. |

## Producing the screenshots

- Use the bundled examples (`examples/architecture.grafli`, `examples/demo-nesting.grafli`, etc.) as starting material so they're reproducible.
- Light theme by default; dark variants welcome but optional.
- Recommended canvas size: ~1600 px wide for stills; the Material theme will downscale on smaller screens.
- For GIFs, the `document-skills:slack-gif-creator` skill or `ffmpeg` produce reasonable sizes; aim for ≤ 5 MB per asset.

When you drop a real file in, replace the matching `<div class="grafli-screenshot">…</div>` block on `docs/index.md` with:

```markdown
![alt text](assets/screenshots/your-file.png)
```

The `.grafli-screenshot` placeholder boxes are styled to match the final image dimensions, so the layout won't shift when you swap them.
