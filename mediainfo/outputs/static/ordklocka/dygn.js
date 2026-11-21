// Dygnets delar (poetiska klockan, dagslinjen, dygnsrytmen, berättande
// klockan). OrdklockaDygn.part(timme) -> {key, name, the, phrase, from, to}
//   name:   "förmiddag"            (obestämd form)
//   the:    "förmiddagen"          (bestämd form)
//   phrase: "på förmiddagen"
//   from/to: timmarna delen gäller (to ej inräknad)
(function (global) {
  const PARTS = [
    { key: "natt", name: "natt", the: "natten", phrase: "på natten", from: 0, to: 5 },
    { key: "morgon", name: "morgon", the: "morgonen", phrase: "på morgonen", from: 5, to: 9 },
    { key: "formiddag", name: "förmiddag", the: "förmiddagen", phrase: "på förmiddagen", from: 9, to: 12 },
    { key: "middag", name: "middag", the: "middagen", phrase: "mitt på dagen", from: 12, to: 13 },
    { key: "eftermiddag", name: "eftermiddag", the: "eftermiddagen", phrase: "på eftermiddagen", from: 13, to: 18 },
    { key: "kvall", name: "kväll", the: "kvällen", phrase: "på kvällen", from: 18, to: 24 },
  ];

  function part(hour) {
    return PARTS.find(p => hour >= p.from && hour < p.to);
  }

  global.OrdklockaDygn = { PARTS, part };
})(window);
