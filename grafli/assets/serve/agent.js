// The board's agent's edits in a grafli serve tab: what it changed glows in
// its colour for a moment, with its name, and a large change waits as its
// proposal until the presenter takes it or drops it.
//
//   U       undo the agent's last edit; what you and the others changed
//           since stays (present link only)
//   Enter   take the agent's proposal, while one waits (present link only)
//   x       drop it
//
// The proposal shows on the board as dashed outlines in the agent's colour:
// what it adds or changes where it would be, what it removes struck
// through. Nothing of it is in the board file until it is taken. These keys
// are asked before the editing keys, so x drops a waiting proposal instead
// of deleting the selection.
(() => {
  "use strict";
  const page = window.grafliPage, live = window.grafliLive;
  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  const stage = $("stage"), wrap = $("stage-wrap");
  const MARK_MS = 4000;      // how long an edit of the agent's glows

  const presenting = () => live.role() === "presenter";
  const scale = () => page.view().w / Math.max(stage.getBoundingClientRect().width, 1);

  function el(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  const proposalLayer = el("g", { id: "proposal-marks" });
  const markLayer = el("g", { id: "agent-marks" });
  stage.append(proposalLayer, markLayer);

  const banner = document.createElement("div");
  banner.id = "proposal";
  banner.hidden = true;
  wrap.appendChild(banner);

  // A tag's width, in pixels at 12px (#agent-marks .tag text).
  const ruler = document.createElement("canvas").getContext("2d");
  function textWidth(text) {
    ruler.font = '600 12px system-ui, -apple-system, "Segoe UI", sans-serif';
    return ruler.measureText(text).width;
  }

  // ── An edit of the agent's: it glows, with the agent's name ──

  let mark = null;          // {by, color, version, ids, timer}
  let marking = [];         // marks waiting for the frame that shows them

  function elementsOf(ids) {
    const b = page.current();
    if (!b) return [];
    const want = new Set(ids);
    return b.elements.filter((e) => want.has(e.id) && (e.rect || e.paths));
  }

  function showMark(m) {
    clearTimeout(mark && mark.timer);
    markLayer.replaceChildren();
    const found = elementsOf(m.ids);
    const k = scale(), nodes = [];
    let tagAt = null;
    for (const e of found) {
      const g = el("g", { class: "agent-glow", "data-id": e.id });
      g.style.setProperty("--agent", m.color);
      if (e.rect) {
        const [x, y, w, h] = e.rect, pad = 4 * k;
        el("rect", { x: x - pad, y: y - pad, width: w + 2 * pad, height: h + 2 * pad,
                     rx: 8 * k, class: "halo" }, g);
        el("rect", { x: x - pad, y: y - pad, width: w + 2 * pad, height: h + 2 * pad,
                     rx: 8 * k, class: "edge" }, g);
        if (!tagAt || y + h > tagAt.y) tagAt = { x: x - pad, y: y + h + pad };
      } else {
        for (const d of e.paths) {
          el("path", { d, class: "halo" }, g);
          el("path", { d, class: "edge" }, g);
        }
      }
      nodes.push(g);
    }
    if (!tagAt && found.length) {
      // Only arrows: the tag goes where the first one starts.
      const at = /M\s*(-?[\d.]+)[\s,]+(-?[\d.]+)/.exec(found[0].paths[0] || "");
      if (at) tagAt = { x: Number(at[1]), y: Number(at[2]) + 6 * k };
    }
    let tag = null;
    if (tagAt) {
      const text = `✦ v${m.version} · ${m.by}` + (presenting() ? " · U undo" : "");
      const g = el("g", { class: "agent-glow tag" });
      g.style.setProperty("--agent", m.color);
      const size = 12 * k, pad = 5 * k;
      el("rect", { x: tagAt.x, y: tagAt.y + 4 * k, rx: 4 * k,
                   width: textWidth(text) * k + 2 * pad, height: size + 2 * pad }, g);
      el("text", { x: tagAt.x + pad, y: tagAt.y + 4 * k + pad + size / 2,
                   "font-size": size }, g).textContent = text;
      nodes.push(g);
      tag = text;
    }
    markLayer.replaceChildren(...nodes);
    mark = { ...m, tag, shown: found.map((e) => e.id) };
    mark.timer = setTimeout(() => {
      markLayer.replaceChildren();
      mark = null;
    }, MARK_MS);
  }

  live.on("marked", (m) => {
    if (m.undone) page.toast(`${m.by} undid its last edit`);
    else {
      page.toast(`${m.by}: ${m.summary || "changed the board"}`
                 + (presenting() ? " · U undoes it" : ""));
    }
    if (m.version == null || live.version() >= m.version) showMark(m);
    else marking.push(m);
  });

  // ── The agent's proposal ──

  let proposal = null;      // as the server sent it, or null

  function drawProposal() {
    proposalLayer.replaceChildren();
    banner.hidden = !proposal;
    if (!proposal) return;
    const p = proposal;
    banner.style.setProperty("--agent", p.color);
    const what = document.createElement("span");
    const head = document.createElement("b");
    head.textContent = `✦ ${p.by} proposes ${p.count} changes`;
    what.append(head, ` · ${p.about || p.summary}`);
    const keys = document.createElement("span");
    keys.className = "keys";
    keys.textContent = presenting() ? "Enter take · x drop"
                                    : "the presenter takes it or drops it";
    banner.replaceChildren(what, keys);
    banner.title = p.summary;

    const nodes = [];
    const k = scale();
    const outline = (shape, cls) => {
      const g = el("g", { class: `proposed ${cls}`, "data-id": shape.id });
      g.style.setProperty("--agent", p.color);
      if (shape.rect) {
        const [x, y, w, h] = shape.rect;
        el("rect", { x, y, width: w, height: h, rx: 6 }, g);
        if (shape.label) {
          el("text", { x: x + w / 2, y: y + h / 2,
                       "font-size": Math.min(16 * Math.max(k, 0.6), h / 3) }, g)
            .textContent = shape.label;
        }
      } else {
        for (const d of shape.paths || []) el("path", { d, class: "line" }, g);
      }
      nodes.push(g);
    };
    // What goes: struck through where it is now.
    for (const e of elementsOf(p.removed || [])) {
      const g = el("g", { class: "proposed gone", "data-id": e.id });
      if (e.rect) {
        const [x, y, w, h] = e.rect;
        el("rect", { x, y, width: w, height: h, rx: 6 }, g);
        el("line", { x1: x + 8, y1: y + h / 2, x2: x + w - 8, y2: y + h / 2 }, g);
      } else {
        for (const d of e.paths) el("path", { d, class: "line" }, g);
      }
      nodes.push(g);
    }
    for (const s of p.changed || []) outline(s, "changed");
    for (const s of p.added || []) outline(s, "added");
    proposalLayer.replaceChildren(...nodes);
  }

  live.on("welcome", () => { proposal = null; drawProposal(); });
  live.on("proposal", (m) => {
    const had = proposal;
    proposal = m.proposal || null;
    const fresh = proposal && (!had || had.id !== proposal.id);
    if (fresh) {
      page.toast(`${proposal.by} proposes ${proposal.count} changes`
                 + (presenting() ? ": Enter takes it, x drops it" : ""));
    }
    drawProposal();
    // The presenter's camera goes to it; the tabs following go along.
    if (fresh && presenting()) {
      const rects = [...(proposal.added || []), ...(proposal.changed || []),
                     ...elementsOf(proposal.removed || [])]
        .map((s) => s.rect).filter(Boolean);
      if (rects.length) {
        const x = Math.min(...rects.map((r) => r[0])), y = Math.min(...rects.map((r) => r[1]));
        const x2 = Math.max(...rects.map((r) => r[0] + r[2]));
        const y2 = Math.max(...rects.map((r) => r[1] + r[3]));
        page.reveal([x, y, x2 - x, y2 - y]);
      }
    }
  });

  live.onFrame(() => {
    if (proposal) drawProposal();
    const due = marking.filter((m) => live.version() >= m.version);
    marking = marking.filter((m) => live.version() < m.version);
    if (due.length) showMark(due[due.length - 1]);
  });
  page.onView(() => { if (proposal) drawProposal(); });

  function settle(doing) {
    const p = proposal;
    live.request({ t: "proposal", do: doing, proposal: p.id }).then((ack) => {
      if (doing === "drop") page.toast(`Dropped ${p.by}'s proposal`);
      else {
        page.toast(ack.conflicts && ack.conflicts.length
          ? `Took ${p.by}'s proposal; a later change by someone else stays`
          : `Took ${p.by}'s proposal`);
      }
    }).catch((err) => page.toast(err.message));
  }

  function undoAgent() {
    live.request({ t: "undo", of: "agent" }).then((ack) => {
      const who = (window.grafliPresence && window.grafliPresence.agent()) || null;
      const name = who ? who.name : "the agent";
      page.toast(ack.conflicts && ack.conflicts.length
        ? `Undid ${name}'s edit, but a later change by someone else stays`
        : `Undid ${name}'s edit`);
      clearTimeout(mark && mark.timer);
      markLayer.replaceChildren();
      mark = null;
    }).catch((err) => page.toast(err.message));
  }

  // ── Keys: asked before the editing keys ──

  page.addKeyHook((e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || !presenting()) return false;
    const edit = window.grafliEdit;
    if (edit && edit.jump()) return false;
    if (e.key === "U") { undoAgent(); return true; }
    if (!proposal) return false;
    if (e.key === "Enter") { settle("take"); return true; }
    if (e.key === "x") { settle("drop"); return true; }
    return false;
  });

  window.grafliAgent = {
    // The proposal waiting, as the server sent it, or null.
    proposal: () => (proposal ? { ...proposal } : null),
    // The banner's text, or null while no proposal waits.
    banner: () => (banner.hidden ? null : banner.textContent),
    // The ids the proposal outlines on the board now.
    outlined: () => Array.from(proposalLayer.children).map((g) => g.dataset.id),
    // The ids glowing now, and the name tag beside them.
    marked: () => (mark ? mark.shown.slice() : []),
    tag: () => (mark ? mark.tag : null),
  };
})();
