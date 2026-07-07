// SVT Play (www.svtplay.se).
//
// LIMITATION: the heading selectors below are a best-effort guess at SVT
// Play's current page markup (a program title heading plus a separate
// episode title element) - likely to need adjustment as the site changes.
// Falls back to the generic MediaSession/document.title baseline when
// they don't match.
(function () {
  function refine() {
    const programEl = document.querySelector("h1");
    const episodeEl = document.querySelector('[class*="episode" i] h2, [class*="Episode" i] h2');

    if (programEl && programEl.textContent.trim() && episodeEl && episodeEl.textContent.trim()) {
      return {
        media_type: "episode",
        series_title: programEl.textContent.trim(),
        title: episodeEl.textContent.trim(),
      };
    }
    return null;
  }

  window.MediaDisplayShared.observe("svtplay", "episode", refine, 5000);
})();
