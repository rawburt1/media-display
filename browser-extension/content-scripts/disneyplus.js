// Disney+ (www.disneyplus.com).
//
// LIMITATION: like Netflix, this is a DRM-protected service, and its
// player UI is partly built from custom elements/shadow DOM that plain
// CSS selectors can't reliably reach into - a robust DOM scrape isn't
// attempted here. Instead this relies primarily on MediaSession (which
// Disney+ does populate for OS media controls) plus a best-effort parse
// of the page <title>, which several streaming sites format as
// "Episode Title - Series Name" or similar - a fragile heuristic, but one
// that doesn't depend on guessing internal component class names. When it
// doesn't match, the generic MediaSession baseline is reported instead.
(function () {
  function refine() {
    const title = document.title || "";
    const match = /^(.*?)\s*[-–]\s*(.*?)\s*[-–]\s*Disney\+?$/i.exec(title);
    if (match && match[1] && match[2]) {
      return {
        media_type: "episode",
        series_title: match[2].trim(),
        title: match[1].trim(),
      };
    }
    return null;
  }

  window.MediaDisplayShared.observe("disneyplus", "movie", refine, 5000);
})();
