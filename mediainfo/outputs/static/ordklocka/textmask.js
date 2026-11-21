// Text som mask: raderna ritas centrerat på en dold canvas och kan sedan
// läsas punkt för punkt (fiberoptik, mosaik, voronoi, norrsken m.fl.).
//   OrdklockaMask.mask(lines, w, h, opts) -> {w, h, size, at(x, y) 0..1, canvas}
//   OrdklockaMask.points(mask, step)      -> [[x, y], ...] inne i texten
// opts: family, weight, lineHeight (1.05), pad (andel av kanten, 0.06),
//       maxSize, blur (px, mjuk kant), box {x, y, w, h} (i stället för hela ytan)
(function (global) {
  const FAMILY = '"Arial Black", "Helvetica Neue", "Liberation Sans", "DejaVu Sans", sans-serif';

  function mask(lines, w, h, opts = {}) {
    w = Math.max(1, Math.round(w)); h = Math.max(1, Math.round(h));
    const family = opts.family || FAMILY;
    const weight = opts.weight || 900;
    const lh = opts.lineHeight || 1.05;
    const pad = opts.pad ?? 0.06;
    const box = opts.box || { x: w * pad, y: h * pad, w: w * (1 - 2 * pad), h: h * (1 - 2 * pad) };
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const g = c.getContext("2d", { willReadFrequently: true });
    let size = box.h / (lines.length * lh);
    g.font = `${weight} ${size}px ${family}`;
    const widest = Math.max(1, ...lines.map(l => g.measureText(l).width));
    size = Math.min(size, size * box.w / widest, opts.maxSize || Infinity);
    g.font = `${weight} ${size}px ${family}`;
    g.textAlign = "center"; g.textBaseline = "middle"; g.fillStyle = "#fff";
    if (opts.blur) g.filter = `blur(${opts.blur}px)`;
    const cx = box.x + box.w / 2;
    const top = box.y + box.h / 2 - (lines.length - 1) * size * lh / 2;
    lines.forEach((l, i) => g.fillText(l, cx, top + i * size * lh + size * 0.05));
    const data = g.getImageData(0, 0, w, h).data;
    const at = (x, y) => {
      x = x | 0; y = y | 0;
      return x >= 0 && y >= 0 && x < w && y < h ? data[(y * w + x) * 4 + 3] / 255 : 0;
    };
    return { w, h, size, at, canvas: c };
  }

  function points(m, step) {
    const out = [];
    for (let y = step / 2; y < m.h; y += step) {
      for (let x = step / 2; x < m.w; x += step) if (m.at(x, y) > 0.5) out.push([x, y]);
    }
    return out;
  }

  global.OrdklockaMask = { FAMILY, mask, points };
})(window);
