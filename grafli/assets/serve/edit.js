// The presenter's keys in a grafli serve tab, the app's letters:
//
//   f       jump: a label on every element in view, type one to select it
//   o / O   a new box below / above the selection, connected from it
//           (Ctrl+arrow: on that side); type its label, Enter
//   c       connect: type the label of the box to connect the selection to
//           (with nothing selected, first the one to start from)
//   e       rename the selection;  x / Delete  delete it
//   u       undo your last edit (also Cmd/Ctrl+Z)
//   :       a command line: a grafli line, e.g. @ box cache "Cache", is
//           applied; anything else is plain language for the board's agent
//           (the Claude Code session the presenter connected). Without
//           one connected the line says so and nothing is sent.
//
// Every edit shows a placeholder on the board until the frame that holds it
// is drawn. A watch link's tab only gets f; a present link's tab gets them
// all, as an edit link's does.
(() => {
  "use strict";
  const page = window.grafliPage, live = window.grafliLive;
  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  const stage = $("stage"), wrap = $("stage-wrap");
  // The app's jump keys and gap beside a box (grafli.view.navigation,
  // grafli.serve.ops.BESIDE_GAP); the app's new box size.
  const KEYS = "asdfjklghqweruioptyzxcvbnm";
  const GAP = 40, NEW_W = 160, NEW_H = 80;
  const SIDES = { ArrowDown: "below", ArrowUp: "above",
                  ArrowRight: "right", ArrowLeft: "left" };

  const marks = document.createElementNS(SVGNS, "g");
  marks.id = "live-marks";
  const ghosts = document.createElementNS(SVGNS, "g");
  ghosts.id = "ghosts";
  const jumpLayer = document.createElementNS(SVGNS, "g");
  jumpLayer.id = "jump";
  marks.append(ghosts, jumpLayer);
  stage.appendChild(marks);

  const field = document.createElement("input");
  field.id = "live-field";
  field.type = "text";
  field.hidden = true;
  field.autocomplete = "off";
  field.spellcheck = false;
  wrap.appendChild(field);

  const cmd = document.createElement("form");
  cmd.id = "cmdline";
  cmd.hidden = true;
  cmd.innerHTML = '<span>:</span><input type="text" autocomplete="off" '
    + 'spellcheck="false" placeholder="@ box cache &quot;Cache&quot;, or plain '
    + 'language   ·   Enter sends, Esc closes"><small id="cmd-route"></small>';
  wrap.appendChild(cmd);
  const cmdInput = cmd.querySelector("input");
  const cmdRoute = cmd.querySelector("#cmd-route");
  const history = [];
  let historyAt = 0;

  let jump = null;        // {purpose, from, map, prefix[, targets, done, none]}
  let fieldDone = null;   // what Enter in the field does
  let fieldCancel = null;
  let waiting = [];       // placeholders waiting for {g, version}

  const editor = () => live.role() === "editor" || live.role() === "presenter";
  const board = () => page.current();
  const scale = () => page.view().w / Math.max(stage.getBoundingClientRect().width, 1);

  function el(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  // ── Where things are ──

  function arrowNode(e) {
    return Array.from($("hits").children).find((n) => n.__el && n.__el.id === e.id);
  }

  function centreOf(e) {
    if (e.rect) return { x: e.rect[0] + e.rect[2] / 2, y: e.rect[1] + e.rect[3] / 2 };
    const n = arrowNode(e);
    if (!n) return null;
    const p = n.getPointAtLength(n.getTotalLength() / 2);
    return { x: p.x, y: p.y };
  }

  function inView(p) {
    const v = page.view();
    return p.x >= v.x && p.x <= v.x + v.w && p.y >= v.y && p.y <= v.y + v.h;
  }

  function rectInView(r) {
    const v = page.view();
    return r[0] < v.x + v.w && r[0] + r[2] > v.x && r[1] < v.y + v.h && r[1] + r[3] > v.y;
  }

  // Board units → pixels in the stage wrap.
  function toScreen(x, y) {
    const m = stage.getScreenCTM(), w = wrap.getBoundingClientRect();
    const p = new DOMPoint(x, y).matrixTransform(m);
    return { x: p.x - w.left, y: p.y - w.top };
  }

  // Where the server puts a box beside *anchor* (grafli.serve.ops._beside),
  // from the drawn rects: the placeholder lands where the box will.
  function besideRect(anchor, side, w, h) {
    const a = anchor.rect;
    const step = { below: [0, a[3] + GAP], above: [0, -(h + GAP)],
                   right: [a[2] + GAP, 0], left: [-(w + GAP), 0] }[side];
    const stride = { below: [0, h + GAP], above: [0, -(h + GAP)],
                     right: [w + GAP, 0], left: [-(w + GAP), 0] }[side];
    const parent = anchor.parent || "";
    const others = board().elements.filter((e) => e.rect && e.kind !== "note"
      && (e.parent || "") === parent && e.id !== parent);
    let x = a[0] + step[0], y = a[1] + step[1];
    for (let i = 0; i < 64; i++) {
      const hit = others.some((o) => x < o.rect[0] + o.rect[2] && o.rect[0] < x + w
        && y < o.rect[1] + o.rect[3] && o.rect[1] < y + h);
      if (!hit) break;
      x += stride[0]; y += stride[1];
    }
    return [x, y, w, h];
  }

  function newBoxRect(side) {
    const sel = page.selectedEl();
    if (sel && sel.rect) {
      const [w, h] = sel.kind === "box" ? [sel.rect[2], sel.rect[3]] : [NEW_W, NEW_H];
      return besideRect(sel, side, w, h);
    }
    const v = page.view();
    return [v.x + v.w / 2 - NEW_W / 2, v.y + v.h / 2 - NEW_H / 2, NEW_W, NEW_H];
  }

  // ── Placeholders: drawn at once, gone when the frame with the edit is ──

  function ghostBox(r, label) {
    const g = el("g", { class: "ghost" });
    el("rect", { x: r[0], y: r[1], width: r[2], height: r[3], rx: 6 }, g);
    const t = el("text", { x: r[0] + r[2] / 2, y: r[1] + r[3] / 2,
                           "font-size": Math.min(16, r[3] / 3) }, g);
    t.textContent = label || "";
    return g;
  }

  function ghostLine(a, b) {
    const g = el("g", { class: "ghost" });
    const p = centreOf(a), q = centreOf(b);
    if (p && q) el("line", { x1: p.x, y1: p.y, x2: q.x, y2: q.y }, g);
    return g;
  }

  // Over an element that is being renamed (with its new label) or deleted.
  function ghostOver(e, label, gone) {
    const g = el("g", { class: "ghost" + (gone ? " gone" : "") });
    if (e.rect) {
      el("rect", { x: e.rect[0], y: e.rect[1], width: e.rect[2], height: e.rect[3], rx: 6 }, g);
    } else {
      const n = arrowNode(e);
      if (n) el("path", { d: n.getAttribute("d"), class: "line" }, g);
    }
    const c = centreOf(e);
    if (label !== undefined && c) {
      const t = el("text", { x: c.x, y: c.y, "font-size": 16 * Math.max(scale(), 0.6) }, g);
      t.textContent = label;
    }
    return g;
  }

  // Send *request*; *g* (a placeholder or null) stays until the frame that
  // shows the edit is drawn. *after* gets the ack.
  function send(request, g, after) {
    if (g) ghosts.appendChild(g);
    request.then((ack) => {
      if (g) {
        if (ack.version == null || live.version() >= ack.version) g.remove();
        else waiting.push({ g, version: ack.version });
      }
      if (ack.conflicts && ack.conflicts.length) {
        page.toast(`Kept the newer change to ${ack.conflicts.map((c) => c.key).join(", ")}`);
      }
      if (after) after(ack);
    }).catch((err) => {
      if (g) g.remove();
      page.toast(err.message);
    });
  }

  live.onFrame((m) => {
    waiting = waiting.filter((w) => {
      if (m.version < w.version) return true;
      w.g.remove();
      return false;
    });
    if (jump) showJump();
    if (!field.hidden && fieldDone && fieldDone.follow) fieldDone.follow();
  });

  function selectTouched(ack) {
    page.selectId(ack.touched);
    const e = page.selectedEl();
    if (e && e.rect) page.reveal(e.rect);
  }

  // ── Jump labels ──

  function jumpTargets() {
    if (jump.targets) return jump.targets();
    const b = board(), from = jump.from;
    const placed = b.elements.filter((e) => e.rect && rectInView(e.rect)
      && (!from || e.id !== from.id));
    if (jump.purpose !== "select") return placed;
    const arrows = b.elements.filter((e) => !e.rect && e.paths)
      .filter((e) => { const c = centreOf(e); return c && inView(c); });
    return [...placed, ...arrows];
  }

  function labelsFor(n) {
    if (n <= KEYS.length) return Array.from(KEYS.slice(0, n));
    const out = [];
    for (let i = 0; i < n; i++) {
      out.push(KEYS[Math.floor(i / KEYS.length) % KEYS.length] + KEYS[i % KEYS.length]);
    }
    return out;
  }

  function startJump(purpose, from, extra) {
    jump = { purpose, from: from || null, map: new Map(), prefix: "", ...extra };
    showJump();
    if (!jump) return;
    if (purpose === "connect") {
      page.toast(jump.from ? `Connect '${jump.from.label}' to… (type its label)`
                           : "Connect from… (type a label)");
    }
  }

  function showJump() {
    const targets = jumpTargets();
    if (!targets.length) {
      const none = jump.none
        || (jump.from ? "Nothing in view to connect to" : "Nothing in view");
      endJump();
      page.toast(none);
      return;
    }
    const labels = labelsFor(targets.length);
    jump.map = new Map(labels.map((l, i) => [l, targets[i]]));
    const k = scale(), size = 13 * k, pad = 3 * k;
    const nodes = [];
    jump.map.forEach((e, label) => {
      if (!label.startsWith(jump.prefix)) return;
      const at = e.rect ? { x: e.rect[0] + 4 * k, y: e.rect[1] + 4 * k } : centreOf(e);
      const g = el("g", { class: "jump-label" });
      const w = (label.length * 0.68 + 0.5) * size;
      el("rect", { x: at.x, y: at.y, width: w, height: size + 2 * pad, rx: 3 * k }, g);
      const t = el("text", { x: at.x + w / 2, y: at.y + pad + size / 2, "font-size": size }, g);
      t.textContent = label;
      nodes.push(g);
    });
    jumpLayer.replaceChildren(...nodes);
  }

  function endJump() {
    jump = null;
    jumpLayer.replaceChildren();
  }

  function jumpKey(e) {
    if (e.key === "Escape") { endJump(); return true; }
    if (e.key === "Backspace") {
      jump.prefix = jump.prefix.slice(0, -1);
      showJump();
      return true;
    }
    if (e.key.length !== 1 || e.metaKey || e.ctrlKey || e.altKey) return true;
    const prefix = jump.prefix + e.key;
    const hit = jump.map.get(prefix);
    if (hit) { picked(hit); return true; }
    if (Array.from(jump.map.keys()).some((l) => l.startsWith(prefix))) {
      jump.prefix = prefix;
      showJump();
    } else {
      endJump();
      page.toast(`No label '${prefix}'`);
    }
    return true;
  }

  function picked(target) {
    const { purpose, from, done } = jump;
    endJump();
    if (done) { done(target); return; }
    if (purpose === "select") { page.selectId(target.id); return; }
    if (!from) {
      page.selectId(target.id);
      startJump("connect", target);
      return;
    }
    send(live.edit({ op: "connect", from: from.id, to: target.id }),
         ghostLine(from, target));
  }

  // ── The text field: a label for a new box, a rename ──

  function openField(r, value, done, cancel) {
    // A field still open (the mouse can open a second one over it) is
    // cancelled first, so its placeholder goes with it.
    if (!field.hidden && fieldCancel) {
      const replaced = fieldCancel;
      fieldCancel = null;
      replaced();
    }
    const place = () => {
      const a = toScreen(r[0], r[1]), b = toScreen(r[0] + r[2], r[1] + r[3]);
      const w = Math.max(b.x - a.x, 160);
      field.style.left = (a.x + (b.x - a.x) / 2 - w / 2) + "px";
      field.style.top = (a.y + (b.y - a.y) / 2 - 16) + "px";
      field.style.width = w + "px";
    };
    done.follow = place;
    fieldDone = done;
    fieldCancel = cancel || null;
    field.value = value;
    field.hidden = false;
    place();
    field.focus();
    field.select();
  }

  function closeField() {
    field.hidden = true;
    field.placeholder = "";
    fieldDone = fieldCancel = null;
    field.blur();
  }

  field.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      const done = fieldDone, text = field.value;
      closeField();
      if (done) done(text);
    } else if (e.key === "Escape") {
      e.preventDefault();
      const cancel = fieldCancel;
      closeField();
      if (cancel) cancel();
    }
  });

  function newBox(side) {
    const anchor = page.selectedEl();
    const r = newBoxRect(side);
    const ghost = ghostBox(r, "");
    ghosts.appendChild(ghost);
    openField(r, "", (label) => {
      ghost.remove();
      if (!label.trim()) { page.toast("No label: no box"); return; }
      const op = anchor && anchor.rect
        ? { op: "add_box", label, beside: anchor.id, side, connect: true }
        : { op: "add_box", label, x: r[0], y: r[1] };
      send(live.edit(op), ghostBox(r, label), selectTouched);
    }, () => ghost.remove());
  }

  function rename() {
    const e = page.selectedEl();
    if (!e) { page.toast("Select something to rename (f, then its label)"); return; }
    if (e.kind === "image") { page.toast("An image has no label to rename"); return; }
    const text = e.text !== undefined ? e.text : e.label;
    if (text.includes("\n")) {
      page.toast(`'${e.label}' has several lines; edit it in the app`);
      return;
    }
    let r = e.rect;
    if (!r) {
      const c = centreOf(e);
      if (!c) return;
      r = [c.x - 80 * scale(), c.y - 12 * scale(), 160 * scale(), 24 * scale()];
    }
    openField(r, text, (label) => {
      if (label === text) return;
      send(live.edit({ op: "rename", id: e.id, label }), ghostOver(e, label, false),
           () => page.selectId(e.id));
    });
  }

  function remove() {
    const e = page.selectedEl();
    if (!e) { page.toast("Select something to delete (f, then its label)"); return; }
    send(live.edit({ op: "delete", id: e.id }), ghostOver(e, undefined, true),
         () => page.selectId(null));
  }

  function undo() {
    send(live.undo(), null, (ack) => {
      page.toast(ack.conflicts && ack.conflicts.length
        ? "Undone, but a later change by someone else stays" : "Undone");
    });
  }

  // ── The ':' command line ──

  // A grafli line starts with @, or reads like one without it: a kind, an
  // id and a quoted label (an arrow: an id and its arrow). Anything else is
  // plain language — "note the cache is slow" too.
  const LINE_RE = /^(@|(box|note|image)\s+[\w.-]+\s+"|arrow\s+[\w.-]+\s*(->|<-|<->|--))/;
  const isLine = (text) => LINE_RE.test(text.trim());
  const BOX_RE = /^@?\s*box\s+(\S+)\s+"((?:[^"\\]|\\.)*)"(.*)$/;
  const PLACE_RE = /^\s+-?[\d.]+,\s*-?[\d.]+\s+[\d.]+x[\d.]+/;

  // The agent as the last peers message gave it: {name, present}, or null
  // before any. Kept here, not read from presence.js, whose own peers
  // listener runs after this one.
  let seat = null;
  const agent = () => seat;

  // Where the text on the line goes, said beside it.
  function route() {
    const text = cmdInput.value.trim(), a = agent();
    const plain = !a ? "plain language: no agent connected"
      : a.present ? `plain language → ${a.name}`
      : `plain language: ${a.name} is gone`;
    const line = "grafli line → applied";
    cmdRoute.textContent = !text ? `${line} · ${plain}` : isLine(text) ? line : plain;
    cmdRoute.dataset.to = !text || isLine(text) ? "board"
      : a && a.present ? "agent" : "none";
  }

  cmdInput.addEventListener("input", route);
  live.on("peers", (m) => {
    seat = m.agent || null;
    if (!cmd.hidden) route();
  });

  // Send *text* to the board's agent, *about* an element id or null; the
  // server says whether a session took it. Nothing waits in the tab.
  function askAgent(text, about) {
    const msg = { t: "ask", text };
    if (about) msg.about = about;
    return live.request(msg).then((ack) => {
      const what = text.length > 48 ? text.slice(0, 47) + "…" : text;
      page.toast(`Asked ${ack.agent}: “${what}” · the answer comes to the board`);
      return ack;
    }).catch((err) => {
      const why = err.message;
      page.toast(why.charAt(0).toUpperCase() + why.slice(1));
      throw err;
    });
  }

  function openCommand() {
    cmd.hidden = false;
    cmdInput.value = "";
    historyAt = history.length;
    route();
    cmdInput.focus();
  }

  function closeCommand() {
    cmd.hidden = true;
    cmdInput.blur();
  }

  cmdInput.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Escape") { e.preventDefault(); closeCommand(); }
    else if (e.key === "Enter") { e.preventDefault(); runCommand(); }
    else if (e.key === "ArrowUp" && historyAt > 0) {
      e.preventDefault();
      cmdInput.value = history[--historyAt];
      route();
    } else if (e.key === "ArrowDown" && historyAt < history.length) {
      e.preventDefault();
      historyAt++;
      cmdInput.value = history[historyAt] || "";
      route();
    }
  });

  cmd.addEventListener("submit", (e) => { e.preventDefault(); runCommand(); });

  function runCommand() {
    const text = cmdInput.value.trim();
    closeCommand();
    if (!text) return;
    if (history[history.length - 1] !== text) history.push(text);
    if (!isLine(text)) {
      askAgent(text, null).catch(() => {});
      return;
    }
    const sel = page.selectedEl();
    const op = { op: "lines", text };
    if (sel && sel.rect) op.beside = sel.id;
    const v = page.view();
    op.x = v.x + v.w / 2;
    op.y = v.y + v.h / 2;
    let ghost = null;
    const m = BOX_RE.exec(text);
    if (m && !PLACE_RE.test(m[3])) {
      const old = board().elements.find((x) => x.id === m[1] && x.rect);
      ghost = old ? ghostOver(old, m[2], false)
        : ghostBox(sel && sel.rect
          ? besideRect(sel, "below", ...(sel.kind === "box" ? [sel.rect[2], sel.rect[3]] : [NEW_W, NEW_H]))
          : [op.x - NEW_W / 2, op.y - NEW_H / 2, NEW_W, NEW_H], m[2]);
    }
    send(live.edit(op), ghost, selectTouched);
  }

  // ── Keys ──

  function watching() {
    page.toast("This link is for watching; editing needs the edit link");
    return true;
  }

  page.addKeyHook((e) => {
    if (jump) return jumpKey(e);
    const k = e.key, mod = e.metaKey || e.ctrlKey;
    if (mod && !e.altKey && !e.shiftKey && (k === "z" || k === "Z")) {
      if (!editor()) return watching();
      undo();
      return true;
    }
    if (e.ctrlKey && !e.metaKey && !e.altKey && SIDES[k]) {
      if (!editor()) return watching();
      newBox(SIDES[k]);
      return true;
    }
    if (mod || e.altKey) return false;
    if (k === "f") { startJump("select"); return true; }
    if (!"ocexu:".includes(k) && k !== "O" && k !== "Delete") return false;
    if (!editor()) return watching();
    if (k === "o") newBox("below");
    else if (k === "O") newBox("above");
    else if (k === "c") {
      const sel = page.selectedEl();
      startJump("connect", sel && sel.rect ? sel : null);
    }
    else if (k === "e") rename();
    else if (k === "x" || k === "Delete") remove();
    else if (k === "u") undo();
    else if (k === ":") openCommand();
    return true;
  });

  // A click on the board ends a jump.
  stage.addEventListener("pointerdown", () => { if (jump) endJump(); }, true);

  window.grafliEdit = {
    // What the mouse gestures (mouse.js) build on.
    rename,
    send,
    ghostBox,
    ghostLine,
    // The text field over rect r, as for a label: done(text) on Enter.
    ask: (r, value, hint, done, cancel) => {
      field.placeholder = hint || "";
      openField(r, value, done, cancel);
    },
    // Jump labels on targets() (elements with a rect); done(element) for
    // the one whose label is typed, toast *none* when there are none.
    pick: (purpose, targets, done, none) => startJump(purpose, null, { targets, done, none }),
    jump: () => (jump ? { purpose: jump.purpose, labels: Array.from(jump.map.keys()) } : null),
    labelOf: (id) => {
      if (!jump) return null;
      for (const [l, e] of jump.map) if (e.id === id) return l;
      return null;
    },
    askAgent,
    isLine,
    ghosts: () => ghosts.children.length,
    field: () => (field.hidden ? null : field.value),
    command: () => !cmd.hidden,
    // Where the command line says its text goes, and "board", "agent" or
    // "none" for it.
    route: () => (cmd.hidden ? null : { text: cmdRoute.textContent, to: cmdRoute.dataset.to }),
  };
})();
