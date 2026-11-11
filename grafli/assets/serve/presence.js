// Presence in a grafli serve tab: who else is on the board, their named
// cursors, the laser and following the presenter. None of it is written to
// the board; it travels over the tab's WebSocket only.
//
//   k       the laser on and off (Esc too): your pointer leaves a red trail
//           every tab on the board sees for a moment
//
// A tab that did not open the present link follows the presenter: it shows
// what the presenter's tab shows, and goes along to another board. Panning
// or zooming yourself stops it; the button in the bar starts and stops it.
// The name others see is the button "You: …" in the bar.
//
// The board's agent — a Claude Code session the presenter connected — shows
// in the bar by name, in purple, while it is present, and dashed as "gone"
// once the session drops, until it (or another) connects again. The
// presenter's tab tells the server what it selected, for the agent to read.
(() => {
  "use strict";
  const page = window.grafliPage, live = window.grafliLive;
  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  const stage = $("stage"), wrap = $("stage-wrap");
  const SEND_MS = 33;        // a pointer message at most every 33 ms
  const VIEW_MS = 50;        // the presenter's camera at most every 50 ms
  const TRAIL_MS = 900;      // how long a laser point stays on screen
  // A pointer's outline, its tip at 0,0.
  const ARROW = "M0,0 L0,17 L4.6,12.8 L7.6,19.6 L10.4,18.4 L7.4,11.8 L13,11.8 Z";

  function stored(kind, name, value) {
    try {
      const s = window[kind];
      if (value === undefined) return s.getItem(name);
      if (value === null) s.removeItem(name); else s.setItem(name, value);
    } catch (e) { /* storage off: the choice lasts as long as this page */ }
    return null;
  }

  const peers = new Map();   // id → {id, name, role, color, following}
  const cursors = new Map(); // id → {x, y} in board units
  const trails = new Map();  // id → [{x, y, t}]
  let me = null, lead = null, presenterView = null, away = null;
  let agent = null;          // {name, color, present}, null before any agent
  let following = stored("sessionStorage", "grafli-follow") !== "off";
  let laser = false;

  const presenting = () => live.role() === "presenter";
  const leadPeer = () => (lead ? peers.get(lead) : null);

  live.hello(() => ({ name: stored("localStorage", "grafli-name") || "",
                      follow: following }));

  // ── The bar: who is here, follow, your name ──

  const bar = document.createElement("span");
  bar.id = "presence";
  bar.innerHTML = '<span id="peers"></span>'
    + '<span id="agent" hidden></span>'
    + '<button id="follow" type="button" hidden></button>'
    + '<span id="followers" hidden></span>'
    + '<button id="me" type="button" title="The name the others see; click to change it"></button>'
    + '<input id="me-field" type="text" maxlength="32" autocomplete="off" '
    + 'spellcheck="false" hidden>';
  $("bar").appendChild(bar);
  const followBtn = $("follow"), meBtn = $("me"), meField = $("me-field");

  function showBar() {
    const dots = [];
    for (const p of peers.values()) {
      const d = document.createElement("span");
      d.className = "peer" + (p.id === me ? " me" : "") + (p.id === lead ? " lead" : "");
      d.style.background = p.color;
      d.textContent = (p.name.trim()[0] || "?").toUpperCase();
      const what = p.id === lead ? "presenting" : p.role === "viewer" ? "watching" : "editing";
      d.title = `${p.name}${p.id === me ? " (you)" : ""} · ${what}`;
      d.setAttribute("aria-label", d.title);
      dots.push(d);
    }
    $("peers").replaceChildren(...dots);
    showAgent();
    const self = peers.get(me);
    meBtn.textContent = self ? `You: ${self.name}` : "You";
    meBtn.style.borderColor = self ? self.color : "";

    const followers = $("followers");
    if (presenting()) {
      followBtn.hidden = true;
      const n = Array.from(peers.values()).filter((p) => p.following).length;
      followers.hidden = me !== lead;
      followers.textContent = n === 1 ? "1 following you" : `${n} following you`;
      return;
    }
    followers.hidden = true;
    const p = leadPeer();
    if (p) {
      followBtn.hidden = false;
      followBtn.textContent = following ? `Stop following ${p.name}` : `Follow ${p.name}`;
      followBtn.dataset.on = following ? "1" : "";
      followBtn.style.borderColor = p.color;
    } else if (away) {
      followBtn.hidden = false;
      followBtn.textContent = `Follow the presenter to ${away.board}`;
      followBtn.dataset.on = "";
      followBtn.style.borderColor = "";
    } else {
      followBtn.hidden = true;
    }
  }

  function showAgent() {
    const chip = $("agent");
    chip.hidden = !agent;
    if (!agent) return;
    chip.textContent = agent.present ? agent.name : `${agent.name} · gone`;
    chip.dataset.present = agent.present ? "1" : "";
    chip.style.setProperty("--agent", agent.color);
    chip.title = agent.present
      ? `${agent.name} · the board's agent, a Claude Code session the presenter connected`
      : `${agent.name} · gone: the session dropped; the presenter connects it (or another) again`;
    chip.setAttribute("aria-label", chip.title);
  }

  followBtn.addEventListener("click", (e) => {
    e.currentTarget.blur();
    setFollowing(!(following && leadPeer()));
  });

  meBtn.addEventListener("click", () => {
    const self = peers.get(me);
    meField.value = self ? self.name : "";
    meBtn.hidden = true;
    meField.hidden = false;
    meField.focus();
    meField.select();
  });

  function closeName() {
    meField.hidden = true;
    meBtn.hidden = false;
    meField.blur();
  }

  meField.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      const name = meField.value.trim().slice(0, 32);
      closeName();
      stored("localStorage", "grafli-name", name || null);
      live.post({ t: "name", name });
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeName();
    }
  });
  meField.addEventListener("blur", () => { if (!meField.hidden) closeName(); });

  // ── Following the presenter ──

  function setFollowing(on, why) {
    following = on;
    stored("sessionStorage", "grafli-follow", on ? null : "off");
    live.post({ t: "follow", on });
    if (on) {
      if (!leadPeer() && away) { goAway(); return; }
      applyView();
    } else if (why) page.toast(why);
    showBar();
  }

  function applyView() {
    if (!following || presenting() || !presenterView || !page.current()) return;
    const v = presenterView;
    page.frame([v.x, v.y, v.w, v.h]);
  }

  function goAway() {
    if (!away || !away.href || location.pathname === away.href) return;
    location.assign(away.href + location.hash);
  }

  // Your own pan, zoom or tour takes over from the presenter's view.
  page.onUserView(() => {
    if (following && !presenting() && leadPeer()) {
      setFollowing(false, `Stopped following ${leadPeer().name}; the button in the bar follows again`);
    }
  });

  live.onFrame(applyView);
  window.addEventListener("resize", applyView);

  // ── The presenter's camera, sent as it moves ──

  let viewTimer = 0, viewAt = 0;
  function sendView() {
    viewTimer = 0;
    viewAt = performance.now();
    const v = page.view();
    if (v && Number.isFinite(v.w)) live.post({ t: "view", x: v.x, y: v.y, w: v.w, h: v.h });
  }

  page.onView(() => {
    if (!presenting() || viewTimer) return;
    viewTimer = setTimeout(sendView, Math.max(0, VIEW_MS - (performance.now() - viewAt)));
  });

  // ── Your pointer and the laser ──

  function toBoard(clientX, clientY) {
    const m = stage.getScreenCTM();
    if (!m) return null;
    const p = new DOMPoint(clientX, clientY).matrixTransform(m.inverse());
    return { x: p.x, y: p.y };
  }

  let pointerTimer = 0, pointerAt = 0, pointer = null;
  function sendPointer() {
    pointerTimer = 0;
    pointerAt = performance.now();
    if (!pointer) return;
    live.post({ t: pointer.laser ? "laser" : "cursor", x: pointer.x, y: pointer.y });
  }

  function pointerMoved(e) {
    const p = toBoard(e.clientX, e.clientY);
    if (!p) return;
    pointer = { ...p, laser };
    if (laser) addTrail(me, p);
    if (!pointerTimer) {
      pointerTimer = setTimeout(sendPointer, Math.max(0, SEND_MS - (performance.now() - pointerAt)));
    }
  }

  function pointerGone() {
    pointer = null;
    clearTimeout(pointerTimer);
    pointerTimer = 0;
    live.post({ t: "cursor", off: true });
  }

  stage.addEventListener("pointermove", pointerMoved);
  stage.addEventListener("pointerleave", pointerGone);
  document.addEventListener("visibilitychange", () => { if (document.hidden) pointerGone(); });

  function setLaser(on) {
    laser = on;
    stage.classList.toggle("lasering", on);
    if (!on) live.post({ t: "laser", off: true });
    page.toast(on ? "Laser on: point with the mouse; k turns it off" : "Laser off");
  }

  page.addKeyHook((e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return false;
    if (e.key === "k") { setLaser(!laser); return true; }
    if (e.key === "Escape" && laser) { setLaser(false); return true; }
    return false;
  });

  // ── Drawing the others' cursors and every laser trail ──

  const layer = document.createElementNS(SVGNS, "svg");
  layer.id = "presence-layer";
  wrap.appendChild(layer);

  function svg(tag, attrs, parent) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }

  function addTrail(id, p) {
    if (!id) return;
    let t = trails.get(id);
    if (!t) trails.set(id, t = []);
    t.push({ x: p.x, y: p.y, t: performance.now() });
    schedule();
  }

  // A name's width on its plate, in the plate's face (#presence-layer text).
  const widths = new Map();
  const ruler = document.createElement("canvas").getContext("2d");
  function nameWidth(name) {
    if (!widths.has(name)) {
      ruler.font = '600 12px system-ui, -apple-system, "Segoe UI", sans-serif';
      widths.set(name, ruler.measureText(name).width);
    }
    return widths.get(name);
  }

  let drawing = 0;
  function schedule() {
    if (!drawing) drawing = requestAnimationFrame(draw);
  }

  function draw() {
    drawing = 0;
    const m = stage.getScreenCTM();
    if (!m) return;
    const w = wrap.getBoundingClientRect();
    const at = (p) => {
      const q = new DOMPoint(p.x, p.y).matrixTransform(m);
      return { x: q.x - w.left, y: q.y - w.top };
    };
    const now = performance.now(), nodes = [];
    let fading = false;
    for (const [id, points] of trails) {
      while (points.length && now - points[0].t > TRAIL_MS) points.shift();
      if (!points.length) { trails.delete(id); continue; }
      fading = true;
      const g = svg("g", { class: "laser" });
      for (let i = 1; i < points.length; i++) {
        const a = at(points[i - 1]), b = at(points[i]);
        const left = 1 - (now - points[i].t) / TRAIL_MS;
        svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y,
                      "stroke-opacity": left.toFixed(2),
                      "stroke-width": (2 + 4 * left).toFixed(1) }, g);
      }
      const head = at(points[points.length - 1]);
      svg("circle", { cx: head.x, cy: head.y, r: 5,
                      "fill-opacity": (1 - (now - points[points.length - 1].t) / TRAIL_MS).toFixed(2) }, g);
      nodes.push(g);
    }
    for (const [id, c] of cursors) {
      const p = peers.get(id);
      if (!p || id === me) continue;
      const s = at(c);
      const g = svg("g", { class: "cursor", transform: `translate(${s.x} ${s.y})`,
                            "data-id": id });
      svg("path", { d: ARROW, fill: p.color }, g);
      const label = svg("g", { class: "name", transform: "translate(12 20)" }, g);
      svg("rect", { x: 0, y: 0, rx: 4, width: nameWidth(p.name) + 14, height: 18,
                    fill: p.color }, label);
      svg("text", { x: 7, y: 9 }, label).textContent = p.name;
      nodes.push(g);
    }
    layer.replaceChildren(...nodes);
    if (fading) schedule();
  }

  page.onView(schedule);
  window.addEventListener("resize", schedule);

  // ── What the server says ──

  // A presenter's tab sends its camera as soon as it has one: the first
  // frame sets it, and a tab that reconnects has it already.
  live.on("welcome", (m) => {
    me = m.id;
    if (m.role === "presenter") {
      following = false;
      if (page.current()) sendView();
      sendSelection(page.selectedEl());
    }
  });

  // What the presenter selected, for the agent to read.
  function sendSelection(el) {
    if (presenting()) live.post({ t: "select", id: el ? el.id : null });
  }
  page.onSelect(sendSelection);

  live.on("peers", (m) => {
    const had = agent;
    agent = m.agent || null;
    if (had && agent && had.present !== agent.present) {
      page.toast(agent.present ? `${agent.name} connected`
                               : `${agent.name} is gone`);
    } else if (!had && agent && agent.present && me) {
      page.toast(`${agent.name} connected`);
    } else if (had && agent && had.name !== agent.name && agent.present) {
      page.toast(`${agent.name} is the agent now`);
    }
    me = m.you;
    const was = lead;
    lead = m.lead;
    peers.clear();
    for (const p of m.peers) peers.set(p.id, p);
    for (const id of Array.from(cursors.keys())) if (!peers.has(id)) cursors.delete(id);
    for (const id of Array.from(trails.keys())) if (!peers.has(id) && id !== me) trails.delete(id);
    if (lead !== was) {
      presenterView = null;
      if (lead) away = null;
      // A presenter's tab that leads now sends its camera at once.
      if (presenting() && lead === me && page.current()) sendView();
    }
    showBar();
    schedule();
  });

  live.on("view", (m) => {
    if (m.id !== lead) return;
    presenterView = { x: m.x, y: m.y, w: m.w, h: m.h };
    applyView();
  });

  // The laser going off leaves the cursor where it is; the cursor going off
  // (the pointer left the board) takes it away.
  function moved(m) {
    if (m.off) {
      if (m.t === "cursor") cursors.delete(m.id);
    } else {
      cursors.set(m.id, { x: m.x, y: m.y });
      if (m.t === "laser") addTrail(m.id, m);
    }
    schedule();
  }
  live.on("cursor", moved);
  live.on("laser", moved);

  live.on("away", (m) => {
    away = m.board ? { board: m.board, href: m.href } : null;
    if (away && following && !presenting()) goAway();
    showBar();
  });

  window.grafliPresence = {
    me: () => me,
    lead: () => lead,
    peers: () => Array.from(peers.values()).map((p) => ({ ...p })),
    following: () => following,
    follow: (on) => setFollowing(on),
    laser: () => laser,
    presenterView: () => (presenterView ? { ...presenterView } : null),
    cursor: (id) => (cursors.has(id) ? { ...cursors.get(id) } : null),
    trail: (id) => (trails.get(id) || []).length,
    // The names on the cursors drawn now.
    shown: () => Array.from(layer.querySelectorAll(".cursor text")).map((t) => t.textContent),
    away: () => (away ? { ...away } : null),
    agent: () => (agent ? { ...agent } : null),
    // The agent as the bar shows it: its text, or null when hidden.
    agentShown: () => ($("agent").hidden ? null : $("agent").textContent),
  };
})();
