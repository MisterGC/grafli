// Reveal mode in a grafli serve tab: a prepared board shows the others only
// its title, and the presenter uncovers the rest in the order the talk takes.
//
//   V       reveal mode on (all but the title hidden from the others) / off
//   v       a jump label on every hidden element in view; type one to
//           reveal it, a container with what it holds
//   +       right after a reveal: also what an arrow connects it to
//
// The others' tabs get a drawing without the hidden elements, so nothing
// hidden reaches them; the present link's tab gets the same drawing and
// draws the hidden elements as faint dashed outlines over it. What is hidden
// lives in the server's memory only, never in the board file.
(() => {
  "use strict";
  const page = window.grafliPage, live = window.grafliLive, edit = window.grafliEdit;
  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  const stage = $("stage");

  const layer = document.createElementNS(SVGNS, "g");
  layer.id = "reveal-outlines";
  stage.insertBefore(layer, $("veil"));

  const chip = document.createElement("span");
  chip.id = "reveal-chip";
  chip.hidden = true;
  $("bar").appendChild(chip);

  let last = null;          // the element just revealed, for "+"

  const presenting = () => live.role() === "presenter";
  const reveal = () => { const b = page.current(); return b && b.reveal; };

  function el(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  // ── The presenter's faint outlines ──

  function draw() {
    const b = page.current(), on = presenting() && b && b.reveal;
    chip.hidden = !on;
    if (!on) { layer.replaceChildren(); return; }
    const n = b.reveal.hidden;
    chip.textContent = n ? `revealing · ${n} hidden` : "revealing · all shown";
    const nodes = [];
    for (const line of b.hidden_lines || []) {
      const g = el("g", { class: "hidden-el" });
      for (const d of line.paths) el("path", { d, class: "line" }, g);
      nodes.push(g);
    }
    const holders = new Set(b.elements.map((e) => e.parent).filter(Boolean));
    for (const e of b.elements) {
      if (!e.hidden || !e.rect) continue;
      const [x, y, w, h] = e.rect;
      const g = el("g", { class: "hidden-el", "data-id": e.id });
      el("rect", { x, y, width: w, height: h, rx: 6 }, g);
      // A container's label sits top left, clear of what it holds.
      const at = holders.has(e.id)
        ? { x: x + 12, y: y + 14, "text-anchor": "start", "font-size": 14 }
        : { x: x + w / 2, y: y + h / 2, "text-anchor": "middle",
            "font-size": Math.max(10, Math.min(16, h / 3)) };
      const t = el("text", at, g);
      t.textContent = e.label;
      nodes.push(g);
    }
    layer.replaceChildren(...nodes);
  }

  live.onFrame(draw);

  // ── Revealing ──

  function inView(r) {
    const v = page.view();
    return r[0] < v.x + v.w && r[0] + r[2] > v.x && r[1] < v.y + v.h && r[1] + r[3] > v.y;
  }

  function step(msg, said) {
    return live.request({ t: "reveal", ...msg }).then((ack) => {
      page.toast(said(ack));
      return ack;
    }).catch((err) => { page.toast(err.message); });
  }

  const left = (ack) => (ack.hidden ? ` · ${ack.hidden} still hidden` : " · nothing left hidden");

  function show(e, near) {
    last = near ? null : e;
    step({ do: "show", el: e.id, near }, (ack) => {
      const more = ack.revealed.length - 1;
      return (near ? `Revealed '${e.label}' and its neighbours` : `Revealed '${e.label}'`)
        + (more > 0 && !near ? ` with ${more} more` : "") + left(ack);
    });
  }

  function pick() {
    if (!reveal()) {
      page.toast("Reveal mode is off: Shift+V hides all but the title");
      return;
    }
    edit.pick("reveal",
      () => page.current().elements.filter((e) => e.hidden && e.rect && inView(e.rect)),
      (e) => show(e, false),
      "Nothing hidden in view");
  }

  function toggle() {
    last = null;
    if (reveal()) {
      step({ do: "stop" }, () => "Reveal mode off: everyone sees the whole board");
    } else {
      step({ do: "start" }, (ack) => `Reveal mode: the others see only the title`
        + ` · ${ack.hidden} hidden · v reveals`);
    }
  }

  const MODIFIERS = ["Shift", "Control", "Alt", "Meta", "CapsLock"];

  page.addKeyHook((e) => {
    const k = e.key;
    if (MODIFIERS.includes(k)) return false;
    const after = last;
    last = null;
    if (e.metaKey || e.ctrlKey || e.altKey) return false;
    if (k === "+" && after && presenting() && reveal()) { show(after, true); return true; }
    if (k !== "v" && k !== "V") return false;
    if (!presenting()) { page.toast("Revealing is for the present link's tab"); return true; }
    if (k === "V") toggle(); else pick();
    return true;
  });

  window.grafliReveal = {
    // Test hooks: whether this tab is in reveal mode, what it shows faint.
    on: () => Boolean(reveal()),
    hidden: () => (page.current() ? page.current().elements.filter((e) => e.hidden).map((e) => e.id) : []),
    outlines: () => Array.from(layer.querySelectorAll("[data-id]"), (n) => n.dataset.id),
  };
})();
