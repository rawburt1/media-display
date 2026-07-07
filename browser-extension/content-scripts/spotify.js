// Spotify Web Player (open.spotify.com) - MediaSession is reliably
// populated with track/artist/album/artwork here, so no site-specific
// refinement is needed.
(function () {
  window.MediaDisplayShared.observe("spotify", "music", null, 3000);
})();
