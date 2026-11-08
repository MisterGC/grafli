// The mouse in a grafli serve tab, for everyone with an edit link — no keys
// to learn:
//
//   click          select (a box with a level opens it after a moment,
//                  unless a second click makes it a double-click)
//   double-click   rename the box, note or arrow
//   drag           move a box, note or image; it goes into the box you let
//                  go over, as a drop in the app does
//   drag an edge   from near a box's border: an arrow to the box you let
//                  go over
//   right-click    a Q: question, typed in place: beside a box, or at the
//                  point on the canvas or in a container
//
// Dragging the empty canvas still pans. Each edit goes through the same
// merge as the keys' and shows its placeholder until its frame is drawn. A
// watch link's tab selects with a click and says the rest needs the edit
// link; the laser (k) points instead of dragging.
(() => {
  "use strict";
  const page = window.grafliPage, live = window.grafliLive, edit = window.grafliEdit;
  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  const stage = $("stage");
  const MOVE_PX = 4;          // a press that moves less is a click
  const EDGE_PX = 10;         // how near a border a drag connects
  const LEVEL_MS = 400;       // a level opens this long after a lone click
  const NOTE_GAP = 20;        // a question goes this far beside a box
  const NOTE_W = 220, NOTE_H = 44;

  const preview = document.createElementNS(SVGNS, "g");
  preview.id = "drag";
  $("live-marks").appendChild(preview);

  let press = null;           // {el, x, y, mode, moved, at}
  let levelTimer = 0;

  const editor = () => live.role() === "editor" || live.role() === "presenter";
  const placed = () => page.current().elements.filter((e) => e.rect);
  const lasering = () => stage.classList.contains("lasering");

  function el(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  function watching() {
    page.toast("This link is for watching; editing needs the edit link");
  }

  // Board units per screen pixel.
  function scale() {
    return page.view().w / Math.max(stage.getBoundingClientRect().width, 1);
  }

  function inside(r, p) {
    return p.x >= r[0] && p.x <= r[0] + r[2] && p.y >= r[1] && p.y <= r[1] + r[3];
  }

  // Whether board point *p* lies near the border of *e*'s rect: within
  // EDGE_PX on screen, and never more than a quarter of the box across.
  function nearEdge(e, p) {
    const r = e.rect, k = scale();
    const band = Math.min(EDGE_PX * k, Math.min(r[2], r[3]) / 4);
    return p.x - r[0] < band || r[0] + r[2] - p.x < band
      || p.y - r[1] < band || r[1] + r[3] - p.y < band;
  }

  function childrenOf(id) {
    return page.current().elements.filter((e) => e.parent === id);
  }

  // *e* and everything inside it, by the drawing's containers.
  function family(e) {
    const out = new Set([e.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const x of page.current().elements) {
        if (x.parent && out.has(x.parent) && !out.has(x.id)) { out.add(x.id); grew = true; }
      }
    }
    return out;
  }

  // The smallest box under board point *p*, leaving out the ids in *skip*;
  // with *containers*, only a box that holds something.
  function boxAt(p, skip, containers) {
    let best = null;
    for (const e of placed()) {
      if (e.kind !== "box" || (skip && skip.has(e.id)) || !inside(e.rect, p)) continue;
      if (containers && !childrenOf(e.id).length) continue;
      if (!best || e.rect[2] * e.rect[3] < best.rect[2] * best.rect[3]) best = e;
    }
    return best;
  }

  // The smallest box, note or image under *p* other than *from*.
  function endAt(p, from) {
    let best = null;
    for (const e of placed()) {
      if (e.id === from.id || !inside(e.rect, p)) continue;
      if (!best || e.rect[2] * e.rect[3] < best.rect[2] * best.rect[3]) best = e;
    }
    return best;
  }

  function centre(e) {
    return { x: e.rect[0] + e.rect[2] / 2, y: e.rect[1] + e.rect[3] / 2 };
  }

  // ── Press, drag, let go ──

  page.addPointerHook((e, target) => {
    if (!editor() || lasering() || !target || !target.rect) return false;
    clearTimeout(levelTimer);
    const p = page.toBoard(e.clientX, e.clientY);
    press = { el: target, x: e.clientX, y: e.clientY, start: p,
              mode: nearEdge(target, p) ? "connect" : "move", moved: false };
    stage.dataset.grab = press.mode === "connect" ? "edge" : "body";
    stage.setPointerCapture(e.pointerId);
    return true;
  });

  stage.addEventListener("pointermove", (e) => {
    if (!press) { hover(e); return; }
    const dx = e.clientX - press.x, dy = e.clientY - press.y;
    if (!press.moved && Math.hypot(dx, dy) < MOVE_PX) return;
    press.moved = true;
    stage.dataset.grab = press.mode === "connect" ? "connecting" : "moving";
    const p = page.toBoard(e.clientX, e.clientY);
    if (press.mode === "move") {
      const r = press.el.rect, k = scale();
      preview.replaceChildren(edit.ghostBox(
        [r[0] + dx * k, r[1] + dy * k, r[2], r[3]], press.el.label));
    } else {
      const a = centre(press.el), to = endAt(p, press.el);
      const g = el("g", { class: "ghost" });
      el("line", { x1: a.x, y1: a.y, x2: p.x, y2: p.y }, g);
      if (to) el("rect", { x: to.rect[0], y: to.rect[1], width: to.rect[2],
                           height: to.rect[3], rx: 6 }, g);
      preview.replaceChildren(g);
    }
  });

  function letGo(e, cancelled) {
    const pr = press;
    press = null;
    preview.replaceChildren();
    delete stage.dataset.grab;
    if (!pr || cancelled) return;
    if (!pr.moved) { click(pr.el); return; }
    const p = page.toBoard(e.clientX, e.clientY);
    if (pr.mode === "connect") {
      const to = endAt(p, pr.el);
      if (!to) { page.toast(`Let go over a box to connect '${pr.el.label}' to it`); return; }
      edit.send(live.edit({ op: "connect", from: pr.el.id, to: to.id }),
                edit.ghostLine(pr.el, to));
      return;
    }
    const k = scale(), r = pr.el.rect;
    const dx = (e.clientX - pr.x) * k, dy = (e.clientY - pr.y) * k;
    const moved = family(pr.el);
    const into = boxAt(p, moved, false);
    moved.delete(pr.el.id);
    edit.send(live.edit({ op: "move", id: pr.el.id, dx, dy,
                          parent: into ? into.id : "", carry: Array.from(moved) }),
              edit.ghostBox([r[0] + dx, r[1] + dy, r[2], r[3]], pr.el.label),
              () => page.selectId(pr.el.id));
  }

  stage.addEventListener("pointerup", (e) => letGo(e, false));
  stage.addEventListener("pointercancel", (e) => letGo(e, true));

  // A lone click selects at once; a level waits a moment, so a double-click
  // can rename the box instead of leaving for its board.
  function click(target) {
    if (target.level) {
      page.selectId(target.id);
      levelTimer = setTimeout(() => page.activate(target), LEVEL_MS);
    } else {
      page.activate(target);
    }
  }

  // What the pointer would do here: move (inside) or connect (at the edge).
  function hover(e) {
    const t = e.target.__el;
    if (!editor() || lasering() || !t || !t.rect) { delete stage.dataset.grab; return; }
    stage.dataset.grab = nearEdge(t, page.toBoard(e.clientX, e.clientY)) ? "edge" : "body";
  }

  stage.addEventListener("pointerleave", () => { if (!press) delete stage.dataset.grab; });

  // ── Double-click: rename what the first click selected ──

  stage.addEventListener("dblclick", (e) => {
    e.preventDefault();
    clearTimeout(levelTimer);
    if (!page.selectedEl()) return;
    if (!editor()) { watching(); return; }
    edit.rename();
  });

  // ── Right-click: a question ──

  stage.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    if (!page.current()) return;
    if (!editor()) { watching(); return; }
    const p = page.toBoard(e.clientX, e.clientY);
    const t = e.target.__el && e.target.__el.rect ? e.target.__el : null;
    let x = p.x, y = p.y, parent = "";
    if (t && t.kind === "box" && childrenOf(t.id).length) {
      parent = t.id;                      // in a container, at the point
    } else if (t) {
      // Beside a box, note or image, so it keeps its look and its label.
      x = t.rect[0] + t.rect[2] + NOTE_GAP;
      y = t.rect[1];
      parent = t.parent || "";
    } else {
      const c = boxAt(p, null, true);
      parent = c ? c.id : "";
    }
    const k = Math.max(scale(), 1);
    const r = [x, y, NOTE_W * k, NOTE_H * k];
    const spot = edit.ghostBox(r, "Q:");
    $("ghosts").appendChild(spot);
    edit.ask(r, "", "Your question · Enter drops it, Esc drops nothing", (text) => {
      spot.remove();
      if (!text.trim()) { page.toast("No question: nothing dropped"); return; }
      const op = { op: "comment", text, x, y };
      if (parent) op.parent = parent;
      edit.send(live.edit(op), edit.ghostBox(r, /^\s*(q|question)\s*:/i.test(text)
        ? text : `Q: ${text}`), (ack) => page.selectId(ack.touched));
    }, () => spot.remove());
  });

  window.grafliMouse = {
    pressing: () => (press ? { id: press.el.id, mode: press.mode, moved: press.moved } : null),
    preview: () => preview.children.length,
  };
})();
