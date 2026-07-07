// Netflix (www.netflix.com).
//
// LIMITATION: Netflix is a DRM-protected service - MediaSession metadata
// is often minimal or absent here, and the on-screen title overlay's
// selectors below are best-effort guesses at Netflix's current player
// markup (as of when this was written). They are very likely to need
// updating as Netflix changes its UI; when they don't match, refine()
// below just returns null and the generic MediaSession/document.title
// baseline is reported instead - never a hard failure.
(function () {
  function refine() {
    const container = document.querySelector('[data-uia="video-title"], .video-title');
    if (!container) return null;

    const seriesEl = container.querySelector("h4");
    const episodeEl = container.querySelector("span");

    if (seriesEl && episodeEl && episodeEl.textContent.trim()) {
      // Episode text is typically "S1:E4 Episode Title" - split off a
      // leading "SxEy" if present, keep the rest as the episode title.
      const raw = episodeEl.textContent.trim();
      const match = /^S(\d+):E(\d+)\s*(.*)$/i.exec(raw);
      const overrides = { series_title: seriesEl.textContent.trim() };
      if (match) {
        overrides.season = parseInt(match[1], 10);
        overrides.episode = parseInt(match[2], 10);
        overrides.title = match[3] || raw;
      } else {
        overrides.title = raw;
      }
      return overrides;
    }

    if (seriesEl && seriesEl.textContent.trim()) {
      // No episode line found - most likely a movie.
      return { media_type: "movie", title: seriesEl.textContent.trim() };
    }

    return null;
  }

  window.MediaDisplayShared.observe("netflix", "movie", refine, 5000);
})();
