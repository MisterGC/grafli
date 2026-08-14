# Images

A board can carry pictures next to its boxes and notes: a screenshot pasted
from the clipboard, a diagram exported from another tool, a hand-maintained
SVG icon. Every picture is one `@ image` line holding a path — the file
itself stays a file, so it diffs, moves and is edited like the rest of the
board.

## Getting an image onto the board

* **Paste** — copy an image anywhere and press <kbd>p</kbd> (or
  <kbd>Alt</kbd>+click to place at a position). The clipboard bitmap is
  written into the board's `<stem>-res/` directory as
  `img-<timestamp>.png` and referenced from there.
* **Drag a file in** — drop an image file onto the canvas and it becomes an
  `@ image` element at the drop point. Raster formats (PNG, JPEG, …) and
  `.svg` both work.
* **Create an SVG in place** — press <kbd>i</kbd> and click where the mockup
  should sit. grafli writes a starter `.svg` into the vault, adds the
  element, and opens the file in your system app right away, so "this UI
  needs a mockup" is one keystroke from drawing. The starter shows a
  recognizable **SVG · TODO** placeholder carrying the board theme's colour
  palette as swatches — eyedrop them while drawing and the mockup fits the
  board it lands on (hovering a swatch names its `%token`). It is one group:
  delete it in a single click when the mockup is done.
  <kbd>Shift</kbd>+click stays in the mode, so you can
  place several mockups first and draw them one by one, each still clearly
  marked as not-yet-done on the board. An existing file is never
  overwritten — a fresh name is picked instead.

## Where the file lives

Dropping a file does not always copy it. The rule follows where the file
already is:

| The dropped file is… | grafli… |
|----------------------|---------|
| already under the board's directory tree | references it **in place**, by its path relative to the `.grafli` file |
| anywhere else | copies it into the board's `<stem>-res/` vault and references the copy |

So assets you keep next to the board — an `icons/` directory, an SVG in the
vault — stay where you put them and keep exactly one copy. Everything else is
pulled in, which keeps a board plus its vault a complete, copyable unit. An
identical copy already in the vault is reused rather than duplicated.

Paths in the file are always relative to the directory of the `.grafli` file
(see [File format](format.md#element-types)).

## Editing an SVG while the board is open

An SVG is rendered from its file every time it is painted, so it stays sharp
at any zoom and in exports. grafli also watches the files its images
reference: edit one in your editor, save, and the element updates on the
board within a second — no re-import, no reopening the board. Nothing else
moves, and your selection is kept.

To jump into that editor from the board, press <kbd>e</kbd> (or
double-click) on a selected image — the same gesture that edits a box's
label or a note's text, because an image's own content *is* its file. It
opens in whatever your system associates with it: set Inkscape as the
default for `.svg` and that is what you get. <kbd>Enter</kbd> is unrelated
to this — it opens the element's *attachment* (a markdown doc, a sub-board,
or a link), for images exactly as for boxes and notes.

That makes the useful loop:

1. Drop (or write) an SVG into the board's `<stem>-res/` directory.
2. Reference it from the board once.
3. Edit the SVG in place — by hand, from a drawing tool, or by asking an AI
   to rewrite it — and watch the board follow.

The same applies to raster files: re-export a PNG over the old one and the
board picks it up.

## Size and resize

A newly placed image is fitted into a 320×240 box — twice the default box
size, and as wide as a pasted image has always been. Vectors have no pixel
size worth honouring, so an SVG is scaled up or down to fit; a raster image
is only ever scaled **down**, since blowing it up past its pixels buys
nothing.

Select an image and drag its handles to resize:

* **Corner handles** keep the aspect ratio.
* <kbd>Shift</kbd>+drag on a corner frees it for a non-uniform resize.
* **Edge handles** stretch one axis.

The side opposite the handle you drag stays put. The size is stored on the
`@ image` line, so it survives an external edit of the image file.

## The frame

A raster image is painted with a subtle border by default — a paper-white
screenshot would otherwise bleed into the canvas. An `.svg` renders bare:
transparent vector art is meant to sit directly on the board (or inside a
colored parent box) without a stray rectangle around it.

To override the default, select the image and press <kbd>s</kbd> then
<kbd>e</kbd> — the same appearance overlay boxes, notes and connectors use —
and cycle the **Frame** row: *Auto* (the file type decides), *Frame*, or
*None*. The choice is stored on the `@ image` line as `!frame` / `!noframe`,
only when it deviates from the default.

## What an image can do

An image behaves like any other node: it can be nested with `>parent`,
connected with <kbd>Alt</kbd>+drag, and carry an attachment — press
<kbd>E</kbd> to open or create its
[Markdown resource](text-annotations.md#markdown-resources).
