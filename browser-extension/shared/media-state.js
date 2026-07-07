// Shared now-playing extraction helpers, loaded into every supported
// site's page context alongside its own small content script (see
// manifest.json - each content_scripts entry lists this file first, so
// its functions are plain globals the site script can call directly; no
// bundler/module system, matching Media Display's own plain-JS
// convention for its config UI).
//
// Primary source of truth: the MediaSession API
// (https://developer.mozilla.org/en-US/docs/Web/API/MediaSession), which
// most modern media sites already populate for the browser/OS's own
// media-key handling and lock-screen widgets - reading it is exactly as
// DRM-safe as the site's own now-playing UI, since it's the same data the
// browser itself displays. Falls back to the page's own <video>/<audio>
// element for play/pause state and progress/duration when a site doesn't
// set MediaSession's playbackState.
//
// Only ever reads: MediaSession metadata, the media element's own
// properties (paused/ended/currentTime/duration), document.title, and (on
// a few sites, via each site's own small refine() function) small bits of
// clearly-visible on-page text such as an episode heading. Never reads
// cookies, local storage, network requests, or anything not already
// visible on the rendered page.

(function () {
  function findMediaElement() {
    return document.querySelector("video, audio");
  }

  function stateFromMediaElement(el) {
    if (!el) return null;
    if (el.ended) return "stopped";
    return el.paused ? "paused" : "playing";
  }

  function stateFromMediaSession() {
    const s = navigator.mediaSession && navigator.mediaSession.playbackState;
    // "none" doesn't reliably mean "stopped" on every site that sets it -
    // only trust an explicit "playing"/"paused" here, fall back to the
    // media element otherwise.
    return s === "playing" || s === "paused" ? s : null;
  }

  function metadataFromMediaSession() {
    const meta = navigator.mediaSession && navigator.mediaSession.metadata;
    if (!meta) return null;
    const artwork = meta.artwork && meta.artwork.length ? meta.artwork[meta.artwork.length - 1].src : null;
    return {
      title: meta.title || null,
      artist: meta.artist || null,
      album: meta.album || null,
      artworkUrl: artwork || null,
    };
  }

  // Builds one normalized event. `refine(state)` (optional) is called
  // with the generic baseline already filled in, and may return an object
  // of fields to overlay on top of it (e.g. splitting a series/episode
  // title Media Session doesn't separate) - a refine() that throws just
  // leaves the generic baseline in place, so a site-specific selector
  // breaking never stops the generic fallback from still reporting
  // something.
  function buildState(site, mediaType, refine) {
    const el = findMediaElement();
    const meta = metadataFromMediaSession() || {};
    const state = stateFromMediaSession() || stateFromMediaElement(el) || "idle";

    let result = {
      source: "browser",
      site: site,
      state: state,
      title: meta.title || document.title || null,
      artist: meta.artist || null,
      album: meta.album || null,
      media_type: mediaType,
      artwork_url: meta.artworkUrl || null,
      duration: el && isFinite(el.duration) ? Math.round(el.duration) : null,
      progress: el ? Math.round(el.currentTime) : null,
      url: location.href,
      timestamp: new Date().toISOString(),
    };

    if (typeof refine === "function") {
      try {
        const overrides = refine(result);
        if (overrides) result = Object.assign(result, overrides);
      } catch (e) {
        // See function docstring above - never let this break reporting.
      }
    }

    return result;
  }

  function sendUpdate(state) {
    try {
      chrome.runtime.sendMessage(state);
    } catch (e) {
      // "Extension context invalidated" after a reload/update - nothing
      // useful to do; the next tick will either work or fail the same way
      // until the page itself is reloaded.
    }
  }

  // Ties buildState+sendUpdate together with a periodic tick (for
  // progress updates while nothing else changes) plus immediate
  // play/pause/ended reporting, so state changes feel responsive rather
  // than waiting for the next interval.
  function observe(site, mediaType, refine, intervalMs) {
    function tick() {
      sendUpdate(buildState(site, mediaType, refine));
    }

    tick();
    setInterval(tick, intervalMs || 5000);

    const el = findMediaElement();
    if (el) {
      el.addEventListener("play", tick);
      el.addEventListener("pause", tick);
      el.addEventListener("ended", tick);
    }
  }

  window.MediaDisplayShared = {
    buildState: buildState,
    sendUpdate: sendUpdate,
    observe: observe,
    findMediaElement: findMediaElement,
  };
})();
