// The live client grafli serve adds to the export page: it reads the key from
// the link after "#k=", opens the board's WebSocket, hands every pushed frame
// to grafliPage.update() and sends edits as small operations.
//
// window.grafliLive.edit(op) sends one, e.g. {op: "move", id: "api", x: 40,
// y: 80}, against the version on screen; it resolves with the server's ack
// ({touched, conflicts, version}) once the frame that shows the edit is on
// its way, and rejects with its message. undo() takes back this tab's last
// edit the same way; the tab's author token survives a reload.
(() => {
  "use strict";
  const page = window.grafliPage;
  const key = new URLSearchParams(location.hash.slice(1)).get("k") || "";
  const author = (() => {
    const made = Math.random().toString(36).slice(2, 12);
    try {
      const kept = sessionStorage.getItem("grafli-author");
      if (kept) return kept;
      sessionStorage.setItem("grafli-author", made);
    } catch (e) { /* storage off: undo lasts as long as this page */ }
    return made;
  })();
  const socketUrl = (location.protocol === "https:" ? "wss://" : "ws://")
    + location.host + location.pathname.replace(/^\/b\//, "/ws/");

  const badge = document.createElement("span");
  badge.id = "live";
  document.getElementById("bar").appendChild(badge);

  let ws = null, role = null, version = 0, retryMs = 500, nextId = 1;
  const pending = new Map();     // edit id → {resolve, reject}
  const shown = [];              // per frame: ms from the file change to drawn
  const frameListeners = [];
  let statusText = "", statusState = "";

  function status(text, state) {
    statusText = text;
    statusState = state;
    showStatus();
  }

  function showStatus() {
    badge.textContent = statusText +
      (pending.size ? ` · ${pending.size} edit${pending.size > 1 ? "s" : ""} on the way` : "");
    badge.dataset.state = statusState;
  }

  function failPending(why) {
    for (const p of pending.values()) p.reject(new Error(why));
    pending.clear();
    showStatus();
  }

  function onFrame(m) {
    page.update(m);
    version = m.version;
    // Measured once the drawing is in the page: the file's change time and
    // this clock are the same machine's when the tab runs on the host.
    requestAnimationFrame(() => {
      const ms = Date.now() - m.changed_at * 1000;
      shown.push({ version: m.version, ms: Math.round(ms), render_ms: m.render_ms });
      if (shown.length > 200) shown.shift();
    });
    status(role === "editor" ? "live · editing" : "live · watching", "live");
    for (const fn of frameListeners) fn(m);
  }

  function onMessage(e) {
    const m = JSON.parse(e.data);
    if (m.t === "welcome") { role = m.role; retryMs = 500; }
    else if (m.t === "frame") onFrame(m);
    else if (m.t === "ack" || m.t === "error") {
      const p = pending.get(m.id);
      if (p) {
        pending.delete(m.id);
        showStatus();
        if (m.t === "ack") p.resolve(m); else p.reject(new Error(m.message));
      } else if (m.t === "error") page.toast(m.message);
    }
  }

  function connect() {
    status("connecting…", "wait");
    ws = new WebSocket(socketUrl);
    ws.onopen = () => ws.send(JSON.stringify({ t: "hello", key, author }));
    ws.onmessage = onMessage;
    ws.onclose = (e) => {
      failPending("the connection closed");
      if (e.code === 4401) { status("wrong or missing key in the link", "off"); return; }
      if (e.code === 4404) { status("no such board", "off"); return; }
      status("reconnecting…", "wait");
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 5000);
    };
  }

  function request(msg) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("not connected"));
    }
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      showStatus();
      ws.send(JSON.stringify({ ...msg, id }));
    });
  }

  window.grafliLive = {
    role: () => role,
    version: () => version,
    shown: () => shown.slice(),
    pending: () => pending.size,
    edit: (op) => request({ t: "edit", base: version, op }),
    undo: () => request({ t: "undo" }),
    // fn(frame) after each pushed frame is drawn.
    onFrame: (fn) => { frameListeners.push(fn); },
  };

  connect();
})();
