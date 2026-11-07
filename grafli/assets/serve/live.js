// The live client grafli serve adds to the export page: it reads the key from
// the link after "#k=", opens the board's WebSocket, hands every pushed frame
// to grafliPage.update() and sends edits as small operations.
//
// window.grafliLive.edit(op) sends one, e.g. {op: "move", id: "api", x: 40,
// y: 80}, against the version on screen; it resolves with the server's ack
// ({touched, conflicts}) and rejects with its message. The new frame follows.
(() => {
  "use strict";
  const page = window.grafliPage;
  const key = new URLSearchParams(location.hash.slice(1)).get("k") || "";
  const socketUrl = (location.protocol === "https:" ? "wss://" : "ws://")
    + location.host + location.pathname.replace(/^\/b\//, "/ws/");

  const badge = document.createElement("span");
  badge.id = "live";
  document.getElementById("bar").appendChild(badge);

  let ws = null, role = null, version = 0, retryMs = 500, nextId = 1;
  const pending = new Map();     // edit id → {resolve, reject}
  const shown = [];              // per frame: ms from the file change to drawn

  function status(text, state) {
    badge.textContent = text;
    badge.dataset.state = state;
  }

  function failPending(why) {
    for (const p of pending.values()) p.reject(new Error(why));
    pending.clear();
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
  }

  function onMessage(e) {
    const m = JSON.parse(e.data);
    if (m.t === "welcome") { role = m.role; retryMs = 500; }
    else if (m.t === "frame") onFrame(m);
    else if (m.t === "ack" || m.t === "error") {
      const p = pending.get(m.id);
      if (p) {
        pending.delete(m.id);
        if (m.t === "ack") p.resolve(m); else p.reject(new Error(m.message));
      } else if (m.t === "error") page.toast(m.message);
    }
  }

  function connect() {
    status("connecting…", "wait");
    ws = new WebSocket(socketUrl);
    ws.onopen = () => ws.send(JSON.stringify({ t: "hello", key }));
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

  window.grafliLive = {
    role: () => role,
    version: () => version,
    shown: () => shown.slice(),
    edit(op) {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        return Promise.reject(new Error("not connected"));
      }
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ t: "edit", id, base: version, op }));
      });
    },
  };

  connect();
})();
