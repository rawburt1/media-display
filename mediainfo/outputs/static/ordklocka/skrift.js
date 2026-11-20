// Handskriven text som skrivs fram tecken för tecken (imma på rutan,
// duschväggen, blodet på golvet). Ritar på en vanlig 2D-canvas.
(function (global) {
  const HAND = '"Segoe Print", "Bradley Hand", "Comic Sans MS", "Purisa", "Z003", "URW Chancery L", cursive';

  // Lägger ut rader centrerat i rutan box = {x, y, w, h}.
  // fontOf(size) ger CSS-typsnittet för en viss storlek.
  function layout(ctx, lines, box, fontOf, opts = {}) {
    const lh = opts.lineHeight || 1.25;
    let size = Math.min(box.h / (lines.length * lh), opts.maxSize || Infinity);
    ctx.font = fontOf(size);
    const widest = Math.max(...lines.map(l => ctx.measureText(l).width));
    if (widest > box.w) size *= box.w / widest;
    const font = fontOf(size);
    ctx.font = font;
    const total = lines.length * size * lh;
    const out = lines.map((text, i) => {
      const prefix = [0];
      for (let k = 1; k <= text.length; k++) prefix.push(ctx.measureText(text.slice(0, k)).width);
      const w = prefix[text.length];
      return { text, w, prefix, x: box.x + (box.w - w) / 2, y: box.y + (box.h - total) / 2 + (i + 0.5) * size * lh };
    });
    return { size, font, lines: out, chars: out.reduce((s, l) => s + l.text.length, 0) };
  }

  // Ritar texten fram till `progress` tecken (decimaler = halvskrivet tecken)
  // genom draw(ctx, line) inom en klippruta. Returnerar pennans position.
  function drawPartial(ctx, L, progress, draw) {
    let left = progress, pen = null;
    for (const line of L.lines) {
      if (left <= 0) break;
      const n = line.text.length;
      const k = Math.min(n, left);
      const whole = Math.floor(k);
      const next = line.prefix[Math.min(n, whole + 1)];
      const xEnd = line.x + line.prefix[whole] + (k - whole) * (next - line.prefix[whole]);
      ctx.save();
      ctx.beginPath();
      const done = k >= n;
      ctx.rect(line.x - L.size, line.y - L.size * 1.2, (done ? line.w + 2 * L.size : xEnd - line.x + L.size), L.size * 2.4);
      ctx.clip();
      draw(ctx, line);
      ctx.restore();
      pen = { x: xEnd, y: line.y };
      left -= n;
    }
    return pen;
  }

  global.OrdklockaSkrift = { HAND, layout, drawPartial };
})(window);
