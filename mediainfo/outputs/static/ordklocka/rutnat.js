// Ordklockans rutnät (12 x 14 bokstäver) och vilka ord som tänds.
// Delas av /ordklocka och /ordklocka/matrix; vad som sägs avgörs av tid.js.
(function (global) {
  // 12 × 14 bokstäver, 24-timmarsklocka. Ordens positioner anges nedan
  // som [rad, kolumn, längd]. FEM/SEX/SJU/TRE tänds som början av
  // FEMTON/SEXTON/SJUTTON/TRETTON, och 21–23 är TJUGO + ETT/TVÅ/TRE.
  //
  // Vad som sägs avgörs av tid.js (delas med /ordklocka/tavla). Här
  // finns bara var orden sitter: vanlig läsning (00:00–12:59) tänder
  // minutorden i rad 0–3 före timmen, digital läsning (från 13:00)
  // minutorden i rad 10–13, efter alla timord 13–23.
  const ROWS = [
    "KLOCKANTÄRSO",
    "FEMXKVARTNAD",
    "TIOFTJUGOLIS",
    "ÖVERMHALVBYN",
    "TJUGOETTTOLV",
    "TVÅTRETTONAS",
    "FJORTONFYRAK",
    "FEMTONSEXTON",
    "SJUTTONÅTTAR",
    "ARTONNITTONE",
    "NIOTIOELVAKS",
    "TJUGOTRETTIO",
    "FYRTIOFEMTIO",
    "NOLLFEMTONUR",
  ];
  const COLS = ROWS[0].length;

  const W = {
    KLOCKAN: [0, 0, 7], ÄR: [0, 8, 2],
    FEM: [1, 0, 3], KVART: [1, 4, 5],
    TIO: [2, 0, 3], TJUGO: [2, 4, 5], I: [2, 10, 1],
    ÖVER: [3, 0, 4], HALV: [3, 5, 4],
  };
  // Timord 0–23, var och en en lista av [rad, kolumn, längd]. Timme 0
  // läses "tolv" (kvart över tolv), precis som på en 12-timmarsklocka.
  const H = {
    TJUGO: [4, 0, 5], ETT: [4, 5, 3], TOLV: [4, 8, 4],
    TVÅ: [5, 0, 3], TRE: [5, 3, 3], TRETTON: [5, 3, 7],
    FJORTON: [6, 0, 7], FYRA: [6, 7, 4],
    FEM: [7, 0, 3], FEMTON: [7, 0, 6], SEX: [7, 6, 3], SEXTON: [7, 6, 6],
    SJU: [8, 0, 3], SJUTTON: [8, 0, 7], ÅTTA: [8, 7, 4],
    ARTON: [9, 0, 5], NITTON: [9, 5, 6],
    NIO: [10, 0, 3], TIO: [10, 3, 3], ELVA: [10, 6, 4],
  };
  // Minutord för digital läsning (13:00–23:59). TIO delas med timordet
  // TIO i rad 10 - alla timmar 13–23 ligger före det.
  const M = {
    TIO: [10, 3, 3], TJUGO: [11, 0, 5], TRETTIO: [11, 5, 7],
    FYRTIO: [12, 0, 6], FEMTIO: [12, 6, 6],
    NOLL: [13, 0, 4], FEM: [13, 4, 3], FEMTON: [13, 4, 6],
  };
  // Sanity check: varje ord ska matcha rutnätet.
  const check = (name, [r, c, n]) => {
    if (ROWS[r].slice(c, c + n) !== name) console.warn("Fel position för", name);
  };
  Object.entries(W).forEach(([k, v]) => check(k, v));
  Object.entries(H).forEach(([k, v]) => check(k, v));
  Object.entries(M).forEach(([k, v]) => check(k, v));
  if (ROWS.some(r => r.length !== COLS)) console.warn("Raderna är olika långa");

  // Vad som ska tändas och läsas ut: [[rad, kolumn, längd], ...] och text.
  function reading(hour, min, style) {
    const t = OrdklockaTid.spokenTime(hour, min, style);
    const hourCells = t.hourWords.map(w => H[w]);
    const lit = t.digital
      ? [W.KLOCKAN, W.ÄR, ...hourCells, ...t.minutes.flat().map(w => M[w])]
      : [W.KLOCKAN, W.ÄR, ...t.minuteWords.map(w => W[w]), ...hourCells];
    return [lit, t];
  }

  global.OrdklockaRutnat = { ROWS, COLS, W, H, M, reading };
})(window);
