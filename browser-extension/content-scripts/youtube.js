// YouTube (www.youtube.com) - regular video pages and YouTube Music share
// this domain's player; MediaSession is usually populated with the video
// title and, on Music, the artist too. For a plain video (no MediaSession
// artist), the channel name is used as a reasonable stand-in.
(function () {
  function refine(state) {
    if (state.artist) return null;
    const channelEl = document.querySelector(
      "ytd-video-owner-renderer #channel-name a, #owner #channel-name a, ytd-channel-name #text"
    );
    if (channelEl && channelEl.textContent.trim()) {
      return { artist: channelEl.textContent.trim() };
    }
    return null;
  }

  window.MediaDisplayShared.observe("youtube", "movie", refine, 5000);
})();
