// The page grafli export-html writes: pan and zoom, levels you zoom into and
// back out of, the doc peek, the overlay switch and the tour player. Every
// board is the app's own SVG in a <template>; this script only moves the
// camera (the viewBox), swaps drawings and places click areas from the rects
// in #grafli-data.
(() => {
  "use strict";
  const DATA = JSON.parse(document.getElementById("grafli-data").textContent);
  const FONTS = JSON.parse(document.getElementById("grafli-fonts").textContent);
  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  const stage = $("stage"), art = $("art"), hits = $("hits"), sel = $("sel");
  const LEVEL_MS = 450;
  const STOP_MS = 700;       // the camera's glide between stops on one board

  let board = null;          // the board on screen
  let vb = null;             // its camera: {x, y, w, h} in board units
  let selected = null;       // the selected element entry
  let peeked = null;         // the element whose doc the peek shows
  let busy = false;          // a level zoom is playing
  const stack = [];          // frames to go back up to
  let tour = null;           // the playing tour, see "Tours" below
  const overlayOf = {};      // board id → index into its states

  // ── Fonts: the bundled faces, gzipped, unpacked in the browser ──

  async function loadFonts() {
    if (!("DecompressionStream" in window) || !("FontFace" in window)) return;
    for (const f of FONTS) {
      try {
        const bin = atob(f.data);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const stream = new Blob([bytes]).stream()
          .pipeThrough(new DecompressionStream("gzip"));
        const buf = await new Response(stream).arrayBuffer();
        const face = new FontFace(f.family, buf, { weight: f.weight });
        await face.load();
        document.fonts.add(face);
      } catch (e) { /* the drawing falls back to a system face */ }
    }
  }

  // ── Camera ──

  function stageSize() {
    const r = stage.getBoundingClientRect();
    return { w: Math.max(r.width, 1), h: Math.max(r.height, 1) };
  }

  function setView(v) {
    vb = v;
    stage.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
    placePeek();
  }

  // A camera that shows rect [x, y, w, h] whole, at the stage's aspect.
  function frameRect(r, margin) {
    const s = stageSize();
    let w = r[2] * (1 + 2 * margin), h = r[3] * (1 + 2 * margin);
    w = Math.max(w, 1); h = Math.max(h, 1);
    if (w / h > s.w / s.h) h = w * s.h / s.w; else w = h * s.w / s.h;
    return { x: r[0] + r[2] / 2 - w / 2, y: r[1] + r[3] / 2 - h / 2, w, h };
  }

  function fitBoard() { return frameRect(board.bounds, 0); }

  function toBoard(clientX, clientY) {
    const r = stage.getBoundingClientRect();
    return { x: vb.x + (clientX - r.left) / r.width * vb.w,
             y: vb.y + (clientY - r.top) / r.height * vb.h };
  }

  function zoomAt(p, factor) {
    const maxW = Math.max(board.bounds[2], board.bounds[3]) * 8;
    const w = Math.min(Math.max(vb.w * factor, 40), maxW);
    const f = w / vb.w;
    setView({ x: p.x - (p.x - vb.x) * f, y: p.y - (p.y - vb.y) * f,
              w, h: vb.h * f });
  }

  // Glide the camera to *to*: centre linear, size geometric, eased.
  function glide(to, ms, done) {
    const from = vb, t0 = performance.now();
    const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
    const cx0 = from.x + from.w / 2, cy0 = from.y + from.h / 2;
    const cx1 = to.x + to.w / 2, cy1 = to.y + to.h / 2;
    function step(now) {
      const t = Math.min((now - t0) / ms, 1), k = ease(t);
      const w = from.w * Math.pow(to.w / from.w, k);
      const h = from.h * Math.pow(to.h / from.h, k);
      const cx = cx0 + (cx1 - cx0) * k, cy = cy0 + (cy1 - cy0) * k;
      setView({ x: cx - w / 2, y: cy - h / 2, w, h });
      if (t < 1) requestAnimationFrame(step); else if (done) done();
    }
    requestAnimationFrame(step);
  }

  // ── Boards ──

  function showBoard(id) {
    board = DATA.boards[id];
    closePeek();
    select(null);
    drawState();
    buildHits();
    showOverlayPick();
    showTourPick();
    showCrumbs();
  }

  function drawState() {
    const state = board.states[overlayOf[board.id] || 0];
    const tpl = $("svg-" + state.svg);
    const svg = tpl.content.firstElementChild;
    art.replaceChildren(...Array.from(svg.childNodes,
      (n) => document.importNode(n, true)));
    $("stage-wrap").style.background = state.background;
    showLegend();
  }

  function hitTitle(el) {
    const what = el.level ? "click to zoom in" : el.doc ? "click to read"
      : el.url ? "Return opens " + el.url : "";
    return what ? `${el.label} — ${what}` : el.label;
  }

  function buildHits() {
    const nodes = [];
    const boxes = board.elements.filter((e) => e.rect)
      .sort((a, b) => b.rect[2] * b.rect[3] - a.rect[2] * a.rect[3]);
    for (const el of boxes) {
      const r = document.createElementNS(SVGNS, "rect");
      r.setAttribute("x", el.rect[0]); r.setAttribute("y", el.rect[1]);
      r.setAttribute("width", el.rect[2]); r.setAttribute("height", el.rect[3]);
      nodes.push(hitNode(r, el, "hit"));
    }
    for (const el of board.elements.filter((e) => e.paths)) {
      for (const d of el.paths) {
        const p = document.createElementNS(SVGNS, "path");
        p.setAttribute("d", d);
        nodes.push(hitNode(p, el, "hit-arrow"));
      }
    }
    hits.replaceChildren(...nodes);
  }

  function hitNode(node, el, cls) {
    node.setAttribute("class", cls + (el.level || el.doc ? " act" : ""));
    node.dataset.id = el.id;
    const t = document.createElementNS(SVGNS, "title");
    t.textContent = hitTitle(el);
    node.appendChild(t);
    node.__el = el;
    return node;
  }

  function elementBox(el) {
    if (el.rect) return el.rect;
    let box = null;
    for (const node of hits.children) {
      if (node.__el !== el) continue;
      const b = node.getBBox();
      box = box ? [Math.min(box[0], b.x), Math.min(box[1], b.y), 0, 0] : [b.x, b.y, 0, 0];
      box[2] = Math.max(box[0] + box[2], b.x + b.width) - box[0];
      box[3] = Math.max(box[1] + box[3], b.y + b.height) - box[1];
    }
    return box || board.bounds;
  }

  function findTarget(b, id) {
    if (!id) return null;
    if (b.bookmarks[id]) return b.bookmarks[id].rect;
    const el = b.elements.find((e) => e.id === id && e.rect);
    return el ? el.rect : undefined;
  }

  // ── Levels ──

  function enter(el) {
    if (busy || !el || !el.level) return;
    const child = DATA.boards[el.level.board];
    const frame = { board: board.id, view: vb, selected: el, via: el,
                    label: el.label, tour: leaveTour() };
    busy = true;
    closePeek();
    glide(frameRect(elementBox(el), 0.02), LEVEL_MS, () => {
      stack.push(frame);
      showBoard(child.id);
      const target = el.level.target;
      const rect = findTarget(child, target);
      setView(rect ? frameRect(rect, 0.08) : fitBoard());
      if (rect === undefined) toast(`No element '${target}' in ${child.file}`);
      fade();
      busy = false;
    });
  }

  function up() {
    if (busy) return;
    if (tour) stopTour();
    if (!stack.length) { toast("Already at the top"); return; }
    const frame = stack.pop();
    showBoard(frame.board);
    select(frame.selected);
    fade();
    if (!frame.via) {
      // A frame a tour stop pushed: no box to zoom back out of.
      setView(frame.view);
      if (frame.tour) resumeTour(frame.tour);
      return;
    }
    busy = true;
    setView(frameRect(elementBox(frame.via), 0.02));
    glide(frame.view, LEVEL_MS, () => {
      busy = false;
      if (frame.tour) resumeTour(frame.tour);
    });
  }

  function upTo(depth) {
    if (busy || depth >= stack.length) return;
    if (tour) stopTour();
    let frame;
    while (stack.length > depth) frame = stack.pop();
    showBoard(frame.board);
    select(frame.selected);
    setView(frame.view);
  }

  function fade() {
    art.classList.remove("fade");
    void art.getBoundingClientRect();
    art.classList.add("fade");
  }

  function showCrumbs() {
    const nav = $("crumbs");
    const labels = [DATA.boards[DATA.root].title, ...stack.map((f) => f.label)];
    const parts = [];
    labels.forEach((label, i) => {
      if (i) {
        const sep = document.createElement("span");
        sep.className = "sep"; sep.textContent = "›";
        parts.push(sep);
      }
      const b = document.createElement("button");
      b.type = "button";
      b.className = "crumb" + (i === labels.length - 1 ? " here" : "");
      b.textContent = label;
      if (i < labels.length - 1) b.addEventListener("click", () => upTo(i));
      else b.setAttribute("aria-current", "page");
      parts.push(b);
    });
    nav.replaceChildren(...parts);
    $("back").disabled = !stack.length;
    document.title = labels[labels.length - 1];
  }

  // ── Selection and the doc peek ──

  function select(el) {
    selected = el;
    for (const node of hits.querySelectorAll(".hit-arrow.selected")) {
      node.classList.remove("selected");
    }
    // SVG elements ignore the hidden attribute.
    sel.style.display = "none";
    if (el && el.rect) {
      const pad = 3;
      sel.setAttribute("x", el.rect[0] - pad); sel.setAttribute("y", el.rect[1] - pad);
      sel.setAttribute("width", el.rect[2] + 2 * pad);
      sel.setAttribute("height", el.rect[3] + 2 * pad);
      sel.style.display = "";
    } else if (el) {
      for (const node of hits.children) {
        if (node.__el === el) node.classList.add("selected");
      }
    }
    showLegend();
  }

  function openPeek(el) {
    if (!el || !el.doc) return;
    peeked = el;
    $("peek-body").innerHTML = DATA.docs[el.doc];
    $("peek").hidden = false;
    $("peek").scrollTop = 0;
    placePeek();
  }

  function closePeek() {
    if (!peeked) return false;
    peeked = null;
    $("peek").hidden = true;
    return true;
  }

  // Beside its element: right when there is room, else left, else below.
  function placePeek() {
    if (!peeked || !vb) return;
    const peek = $("peek"), wrap = $("stage-wrap").getBoundingClientRect();
    const r = elementBox(peeked), gap = 10;
    const sx = wrap.width / vb.w;
    const left = (r[0] - vb.x) * sx, top = (r[1] - vb.y) * sx;
    const right = left + r[2] * sx, bottom = top + r[3] * sx;
    const w = peek.offsetWidth, h = peek.offsetHeight;
    let x, y;
    if (right + gap + w <= wrap.width - gap) { x = right + gap; y = top; }
    else if (left - gap - w >= gap) { x = left - gap - w; y = top; }
    else { x = left; y = bottom + gap; }
    x = Math.max(gap, Math.min(x, wrap.width - gap - w));
    y = Math.max(gap, Math.min(y, wrap.height - gap - h));
    peek.style.left = x + "px";
    peek.style.top = y + "px";
  }

  // ── Overlays ──

  function showOverlayPick() {
    const pick = $("overlay-pick"), select_ = $("overlay");
    if (board.states.length < 2) { pick.hidden = true; return; }
    const opts = board.states.map((s, i) => {
      const o = document.createElement("option");
      o.value = i;
      o.textContent = i ? s.legend.title : "No overlay";
      return o;
    });
    select_.replaceChildren(...opts);
    select_.value = overlayOf[board.id] || 0;
    pick.hidden = false;
  }

  function setOverlay(i) {
    overlayOf[board.id] = i;
    $("overlay").value = i;
    drawState();
    toast(i ? "Overlay: " + board.states[i].legend.title : "Overlays off");
  }

  function div(cls, text) {
    const d = document.createElement("div");
    if (cls) d.className = cls;
    if (text !== undefined) d.textContent = text;
    return d;
  }

  function showLegend() {
    const card = $("legend");
    const i = board ? overlayOf[board.id] || 0 : 0;
    if (!i) { card.hidden = true; return; }
    const lg = board.states[i].legend;
    const rows = [div("title", lg.title)];
    if (lg.producer) rows.push(div("dim", lg.producer));
    if (lg.stale) rows.push(div("stale", "⚠ " + lg.stale));
    if (lg.categories) {
      for (const [label, color] of lg.categories) {
        const row = div("row"), sw = div("swatch");
        sw.style.background = color;
        row.append(sw, document.createTextNode(label));
        rows.push(row);
      }
    } else {
      const bar = div("bar");
      bar.style.background = "linear-gradient(to right, " +
        lg.scale.stops.map(([p, c]) => `${c} ${p * 100}%`).join(", ") + ")";
      const ends = div("ends");
      ends.append(div("", lg.scale.low), div("", lg.scale.high));
      rows.push(bar, ends);
    }
    const none = div("row");
    none.append(div("swatch none"), document.createTextNode("no data"));
    rows.push(none);
    if (selected) {
      rows.push(document.createElement("hr"));
      const d = lg.details[selected.id];
      rows.push(div("", `${selected.id}: ${d ? d.reading : "no data"}`));
      if (d && d.note) rows.push(div("dim", d.note));
      if (d) for (const ref of d.refs) rows.push(div("ref", ref));
    }
    card.replaceChildren(...rows);
    card.hidden = false;
  }

  // ── Tours ──
  //
  // A tour is a flow of its home board; a stop may lie in another board,
  // which the player shows the way the app does: back along the stack when
  // the tour came through it, else one frame down from here. Entering a
  // level mid-tour parks the tour in that frame; going back up resumes it.

  const MODES = ["paused", "playing", "loop"];
  let tourTimer = 0;

  function showTourPick() {
    const pick = $("tour-pick"), select_ = $("tour");
    const flows = board.flows.filter((f) => f.steps.length);
    if (tour || !flows.length) { pick.hidden = true; return; }
    const head = document.createElement("option");
    head.value = ""; head.textContent = "Play a tour…";
    const opts = flows.map((f) => {
      const o = document.createElement("option");
      o.value = f.id;
      o.textContent = `${f.label || f.id} (${f.steps.length})`;
      return o;
    });
    select_.replaceChildren(head, ...opts);
    select_.value = "";
    pick.hidden = false;
  }

  function playTour(flowId, index) {
    const flow = board.flows.find((f) => f.id === flowId);
    if (!flow || !flow.steps.length) return;
    if (tour) stopTour();
    tour = { home: board.id, flow, index: 0, mode: "paused", smooth: true };
    $("tour-pick").hidden = true;
    $("player").hidden = false;
    gotoStop(index || 0, true);
  }

  // Leave the tour on purpose: stop, and come back to its home board.
  function endTour() {
    if (!tour) return;
    const home = tour.home;
    stopTour();
    if (board.id !== home) {
      const frame = boardFor(home);
      if (frame) setView(frame.view);
    }
  }

  function stopTour() {
    clearTimeout(tourTimer);
    tour = null;
    $("player").hidden = true;
    emphasise(null);
    showTourPick();
  }

  // Entering a level mid-tour: the tour pauses and waits in the frame.
  function leaveTour() {
    if (!tour) return null;
    const kept = { home: tour.home, flow: tour.flow, index: tour.index,
                   mode: tour.mode, smooth: tour.smooth };
    stopTour();
    return kept;
  }

  // Pick a parked tour up at its stop, the camera where you left it.
  function resumeTour(kept) {
    tour = { ...kept };
    $("tour-pick").hidden = true;
    $("player").hidden = false;
    gotoStop(kept.index, false);
  }

  // Show board *id* for a stop; the frame popped on the way back, if any.
  function boardFor(id) {
    if (board.id === id) return null;
    const depth = stack.findIndex((f) => f.board === id);
    let frame = null;
    if (depth >= 0) {
      while (stack.length > depth) frame = stack.pop();
    } else {
      stack.push({ board: board.id, view: vb, selected,
                   label: DATA.boards[id].title });
    }
    showBoard(id);
    if (frame) select(frame.selected);
    fade();
    return frame;
  }

  function stopTarget(step) {
    const b = step.board ? DATA.boards[step.board] : null;
    return { board: b, bookmark: b ? b.bookmarks[step.bookmark] : null };
  }

  function gotoStop(index, move) {
    const steps = tour.flow.steps;
    tour.index = Math.max(0, Math.min(index, steps.length - 1));
    const step = steps[tour.index];
    const { board: there, bookmark } = stopTarget(step);
    clearTimeout(tourTimer);
    closePeek();
    if (there && there.id !== board.id) {
      boardFor(there.id);
      if (move) setView(bookmark ? frameRect(bookmark.rect, 0.04) : fitBoard());
    } else if (bookmark && move) {
      const to = frameRect(bookmark.rect, 0.04);
      if (tour.smooth) glide(to, STOP_MS); else setView(to);
    }
    emphasise(there === board ? bookmark : null);
    showPlayer(bookmark);
    if (tour.mode !== "paused") schedule(step);
  }

  function schedule(step) {
    const dwell = step.dwell != null ? step.dwell : DATA.dwell;
    tour.dwellMs = dwell * 1000;
    tourTimer = setTimeout(autoAdvance, tour.dwellMs);
    const bar = $("pl-dwell");
    bar.style.transition = "none";
    bar.style.width = "0";
    void bar.offsetWidth;
    bar.style.transition = `width ${dwell}s linear`;
    bar.style.width = "100%";
  }

  function autoAdvance() {
    if (tour && tour.mode !== "paused") nextStop();
  }

  function nextStop() {
    const last = tour.flow.steps.length - 1;
    if (tour.index < last) gotoStop(tour.index + 1, true);
    else if (tour.mode === "loop") gotoStop(0, true);
    else if (tour.mode === "playing") {
      // The end of the tour: stop advancing, stay on the last stop.
      tour.mode = "paused";
      clearTimeout(tourTimer);
      showPlayer(stopTarget(tour.flow.steps[tour.index]).bookmark);
    }
  }

  function prevStop() {
    if (tour.index > 0) gotoStop(tour.index - 1, true);
  }

  function setMode(mode) {
    tour.mode = mode;
    clearTimeout(tourTimer);
    if (mode !== "paused") schedule(tour.flow.steps[tour.index]);
    showPlayer(stopTarget(tour.flow.steps[tour.index]).bookmark);
  }

  function cycleMode() {
    setMode(MODES[(MODES.indexOf(tour.mode) + 1) % MODES.length]);
  }

  function togglePlay() {
    setMode(tour.mode === "paused" ? "playing" : "paused");
  }

  // A path stop: its arrows in the accent colour.
  function emphasise(bookmark) {
    const ids = new Set(bookmark && bookmark.arrows ? bookmark.arrows : []);
    for (const node of hits.querySelectorAll(".hit-arrow")) {
      node.classList.toggle("tour", ids.has(node.dataset.id));
    }
  }

  function showPlayer(bookmark) {
    const n = tour.flow.steps.length, i = tour.index;
    $("pl-flow").textContent = tour.flow.label || tour.flow.id;
    $("pl-count").textContent = `${i + 1} / ${n}` +
      (tour.mode === "loop" ? " · loop" : "") +
      (tour.smooth ? "" : " · instant");
    $("pl-label").textContent = bookmark
      ? bookmark.label || tour.flow.steps[i].bookmark : "(missing bookmark)";
    $("pl-desc").textContent = bookmark ? bookmark.description : "";
    $("pl-desc").hidden = !(bookmark && bookmark.description);
    $("pl-bar").style.width = `${(i + 1) / n * 100}%`;
    const playing = tour.mode !== "paused";
    $("pl-play").textContent = playing ? "❚❚ Pause" : "▶ Play";
    $("pl-play").setAttribute("aria-pressed", String(playing));
    $("pl-prev").disabled = i === 0;
    $("pl-next").disabled = i === n - 1 && tour.mode !== "loop";
    if (!playing) {
      const bar = $("pl-dwell");
      bar.style.transition = "none";
      bar.style.width = "0";
    }
  }

  // The keys of the app's playback; everything else waits for the tour.
  function tourKey(k) {
    if (k === "Escape" || k === "q") endTour();
    else if (k === " " || k === "ArrowRight" || k === "l" || k === "j") nextStop();
    else if (k === "ArrowLeft" || k === "h" || k === "k") prevStop();
    else if (k === "t") {
      tour.smooth = !tour.smooth;
      showPlayer(stopTarget(tour.flow.steps[tour.index]).bookmark);
    }
    else if (k === "p") cycleMode();
    else if (k === "Enter") {
      if (selected && selected.level) enter(selected);
    }
    else if (k === "Backspace") up();
    else return false;
    return true;
  }

  // ── Toasts ──

  let toastTimer = 0;
  function toast(text) {
    const t = $("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
  }

  // ── Input ──

  function activate(el) {
    select(el);
    if (!el) { closePeek(); return; }
    if (el.level) enter(el);
    else if (el.doc) openPeek(el);
    else closePeek();
  }

  let drag = null;
  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY, moved: false,
             target: e.target.__el || null, view: vb };
    stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener("pointermove", (e) => {
    if (!drag || busy) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    stage.classList.add("panning");
    const s = vb.w / stage.getBoundingClientRect().width;
    setView({ x: drag.view.x - dx * s, y: drag.view.y - dy * s, w: vb.w, h: vb.h });
  });
  stage.addEventListener("pointerup", () => {
    if (!drag) return;
    const d = drag;
    drag = null;
    stage.classList.remove("panning");
    if (!d.moved && !busy) activate(d.target);
  });
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (busy) return;
    const rate = e.ctrlKey ? 0.01 : 0.0015;
    zoomAt(toBoard(e.clientX, e.clientY), Math.exp(e.deltaY * rate));
  }, { passive: false });

  $("back").addEventListener("click", up);
  $("tour").addEventListener("change", (e) => {
    if (e.target.value) playTour(e.target.value, 0);
    e.target.blur();
  });
  // Player buttons let go of the focus, so Space stays the tour's next key.
  const playerButton = (id, act) => $(id).addEventListener("click", (e) => {
    e.currentTarget.blur();
    if (tour) act();
  });
  playerButton("pl-prev", prevStop);
  playerButton("pl-next", nextStop);
  playerButton("pl-play", togglePlay);
  playerButton("pl-close", endTour);
  $("overlay").addEventListener("change", (e) => setOverlay(Number(e.target.value)));

  function centre() { return { x: vb.x + vb.w / 2, y: vb.y + vb.h / 2 }; }

  let gPending = false, gTimer = 0;
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target instanceof HTMLSelectElement) return;
    const k = e.key;
    if (gPending) {
      gPending = false;
      clearTimeout(gTimer);
      if (k === "d") { if (selected && selected.level) enter(selected); else noLevel(); }
      else if (k === "u") up();
      else if (k === "v") peekSelected();
      e.preventDefault();
      return;
    }
    if (busy) return;
    if (tour) {
      if (k === "g") { gPending = true; gTimer = setTimeout(() => { gPending = false; }, 1200); }
      else if (!tourKey(k)) return;
      e.preventDefault();
      return;
    }
    let handled = true;
    if (k === "g") { gPending = true; gTimer = setTimeout(() => { gPending = false; }, 1200); }
    else if (k === "Enter") {
      if (!selected) toast("Select a box first");
      else if (selected.level) enter(selected);
      else if (selected.doc) openPeek(selected);
      else if (selected.url) window.open(selected.url, "_blank", "noopener");
      else toast(`'${selected.label}' has no level, doc or link`);
    }
    else if (k === "Backspace") up();
    else if (k === "Escape") { if (!closePeek()) select(null); }
    else if (k === "A") {
      if (board.states.length < 2) toast("No overlays on this board");
      else setOverlay(((overlayOf[board.id] || 0) + 1) % board.states.length);
    }
    else if (k === "+" || k === "=") zoomAt(centre(), 1 / 1.25);
    else if (k === "-") zoomAt(centre(), 1.25);
    else if (k === "Z") setView(fitBoard());
    else if (k.startsWith("Arrow")) {
      const step = vb.w * 0.1;
      const dx = k === "ArrowLeft" ? -step : k === "ArrowRight" ? step : 0;
      const dy = k === "ArrowUp" ? -step : k === "ArrowDown" ? step : 0;
      setView({ x: vb.x + dx, y: vb.y + dy, w: vb.w, h: vb.h });
    }
    else handled = false;
    if (handled) e.preventDefault();
  });

  function noLevel() {
    if (!selected) toast("Select a box with a level to zoom into it");
    else if (!selected.level) toast(`'${selected.label}' has no level to zoom into`);
  }

  function peekSelected() {
    if (!selected) { toast("Select a box with a doc to peek at it"); return; }
    if (!selected.doc) { toast(`'${selected.label}' has no doc to peek at`); return; }
    if (peeked === selected) closePeek(); else openPeek(selected);
  }

  let lastStage = stageSize();
  window.addEventListener("resize", () => {
    const s = stageSize(), k = vb.w / lastStage.w;
    lastStage = s;
    const c = centre();
    setView({ x: c.x - s.w * k / 2, y: c.y - s.h * k / 2, w: s.w * k, h: s.h * k });
  });

  // A test hook: the page's state, read by the export's browser check.
  window.grafliPage = {
    board: () => board.id, depth: () => stack.length,
    selected: () => (selected ? selected.id : null),
    peek: () => (peeked ? peeked.id : null),
    overlay: () => overlayOf[board.id] || 0,
    view: () => ({ ...vb }), busy: () => busy,
    tour: () => (tour ? { flow: tour.flow.id, index: tour.index,
                          mode: tour.mode, dwellMs: tour.dwellMs || 0 } : null),
  };

  loadFonts();
  showBoard(DATA.root);
  setView(fitBoard());
})();
