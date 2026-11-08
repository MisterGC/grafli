// Ask the board's agent about the selection, in a grafli serve tab with an
// edit or present link:
//
//   ✦ ask   the chip beside the selected element; click it, or
//   a       with something selected
//
// Either opens a field over the element: type the request, Enter sends it
// to the agent — the Claude Code session the presenter connected — with the
// element it is about; its answer comes back as an edit on the board. With
// no agent connected, or one that is gone, the tab says so and sends
// nothing.
(() => {
  "use strict";
  const page = window.grafliPage, live = window.grafliLive, edit = window.grafliEdit;
  const $ = (id) => document.getElementById(id);
  const stage = $("stage"), wrap = $("stage-wrap");

  const chip = document.createElement("button");
  chip.id = "ask";
  chip.type = "button";
  chip.hidden = true;
  chip.textContent = "ask";
  wrap.appendChild(chip);

  let asking = false;        // the field is open for a request

  const editor = () => live.role() === "editor" || live.role() === "presenter";
  const agent = () => (window.grafliPresence && window.grafliPresence.agent()) || null;
  const scale = () => page.view().w / Math.max(stage.getBoundingClientRect().width, 1);

  // Board units → pixels in the stage wrap.
  function toScreen(x, y) {
    const m = stage.getScreenCTM(), w = wrap.getBoundingClientRect();
    const p = new DOMPoint(x, y).matrixTransform(m);
    return { x: p.x - w.left, y: p.y - w.top };
  }

  // Where *e* is, as a rect in board units: an arrow's is a small one
  // around its middle.
  function rectOf(e) {
    if (e.rect) return e.rect;
    const n = Array.from($("hits").children).find((h) => h.__el && h.__el.id === e.id);
    if (!n) return null;
    const p = n.getPointAtLength(n.getTotalLength() / 2), k = scale();
    return [p.x - 80 * k, p.y - 12 * k, 160 * k, 24 * k];
  }

  // Why nothing can be asked now, or null when the agent is here.
  function notHere() {
    const a = agent();
    if (!a) return "No agent is connected, so nothing is asked; the presenter "
      + "connects a Claude Code session with /mcp__grafli__connect";
    if (!a.present) return `${a.name} is gone, so nothing is asked; the presenter `
      + "connects a session again";
    return null;
  }

  function place() {
    const e = page.selectedEl();
    const r = e && rectOf(e);
    chip.hidden = !r || asking || !editor() || !!(edit.jump && edit.jump());
    if (chip.hidden) return;
    const a = agent(), away = notHere();
    chip.dataset.off = away ? "1" : "";
    chip.title = away || `Ask ${a.name} about this (a)`;
    const at = toScreen(r[0] + r[2], r[1]);
    chip.style.left = Math.round(at.x + 6) + "px";
    chip.style.top = Math.round(at.y - 26) + "px";
  }

  function start() {
    const e = page.selectedEl();
    if (!e) { page.toast("Select something to ask about (f, then its label)"); return; }
    const away = notHere();
    if (away) { page.toast(away); return; }
    const r = rectOf(e);
    if (!r) return;
    const name = agent().name;
    const label = (e.text !== undefined ? e.text : e.label) || e.id;
    const short = label.split("\n")[0].slice(0, 40);
    asking = true;
    place();
    edit.ask(r, "", `Ask ${name} about '${short}' · Enter sends, Esc closes`, (text) => {
      asking = false;
      place();
      if (!text.trim()) { page.toast("Nothing asked"); return; }
      edit.askAgent(text.trim(), e.id).catch(() => {});
    }, () => { asking = false; place(); });
  }

  chip.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  chip.addEventListener("click", (ev) => { ev.preventDefault(); start(); });

  page.onSelect(place);
  page.onView(place);
  live.onFrame(() => place());
  live.on("peers", () => place());
  live.on("welcome", () => place());
  window.addEventListener("resize", place);

  page.addKeyHook((e) => {
    if (e.key !== "a" || e.metaKey || e.ctrlKey || e.altKey) return false;
    if (!editor()) return false;
    if (!page.selectedEl()) return false;
    start();
    return true;
  });

  window.grafliAsk = {
    // The chip as shown: {off: no agent to ask, title}, or null when hidden.
    chip: () => (chip.hidden ? null : { off: chip.dataset.off === "1", title: chip.title }),
    start,
  };
})();
