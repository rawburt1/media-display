// Gemensamt för de nyare ordklockorna (neon, magneter, buss, texttv, brickor m.fl.):
// inställningar i localStorage, panelen som tonas bort, helskärm,
// närvaro på /clients och en klocka som anropar sidan när tiden ändras.
// Själva tidsläsningen kommer från tid.js (OrdklockaTid).
(function (global) {
  const load = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, v); } catch {} };

  // Knappgrupp <button data-<attr>="värde">: markerar vald knapp, sparar valet.
  function choice(attr, key, def, onChange) {
    const buttons = [...document.querySelectorAll(`button[data-${attr}]`)];
    const valid = buttons.map(b => b.dataset[attr]);
    function set(v) {
      if (!valid.includes(v)) v = def;
      buttons.forEach(b => b.setAttribute("aria-pressed", b.dataset[attr] === v));
      save(key, v);
      onChange(v);
    }
    buttons.forEach(b => { b.onclick = () => set(b.dataset[attr]); });
    set(load(key, def));
    return set;
  }

  // Raderna som ska visas efter "Klockan är":
  // vanlig läsning ["FEM I HALV", "TRE"], digital ["FJORTON", "TJUGOFEM"].
  function lines(t) {
    const hour = t.hourWords.join("");
    if (t.digital) {
      const minutes = t.minutes.map(parts => parts.join("")).join(" ");
      return minutes ? [hour, minutes] : [hour];
    }
    return t.minuteWords.length ? [t.minuteWords.join(" "), hour] : [hour];
  }

  // Panelens utseende; sidan sätter --panel-bg, --panel-fg och --panel-accent.
  const PANEL_CSS = `
    body.idle { cursor: none; }
    .panel {
      position: fixed; left: 50%; bottom: 16px; z-index: 10;
      transform: translateX(-50%);
      width: max-content; max-width: calc(100vw - 32px);
      display: flex; flex-direction: column; align-items: center; gap: 10px;
      padding: 12px 18px; border-radius: 14px;
      background: var(--panel-bg, rgba(0, 0, 0, 0.82));
      color: var(--panel-fg, #ddd);
      font: 14px/1.3 system-ui, sans-serif;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
      transition: opacity 0.5s, transform 0.5s;
    }
    body.idle .panel { opacity: 0; transform: translateX(-50%) translateY(12px); pointer-events: none; }
    .panel .readout { opacity: 0.75; text-align: center; letter-spacing: 0.03em; }
    .panel .controls { display: flex; flex-wrap: wrap; gap: 10px 22px; justify-content: center; }
    .panel .group { display: flex; align-items: center; gap: 6px; }
    .panel .group > .label { opacity: 0.6; margin-right: 4px; }
    .panel button {
      font: inherit; color: inherit; background: transparent; cursor: pointer;
      border: 1px solid color-mix(in srgb, currentColor 35%, transparent);
      border-radius: 999px; padding: 4px 12px;
    }
    .panel button[aria-pressed="true"] {
      background: var(--panel-accent, #ddd); border-color: var(--panel-accent, #ddd);
      color: var(--panel-bg-solid, #000);
    }
  `;

  // Panel, helskärm och närvaro. presencePath: t.ex. "/ordklocka/neon/ws".
  function setup(presencePath) {
    const css = document.createElement("style");
    css.textContent = PANEL_CSS;
    document.head.prepend(css);

    const fsBtn = document.getElementById("fs");
    // The readout stays available to screen readers even when the visual stage is hidden.
    const readoutEl = document.getElementById("readout");
    if (readoutEl) { readoutEl.setAttribute("role", "status"); readoutEl.setAttribute("aria-atomic", "true"); }
    function toggleFullscreen() {
      if (document.fullscreenElement) document.exitFullscreen?.();
      else document.documentElement.requestFullscreen?.().catch(() => {});
    }
    if (fsBtn) fsBtn.onclick = toggleFullscreen;
    document.addEventListener("dblclick", e => {
      if (!e.target.closest(".panel")) toggleFullscreen();
    });
    document.addEventListener("keydown", e => {
      if ((e.key === "f" || e.key === "F") &&
          !e.altKey && !e.ctrlKey && !e.metaKey &&
          !e.target.closest?.("input, textarea, select, [contenteditable]")) toggleFullscreen();
    });
    document.addEventListener("fullscreenchange", () =>
      fsBtn?.setAttribute("aria-pressed", !!document.fullscreenElement));

    // Göm panel och muspekare efter 3 s utan aktivitet.
    let idleTimer;
    function wake() {
      document.body.classList.remove("idle");
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => document.body.classList.add("idle"), 3000);
    }
    ["mousemove", "pointerdown", "keydown", "touchstart"].forEach(ev =>
      document.addEventListener(ev, wake, { passive: true }));
    wake();

    // Närvaro: syns på /clients. Hoppas över när sidan är inbäddad
    // (idle-klockan på startsidan, som redan är listad) eller öppnad som fil.
    if (location.protocol.startsWith("http") &&
        !new URLSearchParams(location.search).has("embedded")) {
      const presence = () => {
        const ws = new WebSocket(
          (location.protocol === "https:" ? "wss://" : "ws://") + location.host + presencePath);
        ws.onclose = () => setTimeout(presence, 10000);
        ws.onerror = () => ws.close();
      };
      presence();
    }
  }

  // Anropar render(t, info) när läsningen (eller extraminuterna) ändras.
  // info: {now, wordsChanged, first}. Returnerar {setStyle, refresh}.
  function clock(render) {
    let style = "tjugo";
    let last = "";
    const readout = document.getElementById("readout");
    function tick(force) {
      const now = new Date();
      const t = OrdklockaTid.spokenTime(now.getHours(), now.getMinutes(), style);
      const words = OrdklockaTid.spokenWords(t).join(" ");
      const key = words + "|" + t.extra;
      if (!force && key === last) return;
      const first = last === "";
      const wordsChanged = first || !last.startsWith(words + "|");
      last = key;
      if (readout) readout.textContent = OrdklockaTid.spokenSentence(t);
      render(t, { now, wordsChanged, first });
    }
    setInterval(() => tick(false), 1000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(false); });
    window.addEventListener("focus", () => tick(false));
    return {
      setStyle(v) { style = v; last = ""; tick(true); },
      refresh() { last = ""; tick(true); },
    };
  }

  global.OrdklockaSida = { load, save, choice, lines, setup, clock };
})(window);
