// Plex Web (app.plex.tv).
//
// Plex's web player populates MediaSession reasonably well, including
// setting `artist` to the show's name for TV episodes (the same
// convention Plex uses in its own OS media-control integrations) - this
// is used directly as the series title, rather than scraping the page's
// own (frequently-changing) internal component markup.
(function () {
  function refine(state) {
    if (!state.artist) return null; // no show name -> most likely a movie
    return {
      media_type: "episode",
      series_title: state.artist,
      title: state.title,
    };
  }

  window.MediaDisplayShared.observe("plex", "movie", refine, 5000);
})();
