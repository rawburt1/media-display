// Ordklockornas rutnät och vilka ord som tänds. Vad som sägs avgörs av
// tid.js; här finns bara var orden sitter.
//   OrdklockaRutnat          - ordklockans 12 x 14 (/ordklocka, /ordklocka/matrix)
//   OrdklockaRutnat.SYNTAVLA - syntavlans rader, längre nedåt (/ordklocka/syntavla)
(function (global) {
  // Ett rutnät: rader + var orden sitter, [rad, kolumn, längd].
  //   W: KLOCKAN/ÄR (om de står i rutnätet) och minutorden för vanlig läsning
  //   H: timorden 0-23 (TJUGO + ETT/TVÅ/TRE för 21-23)
  //   M: minutorden för digital läsning, efter alla timord 13-23
  function grid(name, ROWS, W, H, M, opts = {}) {
    const COLS = Math.max(...ROWS.map(r => [...r].length));
    const check = (word, [r, c, n]) => {
      if ([...ROWS[r]].slice(c, c + n).join("") !== word) console.warn(name, "fel position för", word);
    };
    [W, H, M].forEach(map => Object.entries(map).forEach(([k, v]) => check(k, v)));
    if (!opts.ragged && ROWS.some(r => [...r].length !== COLS)) console.warn(name, "raderna är olika långa");

    // Vad som ska tändas och läsas ut: [[rad, kolumn, längd], ...] och tiden.
    function reading(hour, min, style) {
      const t = OrdklockaTid.spokenTime(hour, min, style);
      const prefix = [W.KLOCKAN, W.ÄR].filter(Boolean);
      const hourCells = t.hourWords.map(w => H[w]);
      const lit = t.digital
        ? [...prefix, ...hourCells, ...t.minutes.flat().map(w => M[w])]
        : [...prefix, ...t.minuteWords.map(w => W[w]), ...hourCells];
      return [lit, t];
    }
    return { ROWS, COLS, W, H, M, reading, ...opts };
  }

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
  const WORD_CLOCK = grid("ordklocka", ROWS, W, H, M);

  // Syntavlan: "KLOCKAN ÄR" står som rubrik ovanför, och raderna blir
  // längre (och bokstäverna mindre) nedåt. Samma läsordning som ovan:
  // vanliga minutord i rad 0-4, timord i rad 5-11, digitala minutord sist.
  const SYNTAVLA = grid("syntavla", [
    "FEM",
    "TIOD",
    "KVART",
    "TJUGOI",
    "ÖVERHALV",
    "TJUGOETTN",
    "TVÅTRETTON",
    "FYRAFEMTONB",
    "SEXTONNITTON",
    "SJUTTONZÅTTAP",
    "FJORTONELVATOLV",
    "ARTONNIOTIOTJUGO",
    "TRETTIOFYRTIOKSDH",
    "FEMTIONOLLFEMTONUR",
  ], {
    FEM: [0, 0, 3], TIO: [1, 0, 3], KVART: [2, 0, 5],
    TJUGO: [3, 0, 5], I: [3, 5, 1], ÖVER: [4, 0, 4], HALV: [4, 4, 4],
  }, {
    TJUGO: [5, 0, 5], ETT: [5, 5, 3],
    TVÅ: [6, 0, 3], TRE: [6, 3, 3], TRETTON: [6, 3, 7],
    FYRA: [7, 0, 4], FEM: [7, 4, 3], FEMTON: [7, 4, 6],
    SEX: [8, 0, 3], SEXTON: [8, 0, 6], NITTON: [8, 6, 6],
    SJU: [9, 0, 3], SJUTTON: [9, 0, 7], ÅTTA: [9, 8, 4],
    FJORTON: [10, 0, 7], ELVA: [10, 7, 4], TOLV: [10, 11, 4],
    ARTON: [11, 0, 5], NIO: [11, 5, 3], TIO: [11, 8, 3],
  }, {
    // TIO delas med timordet TIO - alla timmar 13-23 står före det.
    TIO: [11, 8, 3], TJUGO: [11, 11, 5],
    TRETTIO: [12, 0, 7], FYRTIO: [12, 7, 6],
    FEMTIO: [13, 0, 6], NOLL: [13, 6, 4], FEM: [13, 10, 3], FEMTON: [13, 10, 6],
  }, { ragged: true, ruleAfter: 4 });

  global.OrdklockaRutnat = { ...WORD_CLOCK, SYNTAVLA };
})(window);
