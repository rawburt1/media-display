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
