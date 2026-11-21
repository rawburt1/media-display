// Gemensam tidsläsning för ordklockorna (/ordklocka och /ordklocka/tavla),
// så att båda alltid säger samma sak.
//
// 00:00–12:59 läses som vanligt ("fem i halv ett") med 12-timmarsnamn.
// Från 13:00 läses tiden digitalt: timme + minuter ("arton tjugofem"),
// utom i 12-timmarsläge där hela dygnet läses som vanligt ("fem i halv tre").
// Upplösningen är 5 minuter; `extra` är minuterna däröver (0–4).
(function (global) {
  // Timord 0–23. Timme 0 läses "tolv" (kvart över tolv).
  const HOUR_WORDS = [
    ["TOLV"], ["ETT"], ["TVÅ"], ["TRE"], ["FYRA"], ["FEM"], ["SEX"], ["SJU"],
    ["ÅTTA"], ["NIO"], ["TIO"], ["ELVA"], ["TOLV"], ["TRETTON"], ["FJORTON"],
    ["FEMTON"], ["SEXTON"], ["SJUTTON"], ["ARTON"], ["NITTON"], ["TJUGO"],
    ["TJUGO", "ETT"], ["TJUGO", "TVÅ"], ["TJUGO", "TRE"],
  ];

  // Digital läsning. Varje inre lista är ett utläst ord:
  // [["TJUGO", "FEM"]] = "tjugofem", [["NOLL"], ["FEM"]] = "noll fem".
  const DIGITAL_MINUTES = {
    0: [], 5: [["NOLL"], ["FEM"]], 10: [["TIO"]], 15: [["FEMTON"]],
    20: [["TJUGO"]], 25: [["TJUGO", "FEM"]], 30: [["TRETTIO"]],
    35: [["TRETTIO", "FEM"]], 40: [["FYRTIO"]], 45: [["FYRTIO", "FEM"]],
    50: [["FEMTIO"]], 55: [["FEMTIO", "FEM"]],
  };

  // Vanlig läsning: [minutord, nästa timme?]. style "halv" säger
  // "tio i halv"/"tio över halv" i stället för "tjugo över"/"tjugo i".
  function classicPhrase(m5, style) {
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
  }

  // 12-timmarsläge, valt i klockpanelen (meny.js). Idle-klockan på
  // startsidan (?embedded=1) har ett eget val; tills det gjorts gäller
  // ?h=12 eller ?h=24 från outputs.web.idle_clock_12h.
  const params = new URLSearchParams(location.search);
  const HOURS_KEY = params.has("embedded") ? "ordklocka-idle-timmar" : "ordklocka-timmar";
  function loadTwelveHour() {
    let saved = null;
    try { saved = localStorage.getItem(HOURS_KEY); } catch {}
    const v = saved || params.get("h");
    return v === "12";
  }
  let twelveHour = loadTwelveHour();
  function setTwelveHour(on) {
    twelveHour = !!on;
    try { localStorage.setItem(HOURS_KEY, twelveHour ? "12" : "24"); } catch {}
  }

  // Digital:  {digital: true,  hourWords: ["TJUGO","TRE"], minutes: [["FYRTIO","FEM"]], extra}
  // Vanlig:   {digital: false, hourWords: ["ETT"], minuteWords: ["FEM","I","HALV"], extra}
  function spokenTime(hour, min, style) {
    const m5 = min - (min % 5);
    const extra = min % 5;
    if (hour >= 13 && !twelveHour) {
      return { digital: true, hourWords: HOUR_WORDS[hour], minutes: DIGITAL_MINUTES[m5], extra };
    }
    const [minuteWords, bump] = classicPhrase(m5, style);
    // 12-timmarsnamn: 12:25 är "fem i halv ett", inte "... halv tretton".
    const h = (hour + bump) % 12;
    return { digital: false, hourWords: HOUR_WORDS[h], minuteWords, extra };
  }

  // De utlästa orden i ordning, versaler: ["TJUGOTRE", "FYRTIOFEM"].
  function spokenWords(t) {
    const hour = t.hourWords.join("");
    if (t.digital) return [hour, ...t.minutes.map(parts => parts.join(""))];
    return [...t.minuteWords, hour];
  }

  // "Klockan är fem i halv ett (+2 min)"
  function spokenSentence(t) {
    const extra = t.extra ? ` (+${t.extra} min)` : "";
    return ["Klockan är", ...spokenWords(t).map(w => w.toLowerCase())].join(" ") + extra;
  }

  global.OrdklockaTid = {
    spokenTime, spokenWords, spokenSentence, setTwelveHour,
    get twelveHour() { return twelveHour; },
  };
})(window);
