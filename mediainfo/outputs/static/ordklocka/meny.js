// Klockväljare i panelen på varje ordklocka: byter till en annan klocka.
// Visas inte när sidan är inbäddad (idle-klockan på startsidan), där
// klockan väljs med outputs.web.idle_clock_style i stället.
(function () {
  const CLOCKS = [
    ["/ordklocka", "Ordklocka"],
    ["/ordklocka/tavla", "Tågtavla"],
    ["/ordklocka/matrix", "Matrix"],
    ["/ordklocka/syntavla", "Syntavla"],
    ["/ordklocka/neon", "Neonskylt"],
    ["/ordklocka/magneter", "Kylskåpsmagneter"],
    ["/ordklocka/buss", "Busskylt"],
    ["/ordklocka/texttv", "Text-TV"],
    ["/ordklocka/brickor", "Bokstavsbrickor"],
    ["/ordklocka/broderi", "Broderi"],
    ["/ordklocka/stampel", "Bokstavsstämplar"],
    ["/ordklocka/sattlada", "Sättlåda"],
    ["/ordklocka/fonster", "Imma på rutan"],
    ["/ordklocka/rakneverk", "Räkneverk"],
    ["/ordklocka/kvitto", "Kassakvitto"],
    ["/ordklocka/domino", "Dominobrickor"],
    ["/ordklocka/ballonger", "Ballonger"],
    ["/ordklocka/stjarnor", "Stjärnhimmel"],
    ["/ordklocka/dusch", "Duschvägg"],
    ["/ordklocka/blod", "Blod på golvet"],
    ["/ordklocka/typografi", "Typografisk"],
    ["/ordklocka/cirklar", "Cirklar"],
    ["/ordklocka/terminal", "Terminal"],
    ["/ordklocka/epapper", "E-papper"],
    ["/ordklocka/konst", "Konstverk"],
    ["/ordklocka/berattande", "Berättande"],
    ["/ordklocka/schweiz", "Schweizisk typografi"],
    ["/ordklocka/zen", "Zen"],
    ["/ordklocka/brutal", "Brutalistisk"],
    ["/ordklocka/artdeco", "Art déco"],
    ["/ordklocka/nixie", "Nixierör"],
    ["/ordklocka/ledmatris", "LED-matris"],
    ["/ordklocka/skrivmaskin", "Skrivmaskin"],
    ["/ordklocka/synthwave", "Synthwave"],
    ["/ordklocka/vagor", "Vågor"],
    ["/ordklocka/spiral", "Spiral"],
    ["/ordklocka/partiklar", "Partiklar"],
    ["/ordklocka/ordmoln", "Ordmoln"],
    ["/ordklocka/3d", "3D-skulptur"],
    ["/ordklocka/poetisk", "Poetisk"],
    ["/ordklocka/dagslinje", "Dagslinjen"],
    ["/ordklocka/kalender", "Kalender"],
    ["/ordklocka/dygnsrytm", "Dygnsrytm"],
    ["/ordklocka/pixel", "Pixel (8-bit)"],
    ["/ordklocka/griffeltavla", "Griffeltavla"],
  ];
  if (new URLSearchParams(location.search).has("embedded")) return;
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
  for (const [path, name] of CLOCKS) {
    const opt = new Option(name, path, false, path === here);
    select.add(opt);
  }
  select.onchange = () => { location.href = select.value; };
  group.append(label, select);
  controls.prepend(group);
})();
