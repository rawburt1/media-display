// Imma på glas som någon skriver i med fingret (fönstret och duschväggen).
// Sidan har <canvas id="fog"> överst och sin egen bakgrund under.
// OrdklockaImma.start(opts) -> {show(lines, animate)}
//   opts.fog:      färg på imman, t.ex. "rgb(214, 222, 230)"
//   opts.alpha:    hur tät imman är (0-1)
//   opts.drips:    rinnande droppar per tecken (0-1)
//   opts.dripSpeed: pixlar per sekund (relativt textstorleken)
//   opts.box():    rutan texten ska ligga i, {x, y, w, h}
(function (global) {
  const K = OrdklockaSkrift;
  const rnd = (a, b) => a + Math.random() * (b - a);

  function start(opts) {
    const cv = document.getElementById("fog");
    const ctx = cv.getContext("2d");
    const tex = document.createElement("canvas");     // imman, förrenderad
    const clear = document.createElement("canvas");   // det som är torkat bort
    const cctx = clear.getContext("2d");
    let W = 0, H = 0, dpr = 1;

    function buildTexture() {
      tex.width = cv.width; tex.height = cv.height;
      const g = tex.getContext("2d");
      g.fillStyle = opts.fog;
      g.globalAlpha = opts.alpha;
      g.fillRect(0, 0, tex.width, tex.height);
      // Ojämn imma: ljusare och mörkare fläckar
      for (let i = 0; i < 70; i++) {
        const x = Math.random() * tex.width, y = Math.random() * tex.height, r = rnd(0.05, 0.25) * tex.width;
        const grd = g.createRadialGradient(x, y, 0, x, y, r);
        const light = Math.random() < 0.5;
        grd.addColorStop(0, light ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.05)");
        grd.addColorStop(1, "rgba(0,0,0,0)");
        g.globalAlpha = 1;
        g.fillStyle = grd;
        g.fillRect(x - r, y - r, 2 * r, 2 * r);
      }
      // Små kondensdroppar
      const n = Math.round(tex.width * tex.height / 900);
      for (let i = 0; i < n; i++) {
        const x = Math.random() * tex.width, y = Math.random() * tex.height, r = rnd(0.6, 2.2) * dpr;
        g.fillStyle = "rgba(255,255,255,0.35)";
        g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
        g.fillStyle = "rgba(0,0,0,0.08)";
        g.beginPath(); g.arc(x + r * 0.3, y + r * 0.4, r * 0.7, 0, Math.PI * 2); g.fill();
      }
    }

    function resize() {
      dpr = Math.min(devicePixelRatio || 1, 2);
      W = innerWidth; H = innerHeight;
      cv.width = clear.width = Math.round(W * dpr);
      cv.height = clear.height = Math.round(H * dpr);
      cctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildTexture();
      if (current) { L = null; progress = current.length ? 9999 : 0; }
    }

    // ---------- Tillstånd ----------
    let current = null;            // rader som visas / skrivs
    let L = null;                  // layout
    let progress = 0;              // skrivna tecken
    let clarity = 1;               // 1 = nyss torkat, sjunker när imman kryper tillbaka
    let fadeOut = 0;               // >0: gammal text immar igen innan ny skrivs
    let pending = null;
    let drips = [];
    let writtenAt = 0;
    const CHARS_PER_SEC = 5.5;

    function font(size) { return `${size}px ${K.HAND}`; }

    function show(lines, animate) {
      if (!current || !animate) {
        current = lines; L = null; progress = animate ? 0 : 9999; drips = []; clarity = 1;
        writtenAt = performance.now();
        return;
      }
      pending = lines;
      fadeOut = 1;
    }

    function drawClear() {
      cctx.clearRect(0, 0, W, H);
      if (!current) return null;
      if (!L) {
        L = K.layout(cctx, current, opts.box(W, H), font, { lineHeight: 1.2 });
        if (progress > L.chars) progress = L.chars;
      }
      cctx.globalAlpha = clarity;
      cctx.fillStyle = cctx.strokeStyle = "#000";
      cctx.lineJoin = cctx.lineCap = "round";
      cctx.lineWidth = L.size * 0.07;           // fingret är brett
      cctx.font = L.font;
      cctx.textBaseline = "middle";
      cctx.shadowColor = "#000";
      cctx.shadowBlur = L.size * 0.05;
      const pen = K.drawPartial(cctx, L, progress, (g, line) => {
        g.fillText(line.text, line.x, line.y);
        g.strokeText(line.text, line.x, line.y);
      });
      cctx.shadowBlur = 0;
      // Rinnande droppar: genomskinliga spår nedåt
      cctx.lineWidth = Math.max(1.5, L.size * 0.035);
      for (const d of drips) {
        cctx.beginPath();
        cctx.moveTo(d.x, d.y0);
        cctx.lineTo(d.x + d.wob, d.y0 + d.len);
        cctx.stroke();
      }
      cctx.globalAlpha = 1;
      return pen;
    }

    let prev = performance.now();
    function frame(now) {
      const dt = Math.min(0.1, (now - prev) / 1000);
      prev = now;
      if (fadeOut > 0) {
        // Ny tid: imman sluter sig över den gamla texten först.
        fadeOut -= dt / 1.4;
        clarity = Math.max(0, fadeOut);
        if (fadeOut <= 0) {
          current = pending; pending = null; L = null; progress = 0; drips = []; clarity = 1;
          writtenAt = now;
        }
      } else if (L && progress < L.chars) {
        const before = Math.floor(progress);
        progress = Math.min(L.chars, progress + dt * CHARS_PER_SEC);
        if (Math.floor(progress) > before && Math.random() < opts.drips) {
          pendingDrip = true;
        }
      } else {
        // Imman kryper långsamt tillbaka, men texten ska gå att läsa i 5 min.
        clarity = Math.max(0.45, 1 - (now - writtenAt) / 1000 / 600);
      }
      for (const d of drips) {
        if (d.len < d.max) d.len = Math.min(d.max, d.len + d.speed * dt * (0.4 + Math.random()));
        d.wob += rnd(-0.3, 0.3) * dt * 10;
      }
      const pen = drawClear();
      if (pendingDrip && pen && L) {
        pendingDrip = false;
        drips.push({ x: pen.x - L.size * 0.15, y0: pen.y + L.size * 0.25, len: 0, wob: 0,
                     max: rnd(0.4, 1) * L.size * opts.dripLength, speed: L.size * opts.dripSpeed });
      }

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, cv.width, cv.height);
      ctx.drawImage(tex, 0, 0);
      ctx.globalCompositeOperation = "destination-out";
      ctx.drawImage(clear, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      // Blanka droppar i änden av varje spår
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (const d of drips) {
        const x = d.x + d.wob, y = d.y0 + d.len, r = Math.max(2, L ? L.size * 0.045 : 3);
        const grd = ctx.createRadialGradient(x - r * 0.3, y - r * 0.3, 0, x, y, r);
        grd.addColorStop(0, `rgba(255,255,255,${0.8 * clarity})`);
        grd.addColorStop(1, `rgba(255,255,255,${0.1 * clarity})`);
        ctx.fillStyle = grd;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      }
      requestAnimationFrame(frame);
    }
    let pendingDrip = false;

    addEventListener("resize", resize);
    resize();
    requestAnimationFrame(t => { prev = t; frame(t); });
    return { show };
  }

  global.OrdklockaImma = { start };
})(window);
