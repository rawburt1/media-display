// Ordklockans rutnät och regler för vilka ord som ska lysa.
// Delas av index.html (klassisk) och matrix.html.
// Positioner anges som [rad, kolumn, längd].

(() => {
  const words = (cells, ...names) => names.map(n => cells[n]);

  // ---------- 12-timmars: "klockan är fem i halv tre" ----------
  const L12 = {
    rows: [
      "KLOCKANTÄRK",
      "FEMXKVARTNA",
      "TIOFTJUGOLI",
      "ÖVERMHALVBY",
      "ETTUTVÅTREM",
      "FYRAFEMSEXO",
      "SJUÅTTANIOP",
      "TIOELVATOLV",
    ],
    fontScale: 0.055,   // relativt klockfrontens storlek (klassisk vy)
    rowGap: "0.9em",
    W: {
      KLOCKAN: [0, 0, 7], ÄR: [0, 8, 2],
      FEM: [1, 0, 3], KVART: [1, 4, 5],
      TIO: [2, 0, 3], TJUGO: [2, 4, 5], I: [2, 10, 1],
      ÖVER: [3, 0, 4], HALV: [3, 5, 4],
    },
    HOURS: [
      [7, 7, 4], [4, 0, 3], [4, 4, 3], [4, 7, 3], [5, 0, 4], [5, 4, 3],
      [5, 7, 3], [6, 0, 3], [6, 3, 4], [6, 7, 3], [7, 0, 3], [7, 3, 4],
    ],
    HOUR_NAMES: ["tolv","ett","två","tre","fyra","fem","sex","sju","åtta","nio","tio","elva"],
    phrase(m5, style) {
      switch (m5) {
        case 0:  return [[], 0];
        case 5:  return [["FEM", "ÖVER"], 0];
        case 10: return [["TIO", "ÖVER"], 0];
        case 15: return [["KVART", "ÖVER"], 0];
        case 20: return style === "halv" ? [["TIO", "I", "HALV"], 1] : [["TJUGO", "ÖVER"], 0];
        case 25: return [["FEM", "I", "HALV"], 1];
        case 30: return [["HALV"], 1];
        case 35: return [["FEM", "ÖVER", "HALV"], 1];
        case 40: return style === "halv" ? [["TIO", "ÖVER", "HALV"], 1] : [["TJUGO", "I"], 1];
        case 45: return [["KVART", "I"], 1];
        case 50: return [["TIO", "I"], 1];
        case 55: return [["FEM", "I"], 1];
      }
    },
    compute(now, style) {
      const min = now.getMinutes();
      const [ws, bump] = this.phrase(min - (min % 5), style);
      const h = (now.getHours() + bump) % 12;
      return {
        cells: [this.W.KLOCKAN, this.W.ÄR, ...words(this.W, ...ws), this.HOURS[h]],
        text: ["Klockan är", ...ws.map(w => w.toLowerCase()), this.HOUR_NAMES[h]].join(" "),
      };
    },
    selfCheck() {
      const hn = ["TOLV","ETT","TVÅ","TRE","FYRA","FEM","SEX","SJU","ÅTTA","NIO","TIO","ELVA"];
      return [...Object.entries(this.W), ...hn.map((n, i) => [n, this.HOURS[i]])];
    },
  };

  // ---------- 24-timmars: "klockan är fjorton och trettiofem" ----------
  const L24 = {
    rows: [
      "KLOCKANTÄRTIO",
      "NOLLATJUGOETT",
      "TVÅTRENIOFYRA",
      "FEMSEXSJUÅTTA",
      "ELVATOLVARTON",
      "TRETTONNITTON",
      "FJORTONFEMTON",
      "SEXTONSJUTTON",
      "PRICKZOCHKTIO",
      "FEMTONTJUGOLA",
      "TRETTIOFYRTIO",
      "FEMTIOFEMAKBS",
    ],
    fontScale: 0.0465,
    rowGap: "0.4em",
    W: {
      KLOCKAN: [0, 0, 7], ÄR: [0, 8, 2],
      PRICK: [8, 0, 5], OCH: [8, 6, 3],
      // minuter (står efter OCH i läsordning)
      m_TIO: [8, 10, 3], m_FEMTON: [9, 0, 6], m_TJUGO: [9, 6, 5],
      m_TRETTIO: [10, 0, 7], m_FYRTIO: [10, 7, 6], m_FEMTIO: [11, 0, 6], m_FEM: [11, 6, 3],
      // timmar
      NOLL: [1, 0, 4], ETT: [1, 10, 3], TVÅ: [2, 0, 3], TRE: [2, 3, 3], FYRA: [2, 9, 4],
      FEM: [3, 0, 3], SEX: [3, 3, 3], SJU: [3, 6, 3], ÅTTA: [3, 9, 4], NIO: [2, 6, 3],
      TIO: [0, 10, 3], ELVA: [4, 0, 4], TOLV: [4, 4, 4], TRETTON: [5, 0, 7],
      FJORTON: [6, 0, 7], FEMTON: [6, 7, 6], SEXTON: [7, 0, 6], SJUTTON: [7, 6, 7],
      ARTON: [4, 8, 5], NITTON: [5, 7, 6], TJUGO: [1, 5, 5],
    },
    HOURS: [
      ["NOLL"], ["ETT"], ["TVÅ"], ["TRE"], ["FYRA"], ["FEM"], ["SEX"], ["SJU"],
      ["ÅTTA"], ["NIO"], ["TIO"], ["ELVA"], ["TOLV"], ["TRETTON"], ["FJORTON"],
      ["FEMTON"], ["SEXTON"], ["SJUTTON"], ["ARTON"], ["NITTON"], ["TJUGO"],
      ["TJUGO", "ETT"], ["TJUGO", "TVÅ"], ["TJUGO", "TRE"],
    ],
    MINUTES: {
      0: [], 5: ["FEM"], 10: ["TIO"], 15: ["FEMTON"], 20: ["TJUGO"], 25: ["TJUGO", "FEM"],
      30: ["TRETTIO"], 35: ["TRETTIO", "FEM"], 40: ["FYRTIO"], 45: ["FYRTIO", "FEM"],
      50: ["FEMTIO"], 55: ["FEMTIO", "FEM"],
    },
    compute(now) {
      const min = now.getMinutes();
      const hw = this.HOURS[now.getHours()];
      const mw = this.MINUTES[min - (min % 5)];
      const join = ws => ws.join("").toLowerCase();
      const tail = mw.length ? ["OCH", ...mw.map(w => "m_" + w)] : ["PRICK"];
      return {
        cells: words(this.W, "KLOCKAN", "ÄR", ...hw, ...tail).filter(Boolean),
        text: ["Klockan är", join(hw), mw.length ? "och " + join(mw) : "prick"].join(" "),
      };
    },
    selfCheck() {
      return Object.entries(this.W).map(([n, p]) => [n.replace(/^m_/, ""), p]);
    },
  };

  // ---------- Syntavla (12 h): rader som blir längre nedåt, "klockan är" står som rubrik ----------
  const SYN = {
    ragged: true,
    rows: [
      "FEM",
      "TIOD",
      "KVART",
      "TJUGOI",
      "ÖVERHALV",
      "ETTTVÅTRE",
      "FYRAFEMSEX",
      "SJUÅTTANIOR",
      "TIOELVATOLVZ",
    ],
    W: {
      FEM: [0, 0, 3], TIO: [1, 0, 3], KVART: [2, 0, 5],
      TJUGO: [3, 0, 5], I: [3, 5, 1], ÖVER: [4, 0, 4], HALV: [4, 4, 4],
    },
    HOURS: [
      [8, 7, 4], [5, 0, 3], [5, 3, 3], [5, 6, 3], [6, 0, 4], [6, 4, 3],
      [6, 7, 3], [7, 0, 3], [7, 3, 4], [7, 7, 3], [8, 0, 3], [8, 3, 4],
    ],
    compute(now, style) {
      const min = now.getMinutes();
      const [ws, bump] = L12.phrase(min - (min % 5), style);
      const h = (now.getHours() + bump) % 12;
      return {
        cells: [...words(this.W, ...ws), this.HOURS[h]],
        text: ["Klockan är", ...ws.map(w => w.toLowerCase()), L12.HOUR_NAMES[h]].join(" "),
      };
    },
    selfCheck() {
      const hn = ["TOLV","ETT","TVÅ","TRE","FYRA","FEM","SEX","SJU","ÅTTA","NIO","TIO","ELVA"];
      return [...Object.entries(this.W), ...hn.map((n, i) => [n, this.HOURS[i]])];
    },
  };

  // ---------- Syntavla (24 h): timmar överst (stora), minuter längst ner (små) ----------
  const SYN24 = {
    ragged: true,
    ruleAfter: 9,                         // röd linje mellan timmar och minuter
    rows: [
      "TJUGO",
      "NITTON",
      "TRETTON",
      "NOLLFYRA",
      "ETTTVÅTRE",
      "FEMTONELVA",
      "FJORTONTOLV",
      "SEXTONFEMSEX",
      "SJUTTONSJUNIO",
      "ARTONHÅTTAZTIO",
      "PRICKSOCHFEMTON",
      "TIODTJUGOTRETTIO",
      "FYRTIOCFEMTIOFEMV",
    ],
    W: {
      TJUGO: [0, 0, 5], NITTON: [1, 0, 6], TRETTON: [2, 0, 7],
      NOLL: [3, 0, 4], FYRA: [3, 4, 4],
      ETT: [4, 0, 3], TVÅ: [4, 3, 3], TRE: [4, 6, 3],
      FEMTON: [5, 0, 6], ELVA: [5, 6, 4],
      FJORTON: [6, 0, 7], TOLV: [6, 7, 4],
      SEXTON: [7, 0, 6], FEM: [7, 6, 3], SEX: [7, 9, 3],
      SJUTTON: [8, 0, 7], SJU: [8, 7, 3], NIO: [8, 10, 3],
      ARTON: [9, 0, 5], ÅTTA: [9, 6, 4], TIO: [9, 11, 3],
      PRICK: [10, 0, 5], OCH: [10, 6, 3], m_FEMTON: [10, 9, 6],
      m_TIO: [11, 0, 3], m_TJUGO: [11, 4, 5], m_TRETTIO: [11, 9, 7],
      m_FYRTIO: [12, 0, 6], m_FEMTIO: [12, 7, 6], m_FEM: [12, 13, 3],
    },
    HOURS: L24.HOURS,
    MINUTES: L24.MINUTES,
    compute: L24.compute,
    selfCheck: L24.selfCheck,
  };
  SYN.ruleAfter = 4;

  const LAYOUTS = { "12": L12, "24": L24, "syn": SYN, "syn24": SYN24 };

  // Kontroll: varje ord ska stå på rätt plats, och alla rader vara lika långa.
  for (const [key, L] of Object.entries(LAYOUTS)) {
    L.cols = Math.max(...L.rows.map(r => [...r].length));
    if (!L.ragged) L.rows.forEach((r, i) => {
      if ([...r].length !== L.cols) console.warn(`${key} h: rad ${i} har fel längd`);
    });
    L.selfCheck().forEach(([name, [r, c, n]]) => {
      if ([...L.rows[r]].slice(c, c + n).join("") !== name)
        console.warn(`${key} h: fel position för`, name);
    });
  }

  window.ORDKLOCKA_LAYOUTS = LAYOUTS;
})();
