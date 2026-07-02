# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **The AI skill is now a lean core plus on-demand references.** The bundled
  skill splits into an always-loaded `SKILL.md` (workflow, collaboration
  etiquette, common-mistakes checklist, syntax card) and `references/` files
  the agent opens when needed — full format tables, design principles
  (now covering semantic-zoom authoring, the depth ladder, and a quality bar),
  a much richer presenting guide (`~iso` scoped stops, text slides,
  container-as-slide, auto-flows, PDF/PPTX export incl. corporate templates),
  and a new **thinking-boards** reference (decision boards, tension maps,
  question landscapes, deliberate incompleteness). `grafli skill install`
  copies the whole directory, `check` compares versions, and bare
  `grafli skill` prints the full single-file build (`--core` for just the
  core). ([#108](https://github.com/MisterGC/grafli/issues/108))
- **`grafli diagnose` reports dropped lines as errors.** A malformed directive
  or misplaced modifier used to silently remove the element from the render;
  it now surfaces as a `parse-error` finding with the line number — the
  scariest AI/hand-edit failure class is machine-checkable.
  ([#109](https://github.com/MisterGC/grafli/issues/109))
- **Agent-support CLI.** `grafli inspect --json` reports resolved geometry
  (element bounds, container inner rects, sibling gaps, next free slot);
  `grafli render` gains `--focus <ids>`, `--bookmark <id>` and `--lod`
  (the zoomed-out semantic-zoom reading) for targeted verification; and
  `grafli export --check [--json]` dry-runs a deck and reports overloaded
  slides, dangling bookmark/step refs, and missing vault docs without
  writing the file. ([#110](https://github.com/MisterGC/grafli/issues/110))
- **Quotes inside labels.** Single-line quoted text (box/arrow/bookmark/flow
  labels, descriptions, note text, the footer) now supports the `\"` escape,
  and the serializer emits it — `@ box a "Say \"hi\"" …` round-trips.
  ([#110](https://github.com/MisterGC/grafli/issues/110))

### Changed
- **The Markdown editor is now [textli](https://github.com/MisterGC/textli), its
  own package.** The editor that grew inside grafli (zen writing surface, reading
  view, comments, suggestions) moved to a separate repository and is consumed as
  the [`textli-editor`](https://pypi.org/project/textli-editor/) dependency —
  same editor, same keys, now also installable standalone. The bundled copy and
  grafli's own `textli` console script are gone; the `textli` command now comes
  with the package.

### Added
- **The Markdown editor owns its help (<kbd>F1</kbd>).** The zen / `textli` editor
  now shows its own, up-to-date help — covering the reading view, comments, and
  suggestions — with <kbd>F1</kbd>, whether it's hosted in grafli or (soon) run
  standalone. grafli's canvas <kbd>F1</kbd> now covers only the diagram.
- **Suggestions (track changes) in the reading view.** Beyond comments, the zen /
  `textli` reading view now speaks the full [CriticMarkup](http://criticmarkup.com/)
  vocabulary — `{++insert++}`, `{--delete--}`, `{~~old~>new~~}` — rendered as
  track changes: removals wear a strong strike line, additions are in a subtle
  zen red. Step through with <kbd>]</kbd><kbd>s</kbd> / <kbd>[</kbd><kbd>s</kbd>
  and **accept** (<kbd>a</kbd>) / **reject** (<kbd>x</kbd>) each — advancing to the
  next decision — or all at once (<kbd>Shift</kbd>+<kbd>A</kbd> /
  <kbd>Shift</kbd>+<kbd>X</kbd>), with an animated swap and single-undo source
  edits. **Author** a change by selecting a
  span and pressing <kbd>s</kbd> (replace / delete / insert). <kbd>g</kbd><kbd>c</kbd>
  opens a changes overview jump-list; <kbd>p</kbd> toggles a clean preview of the
  accepted prose. Marks live inline in the Markdown, so AI-proposed edits
  round-trip through the file and git and are reviewed key-by-key instead of
  diff-hunted.
- **Adjustable editor width.** The textli / zen markdown editor's content column
  can now be widened or narrowed from the keyboard — <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>→</kbd>
  wider, <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>←</kbd> narrower,
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>↓</kbd> reset — alongside the existing
  font-size zoom (<kbd>Ctrl</kbd>+<kbd>+</kbd>/<kbd>-</kbd>/<kbd>0</kbd>). The
  preference persists across sessions.

## [0.4.0] - 2026-06-28

### Added
- **`textli` — standalone markdown editor.** Launch grafli's focused Zen
  editor on any file without the diagram app: `textli notes.md`. It's the same
  editor grafli uses for notes — vim-navigable, with the rendered reading view
  (⌘R) — now usable on its own. Autosaves while you edit (and creates the file
  on first save if it doesn't exist yet), so important states are captured via
  git/SCM rather than a manual save action. Open at a specific spot and in a
  chosen mode: `textli notes.md#design-decisions` scrolls to that heading, and
  `-r`/`--read` opens straight into the rendered reading view (default is the
  editable write view). The `path#heading-slug` form is a plain markdown
  fragment, so a grafli node can link to a precise location in a doc.
- **Inline comments in the reading view.** The zen editor's rendered view
  (<kbd>⌘R</kbd>) is now caret-based and vim-navigable, and you can comment on a
  span of text: select it in **visual mode** (<kbd>v</kbd> + motions), press
  <kbd>c</kbd>, and type the comment. Comments are stored inline in the Markdown
  as [CriticMarkup](http://criticmarkup.com/) (`{==span==}{>>comment<<}`) — they
  travel with the file and diff in git, no sidecar. The reading view keeps the
  prose the focus: the comment body is hidden and the span wears a subtle
  highlight; a comment surfaces only when you ask for it. Step between comments
  with <kbd>]c</kbd>/<kbd>[c</kbd>, <kbd>Enter</kbd> reveals & edits one inline
  (while editing, <kbd>Enter</kbd> saves, <kbd>⇧Enter</kbd> is a line break,
  <kbd>Esc</kbd> cancels), <kbd>⇧D</kbd> deletes it. You never type the markup by
  hand.
- **READ / WRITE mode flash.** Toggling the zen editor's rendered view
  (<kbd>⌘R</kbd>) briefly flashes a big, blocky **READ** or **WRITE** in the
  centre and fades it out — anchoring the change without needing a permanent
  mode indicator (the state is also legible from the styling).
- **Level-of-Detail / semantic zoom.** Zooming far out now simplifies the
  canvas instead of shrinking everything into unreadable mush:
  - **Containers collapse by their own size, smallest first** — like a map where
    a small town's label vanishes before a city's. Each container folds when
    *its own* children get too small to read on screen, so a small group doesn't
    wait on a large same-level sibling; a **cascade guarantee** still folds the
    innermost containers first and never folds a parent before a tile it would
    subsume. Folding triggers **a shade early** — while a fresh tile is still
    large enough to read at a comfortable size rather than only once its interior
    is already a thumbnail — and a container is **always fully detailed at 100%
    zoom** (aggregation is a zoom-*out* affordance). The zoom-out floor also
    **drops far enough to reach the coarsest top-level tile**, so the whole-board
    overview is always attainable. A collapsed container becomes a single tile —
    its counter-scaled headline (kept legible like a place name on a map, sized
    from the tile's **area** so a wide-flat tile still reads boldly, **wrapping
    across lines** and shrinking its font only if it would still overflow the
    tile) plus a child-count badge — and its children hide. Boundary-crossing
    arrows re-route to the tile; internal edges vanish.
  - **Every simplified node speaks one "there's content here" language.** A leaf
    whose label is too small keeps its colour and shows **skeleton bars** where
    the label was; a connector **label** hides once it drops below the same
    legibility floor (and its line redraws unbroken — no leftover gap).
  - **Notes are first-class nodes.** A notes-only container (a legend) collapses
    to a tile like any container; a standalone note that gets too small shows a
    **text marker** — its plate with skeleton bars and a semantic accent tick
    (task / question / info) — instead of vanishing; a note inside a collapsed
    container is subsumed into its tile. Images inside a collapsed container are
    subsumed too; a standalone image stays (a shrunk image is still a legible
    thumbnail).
  - A **parent-less cluster** (a connected, spatially-compact group of ≥3 loose
    nodes) collapses behind a concave **"bubble" hull** — a tight organic
    outline (Qt path unions, padding adapted to node size) labelled by its hub
    node and count, with outside arrows re-attaching to the outline. The hull
    peels on its **own legibility** (once every member's label is too small to
    read), the leaf-level twin of a container folding when its children shrink —
    including a cluster sitting **among already-collapsed peers** (boxes subsumed
    by a neighbouring tile no longer block it).
  - A hysteresis band keeps threshold crossings from flickering while you scrub
    the zoom.
  - Aggregated nodes (tiles and hulls) are **read-only** — you edit at full
    detail, reached by zooming in, toggling LoD off, or **double-clicking the
    tile/hull to fly into it**. (This also closes a desync where dragging a
    collapsed container would have left its children behind.)
  - LoD-generated proxies are **visually distinct from real elements**: tiles
    and hulls both carry an aggregation cue (stacked "notebook" edges / an
    offset shadow behind a solid outline). When an aggregate's members don't
    share a colour it renders **neutral grey** rather than borrowing one
    member's.
  - The **LoD state is surfaced**: a status-bar indicator (`◧ LoD` while
    summarizing, `LoD off` when toggled off), and the **minimap outlines the
    currently-collapsed regions** against its always-full-detail view.
  - **Aggregation tracks live edits.** Adding, deleting, connecting, moving or
    reparenting elements — and undo/redo — update the zoomed-out view
    immediately (a newly added cluster grows its hull without reopening the
    file), instead of reflecting only what was on the board at open time. The
    rebuild is debounced to gesture boundaries, so the canvas stays responsive.
    See issue #106.
  Toggle the whole thing with `⇧D` (on by default; off restores the
  uniform-shrink behaviour) — see issue #103. Ships with an
  `examples/lod-demo.grafli` board built to show it off.
- **Bookmarks & flows — guided tours of a graph.** Capture **bookmarks**
  (named viewpoints) and string them into **flows** — ordered, narrated tours
  that play in-app, present fullscreen, or export to slides. Both live in the
  `.grafli` file as plain-text v2 directives (`@ bookmark` / `@ flow`), so they
  diff in git and an agent can author them.
  - **Semantic bookmarks.** A bookmark frames a set of element *ids*, not raw
    coordinates, so it stays correct when the layout changes; an optional
    isolate mode renders only the framed items. Capture the current view with
    `gb` (logical / by selection) or `gB` (exact viewport); `gf` records a flow.
  - **Playback & present.** Step a flow manually or auto-play with per-step
    dwell times; `p` cycles paused → playing → looping; `F5` presents
    fullscreen with on-canvas captions. A dedicated **Flows** side-panel tab
    shows slide-card previews with inline editing, and a flow can be
    **auto-generated** from a node's neighbourhood.
  - **Export to PDF & PowerPoint.** Export a flow as a slide deck — a title
    slide plus one slide per stop, the step description as caption. Single-note
    steps export as **native, clickable text slides**; scoped steps render only
    their framed items. In-app buttons, or headless
    `grafli export <file> tour.pdf --flow <id>`. (PowerPoint export, including
    onto an existing template, is detailed below.)
- **Parse problems are surfaced, not swallowed.** When a line can't be
  interpreted (a malformed `@` directive, an unterminated `"""` note block) the
  parser still keeps it as a comment — but now *records* it and the app shows a
  warning toast on open/reload (`⚠ N lines couldn't be parsed (line …) — kept
  as comments`), and `grafli diagnose` reports each as an `error`. Previously a
  small AI/hand-edit syntax slip silently dropped the element from the diagram
  with no indication anything was wrong. A file that isn't a grafli board at all
  (e.g. a Markdown doc opened by mistake — no header, most lines unparseable) is
  recognised as such and reported plainly ("doesn't look like a grafli file")
  rather than as a board with N broken lines.
- **Running-build indicator in the status bar.** A small `branch@sha` (with `*`
  when the tree is dirty) for dev/editable checkouts — so it's obvious at a
  glance whether a relaunch actually picked up new code (a packaged install
  shows `vX.Y.Z` instead).
- **Over-long notes are capped on the canvas.** A note taller than ~12 lines
  is clipped to a readable height with a soft bottom fade and a clear
  `⌄ N more lines · double-click to open` pill — so a stray long note can't
  dominate the board, and it's obvious the full text lives in the editor
  (the note's clickable footprint is the displayed, capped area).
- **Zen Markdown editor: rendered reading view, simpler modes.** The editor
  now **opens ready to type** (no more read-only-on-open), and reading is a
  proper **rendered view** rather than read-only source: `⌘R` toggles between
  the source editor and a formatted Markdown render (headings, bold, lists,
  links), navigable with **vim keys** (`j`/`k`, `Ctrl+d`/`u`, `Ctrl+f`/`b`,
  `gg`/`G`). `⌘↵` expands the card to fill the window; `⌘.` toggles the
  section-focus dim (everything but the current paragraph — now **off by
  default**). The old `⌘W` read-only/write toggle is gone (redundant);
  `⌘P` print and `⌘±` font zoom stay. Doc-backed notes autosave (with a
  flush on close) and the source view’s help reflects the new keys.
- **Trackpad-native pan & zoom.** Two-finger trackpad scroll now **pans** the
  canvas (it used to zoom), pinch-to-zoom works via native gestures, and
  `Ctrl`/`⌘`+scroll zooms — matching how a modern canvas app behaves. The
  trackpad-vs-mouse distinction uses the gesture source, so **mouse wheels
  always zoom — including high-resolution / Bluetooth wheels** that emit
  pixel-precise deltas — now **proportional** to the scroll amount (partial
  and fast scrolls zoom smoothly instead of in fixed steps).
- **Zoom limits with rubber-band feedback.** Zoom is now bounded so you can't
  get lost: zoom-in caps at 500%, and zoom-out is content-aware (stops once the
  board fills ~30% of the viewport, so a small board never shrinks to a speck
  dwarfed by the minimap). Hitting a limit gives a tactile bounce plus a brief
  message ("Max zoom" / "Min zoom — ⇧Z to fit"). Applies to wheel, `+`/`-`,
  and the zoom animations alike.
- **Hero text size `~4xl` (+ short aliases).** A new top size tier (`~4xl`,
  60 pt) for full-page sketchnote titles, reachable as a `4XL` row in the text
  grid. The multi-x tiers now also accept the short modern aliases `~2xl` /
  `~3xl` / `~4xl` (for `~xxlarge` / `~xxxlarge` / `~xxxxlarge`); files keep
  whichever form you write.
- **Notes can drop their background plate (`!flat`).** A note can now render
  with no beige plate, so a hand-lettered title or header sits directly on the
  canvas — beige plate (default) or nothing, two states only. Choose it from
  the colour picker (style mode → `c`) on a note. Pairs naturally with the
  display-lettering flags below.
- **Display lettering for notes (`!outline` / `!shadow`).** Two new text-style
  flags turn a note into a hand-lettered sketchnote header: `!outline` draws
  hollow letters, `!shadow` adds drop-shadow depth, and they layer on `~size`
  and `!bold` — `~xxlarge !outline` for a big hollow title, `~xxlarge !bold
  !shadow` for a 3D one. Set them from the text grid (style mode → `t`): `o`
  toggles outline, `s` toggles shadow (notes only, alongside `Tab` for the
  font). No new render mode — just more text styling, true to grafli's
  plain-text nature.
- **Selected element highlighted on the minimap.** The currently selected
  box, note, or image now shows as an amber glow ring on the RTS-style
  minimap — a radar "blip" that locates your selection at a glance, even when
  it's scrolled off-screen.
- **Clickable task lists in markdown notes.** GitHub-style task checkboxes
  in a markdown note (`- [ ]` / `- [x]`) are now interactive: click anywhere
  on the line to tick or untick it — no editing markdown by hand. The toggle
  rewrites just that one checkbox in the note's source (a one-character diff),
  saves, and is a single undo step. A `[text](url)` link on the same line
  still opens on click; the rest of the line toggles.
- **Handwritten notes.** Notes now render in the bundled Patrick Hand face by
  default — a warmer, sketchnote feel — while box labels stay monospace
  (structure). `!mono` (and `code:` notes) keep the monospace face for code.
  Toggle a note's font with `Tab` in the text grid. (Restores the long-dormant
  `NOTE_FONT_FAMILY` / `"" vs mono` intent.) The style-mode text grid moved
  from `s` to `t` (`s` → `t` = "style → text").
- **Text emphasis + a type grid.** Box labels and notes can now be **bold**
  and/or *italic* (`!bold` / `!italic`, layered on `~size`) — the missing
  emphasis dimension for visual-note hierarchy. Set it visually from a text
  grid: **style mode → `t`** opens a size (rows) × style (Regular / Bold /
  Italic / Bold+Italic, columns) matrix with live preview — `hjkl` to move,
  `Enter` to confirm, `Esc` to cancel. Works on boxes and notes. Bold renders
  crisply on both faces: the monospace UI font bundles a real Bold weight,
  and the handwritten Patrick Hand face (which ships none) gets a
  painter-level faux-bold so its bold no longer reads as regular.
- **Visual vocabulary — glyph boxes & notes.** A box or note can carry a
  curated line icon via the `*name` sigil (e.g. `*bulb`, `*warning`,
  `*database`), with two placements: *fill* (`*bulb`) makes the glyph the
  body with the label as a caption — a framed concept node on a box, a
  borderless marker on a note; *lead* (`*lead:lock`) puts a small glyph left
  of the label, which stays primary — labeled items and flags on existing
  nodes. 16 monochrome icons (person, gear, cloud, database, warning, bulb,
  check, cross, money, clock, doc, lock, flag, star, link, question). Pick
  from a live-preview grid: **style mode → `i`** (`hjkl` to move, `Tab` to
  toggle fill ↔ lead, `Enter` to confirm, `Esc` to cancel), with a "none"
  cell to clear. Works on boxes and notes alike.
- **Visual colour picker with live preview.** In style mode, <kbd>c</kbd>
  opens a colour grid beside the selection: navigate the palette with
  <kbd>h</kbd><kbd>j</kbd><kbd>k</kbd><kbd>l</kbd> and the box(es) recolour
  live as you move, <kbd>Enter</kbd> commits (one undo step), <kbd>Esc</kbd>
  reverts. Replaces the blind <kbd>h</kbd>/<kbd>l</kbd> colour cycling;
  <kbd>j</kbd>/<kbd>k</kbd> still size text.
- **Five more node colours.** The palette gains `%clay`, `%teal`,
  `%rose`, `%forest` and `%plum` — muted red / teal / pink / deep-green /
  deep-purple tuned to the existing desaturated tokens — filling the gaps
  in the colour grid.
- **Smart alignment guides while dragging.** Free-moving a single box,
  note or image now snaps its edges and centres to nearby elements,
  drawing thin guide lines where they line up — Figma/Keynote-style —
  and works whether or not grid-snap is on (grid is the fallback on any
  axis alignment didn't already pin). Mode badges pop in with a subtle
  overshoot and deleted elements pop out where they were, so the canvas
  feels more tactile without adding any chrome. Multi-element drags keep
  their relative layout (alignment applies to single-selection drags).
- **RTS-style minimap.** The minimap reads like a tactical radar: the
  viewport indicator is now a camera box with corner brackets, the radar
  is framed by subtle HUD corner brackets and laid over a faint grid —
  drawn in the minimap's own muted-blue accent so it fits the rest of the
  palette. All static (no animation).
- **Typed vault attachments; markdown notes become doc-bodied** ([#95]).
  The single `&url` attachment grows explicit kinds: `&link:<url>`
  (opens externally — the only kind that may point outside the board),
  `&doc:<name>` (a markdown document in the board's `<stem>-res/`
  vault) and `&graph:<name>` (a sub-board in the vault). A doc attached
  to a *note* renders as its body — that is what a markdown note now
  is: `@ note arch 600,0 &doc` plus a pristine `arch.md`, so prose
  diffs line-by-line in git and agents can read/rewrite a note without
  touching the board. Inline `md:` notes keep parsing forever and
  auto-convert on first save (announced via toast); legacy `&url`
  values classify on load and normalize on save. Multiline inline
  notes now default to the `"""` block form. Doc lifecycle: deleting
  an element keeps its doc (with a hint), Shift+Delete removes the doc
  too (refusing while shared; undo restores body and file), and the
  new `grafli vault <file>` CLI lists referenced / missing /
  unreferenced docs with `--clean` / `--delete <name>` for explicit
  removal. External edits to vault docs live-reload via one
  consolidated watcher; `grafli diagnose` reports missing and
  unreferenced docs.
- **PowerPoint export onto an existing template.** The flow → `.pptx`
  export can now drop onto an existing `.pptx`, keeping its master,
  theme, fonts and slide size: the slide title fills the template's
  title placeholder, the diagram fits the body placeholder's region
  (respecting the template's header / footer / logo), and grafli's own
  chrome, footer and progress counter are dropped — the template
  supplies its own. The corporate look applies with no manual
  restyling. Existing slides in the template are stripped first, and the
  template's own page size is adopted (4:3 templates letterbox the
  diagram). In the app the **Flow PPTX** export offers it under *Use a
  template…* (with layout pickers); headless via `--template`,
  `--title-layout` and `--content-layout`. The exporter geometry is now
  page-size agnostic, shared by the from-scratch and template paths.
- **Inline vim-capable note editing** ([#66]). Editing a note (`e` /
  double-click) now opens a small vim editor in place on the canvas —
  the same keybindings as the full-window zen editor, without leaving
  the diagram. Opens in INSERT (type right away); `Esc` drops to NORMAL,
  a second `Esc` commits, `Shift+Esc` discards, clicking away commits.
  Markdown (`md:`) notes are syntax-highlighted while editing. The
  editor lives in a new dependency-clean `grafli.editor` package so the
  reusable widget can later move into a standalone editor project.
- **`E` opens the zen editor on a note's own text** ([#66]). For longer
  prose, `Shift+E` on a note now opens the full-window zen editor seeded
  with the note's text and writes the result straight back — instead of
  implicitly creating an attached markdown file. Boxes and images keep
  the attached-markdown behaviour.
- **Markdown-mode notes** ([#65]). A note whose first non-empty line is
  `md:` (or `markdown:`) renders its body as a small subset of
  GitHub-flavoured Markdown — headings, bullet / ordered / task lists,
  blockquotes, horizontal rules, fenced and inline code (on a muted
  plate), inline `**bold**` / `*italic*` / `~~strike~~`, and clickable
  `[text](url)` links. A sibling of code-mode: a formatted block on the
  same beige plate with near-black body text. Rendered via Qt's
  `QTextDocument` Markdown engine, so it honours `~size` / `~width` and
  drag-to-resize like other notes.
- **Resize a node by dragging its corners.** A selected box shows resize
  handles; dragging a corner scales the node — its size *and* its label — with
  <kbd>Shift</kbd> to lock the aspect ratio. Connector widths scale with node
  size too. (Replaces the earlier `!ratio` / `!fit` flag experiment.)
- **Drag a node onto another to nest it.** Dropping a box (or image) over
  another makes it a child at the cursor: the parent auto-grows to fit the drop
  with a live dashed preview, reserves its headline band, keeps children inside,
  and shrinks back when its last child leaves — so containment is a direct drag,
  not a syntax edit ([#73], [#74], [#75], [#76]).
- **Notes and images can be first-class graph nodes.** Connect a note or image
  with a real arrow and it joins the graph — traversable by `Alt`
  graph-navigation and auto-flows — rather than staying a decorative
  annotation. Connectors carry an explicit kind: in arrow style mode, `s` then
  `a` toggles annotation ↔ graph edge (sticky, so new connectors inherit the
  choice), and a graph-edge note no longer triggers the annotation-dimming
  spotlight ([#85]).
- **Fine-grained numeric text sizes.** Box and note `~size` accepts numeric
  point values, not just the named tiers, and container / parent boxes can take
  any size too (previously pinned small) ([#82]).
- **Image resize handles.** A selected image shows corner handles, making
  aspect-locked corner-drag resize discoverable ([#78]).
- **`gz` — focus, then fly back.** `gz` zooms to fit the current selection;
  press it again to return to the previous overview — a one-key
  overview → focus → overview loop.
- **Zoom anchors on the selection.** `+` / `-` now zoom centred on the current
  selection (falling back to the viewport centre when nothing is selected), so
  zooming keeps the thing you care about in view ([#69]).
- **Right-mouse-button pan.** Drag with the right mouse button to pan the
  canvas; the canvas context menu is suppressed so the drag isn't interrupted.
- **Snap grid with three modes.** The grid cycles off → visual → snap
  (remembered across restarts); snap points draw as small crosses ([#77]).
- **Resizable side panel.** The panel / canvas splitter is draggable (with a
  content-floor minimum) and its width persists across runs.
- **Window pins to the primary screen.** grafli opens on the primary display so
  a sleeping or disconnected external monitor can't swallow the window.
- **Clipboard paste prefers the fresher image.** Pasting compares grafli's
  internal copy buffer against the system clipboard and uses whichever is more
  recent, so an external screenshot isn't shadowed by a stale internal copy
  ([#81]).
- **Coordinates quantize to integers on save.** Element positions and sizes are
  written as whole pixels, so a moved box is a one-line diff instead of a wall
  of sub-pixel float noise — keeping `.grafli` files clean in git ([#20]).

### Fixed
- **Reading view scrolls back to the top after jumping to the end.** Pressing
  `G` to jump to the bottom of a long document in the rendered reading view, then
  scrolling up, could stop short of the beginning (only `gg` recovered it) — the
  Markdown layout was still being computed lazily, so the scroll range was an
  estimate. Entering the reading view now settles the layout up front, so jumps
  and scrolling work against the real document height immediately.
- **Opening a file reliably frames it and focuses the canvas.** A board could
  open off-screen (the on-open zoom-to-fit fired before the window had its real
  size, leaving the view at 1:1 near the origin) and the canvas didn't grab
  keyboard focus, so `M` / `⇧Z` did nothing until you clicked it — together
  reading as a frozen app on a blank canvas. The fit now defers past an unsized
  viewport and re-fits as the window reaches its real size, and the canvas takes
  focus the moment a buffer loads.
- **Reliable zoom-to-fit on load.** Opening a board now frames it correctly:
  the canvas scrollbars are hidden (a scrollbar toggling mid-`fitInView` used
  to shrink the viewport and throw the fit off), re-opening or
  single-instance-forwarding a file re-fits it instead of restoring a stale
  view, and images-only boards now fit too.
- **Lead-glyph box labels no longer overflow.** A box with a `*lead:` icon
  offset its label by the icon gutter but still wrapped at the full width, so
  long labels ran past the right edge. The wrap width now reserves the gutter.
- **Crisp flow / step previews on hi-dpi displays.** The Flows panel
  thumbnails were painted at logical resolution and upscaled by the
  display, reading blurry on Retina screens. They now render and scale
  in device pixels, get a hairline slide frame so each preview reads as
  a slide against the paper card, and step numbers no longer clip at
  two digits.
- **Sharper exported diagrams.** The PPTX diagram raster goes from 2x
  to 4x slide points (~288 DPI, on par with the PDF's 300), and all
  diagram rasters (PPTX, PDF, panel thumbnails, cover collage) now use
  smooth pixmap resampling like the canvas does — embedded screenshots
  no longer alias when scaled.
- **Text slides now size like playback frames them.** A text-slide note
  used to be typeset at a fixed point band (capped at 30 pt), so short
  notes floated small mid-slide instead of filling it like the zoomed
  note does in the app. Both the PDF and PPTX exporters (and the Flows
  panel thumbnails) now mirror playback's `fitInView` zoom: the note
  block is fitted into the slide's hero area and its font scaled by the
  same factor, capped at 60 pt; notes too dense for that keep the old
  shrink-to-fit band so nothing goes sub-readable. The parity fit lives
  in the shared slide-plan layer so both formats stay in lock-step.
- **Minimap notes are distinct and sized to the real note.** Notes now
  render scaled to their rendered dimensions (like boxes) instead of a
  fixed blue square, and draw as a light "card" with an accent-colored
  border and a few text lines — so they read as text at a glance, stay
  high-contrast against the panel, and keep their task / question /
  discussion colour.

## [0.3.0] - 2026-05-09

### Added
- **Notes auto-wrap to a width budget** ([#27]). Plain-text and code-mode
  notes now soft-wrap to **80 characters by default** — long
  AI-generated sentences flow onto multiple readable lines instead of
  running off the canvas. Explicit `\n`, blank lines, and leading
  indentation are preserved across wraps. Code-mode continuations use
  a two-space hanging indent so block structure stays visible.
- **Per-note width override** via `~width=N` modifier ([#28]) (placed after
  `~size`, before `!style`), e.g.
  `@ note n1 0,0 "..." ~small ~width=60`.
- **Drag-to-resize note width** ([#29]). The right edge of plain-text and
  code-mode notes is now a horizontal resize handle: hover shows
  `SizeHorCursor`, drag updates `wrap_chars` live and persists as
  `~width=N` on next save. Height auto-derives from the wrapped
  content.
- **Search (`/`) is now a dim-filter** ([#30]). Typing dims everything that
  doesn't match to 8% opacity so hits stand out across the canvas.
  `Tab` / `Shift+Tab` cycle between matches with an animated zoom and
  the selection follows; `Enter` dismisses the input but keeps the
  filter so you can pan/zoom around the highlighted set; `Esc`
  clears the filter. Matches search box label + id and note text
  (case-insensitive substring). The filter is mutually exclusive
  with focus / complexity / arrow-dim — opening one closes the
  others. The minimap now reflects the dimmed set so off-screen
  hits are still visible at a glance. The search input is a
  viewport overlay (drawn in viewport coordinates) so it stays put
  while you pan and zoom — earlier it was a scene item that scaled
  and scrolled away with the canvas. `/` also works on non-US
  layouts where typing the slash needs Shift+7.

### Changed
- **Zoom hotkeys redesigned** ([#31]). `z` now zooms *in* to the next step
  in `25% → 50% → 100% → 150%`, wrapping back to 25% after 150%.
  Works regardless of selection state. Direction is always "in",
  so a single keypress is predictable; if you ever need to go
  smaller you keep pressing until it wraps. `Shift+Z` zooms to fit
  the whole graph.
- **Search cycling pins zoom at 100%** ([#32]). Tabbing through search
  matches now lands at a consistent 100% zoom each time, so hits
  are easy to compare regardless of where the user was zoomed
  before. Previously the view fit each match individually,
  producing wildly different zoom levels per result.

### Fixed
- **Autoscroll fights leftward drags on oversize parents** ([#33]). The
  drag-autoscroll timer triggered whenever any edge of the dragged
  item was past a viewport-edge margin — for a parent box wider or
  taller than the viewport that was always true, so dragging left
  scrolled right. Autoscroll is now driven by the **cursor's**
  distance from the viewport edges, which is what reflects user
  intent. If the cursor leaves the viewport entirely mid-drag, the
  timer pauses rather than guessing direction.
- **`grafli render` clipped wide-and-short diagrams** ([#34]). Setting
  `QImage.setDevicePixelRatio(2)` *before* `QGraphicsScene.render(...)`
  with a null target rect made Qt drop most of the scene — the bug
  surfaced only for certain aspect ratios (LR pipelines like the new
  skill-pipeline diagram on `docs/ai.md` rendered to a near-blank PNG).
  The render path now passes an explicit pixel-extent target rect and
  defers the DPR setting until after the paint completes. Tall diagrams
  (e.g. the RPG-engine example) were also subtly affected; the fix
  produces complete renders for both shapes.

[#20]: https://github.com/MisterGC/grafli/issues/20
[#27]: https://github.com/MisterGC/grafli/issues/27
[#28]: https://github.com/MisterGC/grafli/issues/28
[#29]: https://github.com/MisterGC/grafli/issues/29
[#30]: https://github.com/MisterGC/grafli/issues/30
[#31]: https://github.com/MisterGC/grafli/issues/31
[#32]: https://github.com/MisterGC/grafli/issues/32
[#33]: https://github.com/MisterGC/grafli/issues/33
[#34]: https://github.com/MisterGC/grafli/issues/34
[#65]: https://github.com/MisterGC/grafli/issues/65
[#66]: https://github.com/MisterGC/grafli/issues/66
[#69]: https://github.com/MisterGC/grafli/issues/69
[#73]: https://github.com/MisterGC/grafli/issues/73
[#74]: https://github.com/MisterGC/grafli/issues/74
[#75]: https://github.com/MisterGC/grafli/issues/75
[#76]: https://github.com/MisterGC/grafli/issues/76
[#77]: https://github.com/MisterGC/grafli/issues/77
[#78]: https://github.com/MisterGC/grafli/issues/78
[#81]: https://github.com/MisterGC/grafli/issues/81
[#82]: https://github.com/MisterGC/grafli/issues/82
[#85]: https://github.com/MisterGC/grafli/issues/85
[#95]: https://github.com/MisterGC/grafli/issues/95

## [0.2.0] - 2026-05-05

### Added
- **AI skill bundled with the package.** `grafli/skills/grafli/SKILL.md`
  ships inside the wheel; extract via `grafli skill` (prints to stdout)
  or `grafli skill -o SKILL.md`. The skill teaches Claude Code,
  OpenCode, or Codex CLI agents how to author idiomatic `.grafli`
  files — format reference, planning loop, layout discipline,
  code-mode style guidance, common-mistakes checklist. Triggers only
  on explicit visualization requests so it doesn't pollute unrelated
  conversations.
- **`grafli render` CLI** — headless PNG / SVG render of a `.grafli`
  file without opening a window:
  `grafli render input.grafli output.png [--width N] [--padding N]`.
  Useful for docs-as-code workflows, snapshot tests, and skill
  iteration. Uses `QT_QPA_PLATFORM=offscreen` automatically.
- **"Pair with your AI" docs section** — README adds an install /
  usage block right after the screenshot. New `docs/ai.md` page
  covers the longer story (why a skill, what it triggers on, render
  workflow, graph + code-mode pattern). Fourth pillar added to the
  homepage *Why grafli* row.

### Fixed
- `examples/architecture.grafli` referenced an attached PNG that was
  never committed — the example now ships with its companion image
  so the diagram renders cleanly out of the box.

## [0.1.1] - 2026-05-03

### Fixed
- `RuntimeError: libshiboken: Internal C++ object … already deleted`
  when switching modes (via the side-panel buttons or `n` / `t` / `c`
  shortcuts) after a file open or scene reload. The floating mode
  badge's Python references survived the scene rebuild that auto-deletes
  their C++ counterparts; the next mode switch tried to remove the dead
  items. The badge cleanup is now defensive and the references are
  reset on `load_board`.

## [0.1.0] - 2026-05-03

First public release of grafli on PyPI.

### Added

#### Editing
- Modal editing — Select (`v`), Rect (`n`), Text (`t`), Connect (`c`).
  Click without modifier creates one element and exits to Select; hold
  `Shift` while clicking to stay in the create mode for rapid placement.
- **Ghost preview in create modes** — a semi-transparent box / note
  follows the cursor with prefilled placeholder text (*A Node* /
  *Some text …*). The placeholder also lands on the created element so
  the auto-opened editor is ready for type-replace.
- Style sub-mode (`s`) and dimension sub-mode (`d`) for color, size, and
  resize without leaving the keyboard.
- Directional creation — `Ctrl+h` / `Ctrl+k` / `Ctrl+l` spawn a connected
  neighbor box (with arrow); `o` / `O` create adjacent boxes below /
  above the selection.
- Smart arrow routing — edges snap to the nearest box boundary;
  bidirectional pairs merge automatically.
- Undo/redo with up to 50 history states; copy/paste with `y` / `p`.

#### Diagram primitives
- **Boxes** with labels, anchored placement, free nesting via `>parent`,
  and color/size sub-mode cycling.
- **Arrows** with directional, bidirectional, and headless operators
  (`->`, `<-`, `<->`, `--`), optional labels, and dashed/flat styles.
- **Notes** — free-form text blocks, optionally child of any box.
- **Color tokens** — `%primary`, `%secondary`, `%tertiary`, `%accent`,
  `%subtle`, `%muted`, plus arbitrary `#rrggbb` hex.

#### Annotations
- **Tasks** (`T:`) and **questions** (`Q:`) lead-prefixes render with
  distinct colors so review work is visible at a glance. Both prefixes
  are case-insensitive and accept long forms (`TODO:` / `todo:`,
  `QUESTION:` / `question:`); the rendered badge is normalised to the
  short form for visual consistency.
- **Threaded discussions** — multi-speaker notes (`AI:`, `Reviewer:`,
  arbitrary speaker names) format as conversation bubbles inside a
  single note.
- **Code-mode notes** — lines starting with `code:` render as a
  stylized pseudocode block for review-oriented diagrams:
    - The first body line is the **function signature**, rendered bold
      with a divider rule beneath. Indentation carries block structure;
      indent guides are drawn automatically. Trailing `:` on keywords
      is optional.
    - **Flow keywords** (blue, bold): `if`, `else`, `for`, `while`,
      `try`, `catch`, `return`, `call`, `await`, `emit`, `state`.
    - **Contract keywords** (red, bold): `pre`, `post`, `assert`,
      `verify`, `risk`, `err`. Reviewer's eye lands here first.
    - **Clickable `@path:line` refs** open the file at that line in the
      configured editor (`editor/command` setting; auto-detects `code` /
      `cursor` / `subl`; falls back to `QDesktopServices`).
    - **Italic, muted comments** with `# …`. Plain assignments
      (`out = []`) need no keyword. String / hex / number / boolean
      literals are tokenised as values.
- **Semantic edge-label prefixes** — `call:`, `data:`, `event:`,
  `state:`, `step:`, `verify:`, `owns:`, `depends:`, `risk:`, `note:`
  render as colored chips on arrows and tint the edge.
- **Markdown resources** — attach a markdown file to any element and
  edit it in a full-window zen editor with vim-style keybindings.
- **URLs** on any element — `W` to set, `Return` to open in browser.

#### Navigation
- Fuzzy **search** by label with `/`.
- **Jump labels** (`Ctrl+J`) overlay one- or two-character labels on
  every visible item; press the label to select.
- **Graph navigation** — hold `Alt` to see connector keys; chain hops
  along edges chord by chord.
- **Hierarchy traversal** — `gp` parent (zoom if needed), `F` first
  child, `Tab` / `Shift+Tab` cycle siblings; ancestry breadcrumb in
  the status bar.
- **Jumplist** — `Ctrl+O` / `Ctrl+I` for vim-style viewport history.
- **Sub-graflis** — link any node to a deeper diagram in its own file;
  click through and return.

#### Visualization
- **Subgraph focus** — `B` fades elements not reachable from the
  selection, cycling direction (all → forward → backward); `Shift+B`
  toggles 1-hop vs unlimited depth.
- **Complexity heatmap** (`A`) colors nodes by connectivity to surface
  refactoring candidates.
- **Arrow dimming** (`,`) fades arrows for label-first reading.
- **Note dimming** (`Shift+N`) fades notes and their connector arrows
  to 8% opacity so the bare graph reads cleanly.
- **Minimap** (`M`) toggles a corner overview showing boxes, notes,
  and connector density.
- **Tools panel** (`\`) toggles the side panel; the *View* section
  also exposes the three view-toggles (notes, edges, complexity) as
  buttons.
- **Auto-layout** (`=`) lays out the selection or the whole diagram.

#### File format
- Plain-text `.grafli` v1 — line-oriented, one element per line, with
  `#` comments and a `#!grafli v1` header.
- **Triple-quoted note blocks** for multi-line text and notes
  containing quote characters; the serializer auto-promotes single-line
  notes that contain quotes.
- **External edit watching** — changes from your editor reload
  automatically.
- **Auto-save** — changes persist within 300 ms.

#### Export & sharing
- **Yank as PNG** (`Y`) — copy the diagram to the clipboard.
- **SVG export** (`Ctrl+E`) — clean vector output.
- **Buffers** — `Ctrl+K` to switch, `Ctrl+6` to toggle last, `Q` to
  close.

#### Tooling
- In-app **F1 cheat sheet** with live filter and a Text Annotations
  reference tab.
- **Documentation site** (MkDocs Material) at
  <https://grafli.mistergc.dev>.

### Requirements
- Python 3.12+
- PySide6 (Qt 6.7+)

[Unreleased]: https://github.com/MisterGC/grafli/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/MisterGC/grafli/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/MisterGC/grafli/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/MisterGC/grafli/releases/tag/v0.2.0
[0.1.1]: https://github.com/MisterGC/grafli/releases/tag/v0.1.1
[0.1.0]: https://github.com/MisterGC/grafli/releases/tag/v0.1.0
