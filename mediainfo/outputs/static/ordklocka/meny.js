// Klockväljare och 12/24 h-val i panelen på varje ordklocka.
// Inbäddad (idle-klockan på startsidan, ?embedded=1) gäller valen bara
// idle-klockan i den här webbläsaren: klockan sparas i IDLE_KEY och läses
// av startsidan, och "Enligt inställningarna" går tillbaka till
// outputs.web.idle_clock_style.
(function () {
  const CLOCKS = [
    ["/ordklocka", "Ordklocka"],
    ["/ordklocka/tavla", "Tågtavla"],
    ["/ordklocka/matrix", "Matrix"],
    ["/ordklocka/neon", "Neonskylt"],
    ["/ordklocka/magneter", "Kylskåpsmagneter"],
    ["/ordklocka/buss", "Busskylt"],
    ["/ordklocka/texttv", "Text-TV"],
    ["/ordklocka/brickor", "Bokstavsbrickor"],
    ["/ordklocka/broderi", "Broderi"],
    ["/ordklocka/rakneverk", "Räkneverk"],
    ["/ordklocka/ballonger", "Ballonger"],
    ["/ordklocka/stjarnor", "Stjärnhimmel"],
    ["/ordklocka/typografi", "Typografisk"],
    ["/ordklocka/terminal", "Terminal"],
    ["/ordklocka/epapper", "E-papper"],
    ["/ordklocka/konst", "Konstverk"],
    ["/ordklocka/berattande", "Berättande"],
    ["/ordklocka/schweiz", "Schweizisk typografi"],
    ["/ordklocka/zen", "Zen"],
    ["/ordklocka/brutal", "Brutalistisk"],
    ["/ordklocka/nixie", "Nixierör"],
    ["/ordklocka/ledmatris", "LED-matris"],
    ["/ordklocka/vagor", "Vågor"],
    ["/ordklocka/ordmoln", "Ordmoln"],
    ["/ordklocka/3d", "3D-skulptur"],
    ["/ordklocka/poetisk", "Poetisk"],
    ["/ordklocka/dagslinje", "Dagslinjen"],
    ["/ordklocka/kalender", "Kalender"],
    ["/ordklocka/dygnsrytm", "Dygnsrytm"],
    ["/ordklocka/pixel", "Pixel (8-bit)"],
    ["/ordklocka/griffeltavla", "Griffeltavla"],
    ["/ordklocka/fiberoptik", "Fiberoptik"],
    ["/ordklocka/glasmosaik", "Glasmosaik"],
    ["/ordklocka/akvarell", "Akvarell"],
    ["/ordklocka/sand", "Sandträdgård"],
    ["/ordklocka/kugghjul", "Kugghjul"],
    ["/ordklocka/rullband", "Rullband"],
    ["/ordklocka/glitch", "Glitch"],
    ["/ordklocka/tessellation", "Tessellation"],
    ["/ordklocka/fraktal", "Fraktal"],
    ["/ordklocka/voronoi", "Voronoi"],
    ["/ordklocka/smalt", "Smältande"],
    ["/ordklocka/vader", "Väder"],
    ["/ordklocka/ordletare", "Ordletare"],
    ["/ordklocka/flock", "Självorganiserande"],
    ["/ordklocka/manuskript", "Medeltida manuskript"],
    ["/ordklocka/tidning", "Tidning"],
    ["/ordklocka/skarmslackare", "Skärmsläckare"],
    ["/ordklocka/ascii", "ASCII"],
    ["/ordklocka/perspektiv", "Perspektiv"],
    ["/ordklocka/kalejdoskop", "Kalejdoskop"],
    ["/ordklocka/tangram", "Tangram"],
    ["/ordklocka/kalligrafi", "Kalligrafi"],
    ["/ordklocka/variabel", "Variabelt typsnitt"],
    ["/ordklocka/urklipp", "Tidningsurklipp"],
    ["/ordklocka/timglas", "Timglas"],
    ["/ordklocka/norrsken", "Norrsken"],
    ["/ordklocka/betong", "Betong"],
    ["/ordklocka/binar", "Binär"],
    ["/ordklocka/biograf", "Biograf"],
    ["/ordklocka/bioluminiscens", "Bioluminiscens"],
    ["/ordklocka/bokhylla", "Bokhylla"],
    ["/ordklocka/cylinder", "Cylinder"],
    ["/ordklocka/dna", "DNA"],
    ["/ordklocka/dos", "DOS"],
    ["/ordklocka/eldflugor", "Eldflugor"],
    ["/ordklocka/fasad", "Kinetisk fasad"],
    ["/ordklocka/flipper", "Flipperspel"],
    ["/ordklocka/frost", "Frost"],
    ["/ordklocka/gravitation", "Gravitation"],
    ["/ordklocka/halkort", "Hålkort"],
    ["/ordklocka/hojdkurvor", "Höjdkurvor"],
    ["/ordklocka/hologram", "Hologram"],
    ["/ordklocka/hud", "HUD"],
    ["/ordklocka/kakel", "Kakelplattor"],
    ["/ordklocka/kalenderord", "Kalenderord"],
    ["/ordklocka/keramik", "Keramik"],
    ["/ordklocka/korsord", "Korsord"],
    ["/ordklocka/kristall", "Kristall"],
    ["/ordklocka/labyrint", "Labyrint"],
    ["/ordklocka/lava", "Lava"],
    ["/ordklocka/ljudvag", "Ljudvåg"],
    ["/ordklocka/ljusmalning", "Ljusmålning"],
    ["/ordklocka/lov", "Löv"],
    ["/ordklocka/manfas", "Månfas"],
    ["/ordklocka/marmorering", "Marmorering"],
    ["/ordklocka/mekanisk", "Mekanisk blädderklocka"],
    ["/ordklocka/moln", "Moln"],
    ["/ordklocka/mossa", "Mossa"],
    ["/ordklocka/optisk", "Optisk illusion"],
    ["/ordklocka/ordbok", "Ordbok"],
    ["/ordklocka/origami", "Origami"],
    ["/ordklocka/oversattning", "Översättning"],
    ["/ordklocka/planeter", "Planeter"],
    ["/ordklocka/pointillism", "Pointillism"],
    ["/ordklocka/praglad", "Präglad metall"],
    ["/ordklocka/rispapper", "Rispapper"],
    ["/ordklocka/romersk", "Romersk inskription"],
    ["/ordklocka/skuggor", "Skuggor"],
    ["/ordklocka/stad", "Stadsbyggare"],
    ["/ordklocka/station", "Stationsklocka"],
    ["/ordklocka/trasnideri", "Träsnideri"],
    ["/ordklocka/varld", "Världsklocka"],
    ["/ordklocka/vatten", "Vattenspegel"],
    ["/ordklocka/viktoriansk", "Viktoriansk"],
  ];
  const embedded = new URLSearchParams(location.search).has("embedded");
  const IDLE_KEY = "ordklocka-idle-klocka";
  const controls = document.querySelector(".panel .controls");
  if (!controls) return;

  const css = document.createElement("style");
  css.textContent = `
    .panel select.clock-menu {
      font: inherit; color: inherit; background: transparent; cursor: pointer;
      border: 1px solid color-mix(in srgb, currentColor 35%, transparent);
      border-radius: 999px; padding: 4px 10px;
    }
    .panel select.clock-menu option { color: #111; background: #fff; }
  `;
  document.head.appendChild(css);

  const here = location.pathname.replace(/\/+$/, "") || "/ordklocka";
  const group = document.createElement("div");
  group.className = "group";
  const label = document.createElement("label");
  label.className = "label";
  label.htmlFor = "clock-menu";
  label.textContent = "Klocka";
  const select = document.createElement("select");
  select.id = "clock-menu";
  select.className = "clock-menu";
  let override = null;
  if (embedded) {
    try { override = localStorage.getItem(IDLE_KEY); } catch {}
    select.add(new Option("Enligt inställningarna", "", false, !override));
  }
  for (const [path, name] of CLOCKS) {
    const opt = new Option(name, path, false, path === here && (!embedded || !!override));
    select.add(opt);
  }
  select.onchange = () => {
    if (!embedded) { location.href = select.value; return; }
    // Startsidan väljer sidan nästa gång idle-klockan visas; byt direkt
    // här också. Tomt val = tillbaka till inställningarnas klocka.
    try {
      if (select.value) localStorage.setItem(IDLE_KEY, select.value);
      else localStorage.removeItem(IDLE_KEY);
    } catch {}
    if (select.value) location.href = select.value + location.search;
    else parent.postMessage("ordklocka-idle-reset", location.origin);
  };
  group.append(label, select);
  controls.prepend(group);

  // 12- eller 24-timmarsläge (tid.js). Sidan laddas om så att varje klocka
  // ritar om från början med den nya läsningen.
  const T = window.OrdklockaTid;
  if (!T || !T.setTwelveHour) return;
  const hours = document.createElement("div");
  hours.className = "group";
  hours.setAttribute("role", "group");
  hours.setAttribute("aria-label", "12- eller 24-timmarsklocka");
  const hoursLabel = document.createElement("span");
  hoursLabel.className = "label";
  hoursLabel.textContent = "Timmar";
  hours.appendChild(hoursLabel);
  for (const [value, text] of [[false, "24 h"], [true, "12 h"]]) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.setAttribute("aria-pressed", T.twelveHour === value);
    b.onclick = () => {
      if (T.twelveHour === value) return;
      T.setTwelveHour(value);
      location.reload();
    };
    hours.appendChild(b);
  }
  group.after(hours);
})();
