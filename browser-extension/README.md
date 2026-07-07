# Media Display Now-Playing Bridge (browser extension)

Sends now-playing info from a handful of supported sites to a running
Media Display instance's `sources.browser` WebSocket server, so media
playing in a browser tab (YouTube, Spotify Web, Netflix, Disney+, SVT
Play, Plex Web) can show up the same way Kodi/Plex/Spotify/etc. already
do - see the main [README.md](../README.md)'s `sources.browser` section
for the Media Display side of this.

## What it reads (and doesn't)

Every content script reads only:

- The [MediaSession API](https://developer.mozilla.org/en-US/docs/Web/API/MediaSession)
  (`navigator.mediaSession.metadata`/`.playbackState`) - the same
  information the browser itself already uses for its own media-key
  handling and lock-screen/OS media widgets. Reading it is exactly as
  DRM-safe as the browser's own now-playing UI, since it's the same data.
- The page's own `<video>`/`<audio>` element's `paused`/`ended`/
  `currentTime`/`duration` properties, as a fallback when a site doesn't
  set MediaSession's playback state.
- `document.title`, and (on a couple of sites) small bits of clearly
  visible on-page text, such as an episode heading - see each site's
  limitations below.

It never reads cookies, local storage, network requests, DRM-protected
stream data, or any page content beyond what's listed above - and never
tries to bypass paywalls or DRM. Only the small, structured event shown
below is ever sent - never raw page content.

## Install (unpacked, for local/personal use)

This extension isn't published to any browser's store - install it
unpacked, from this folder:

**Chrome / Edge:**
1. Go to `chrome://extensions` (or `edge://extensions`).
2. Turn on "Developer mode" (top-right).
3. Click "Load unpacked" and select this `browser-extension/` folder.

**Firefox:**
1. Go to `about:debugging#/runtime/this-firefox`.
2. Click "Load Temporary Add-on…" and select `manifest.json` in this
   folder.
3. Firefox only keeps temporary add-ons until it restarts - reload it the
   same way after each restart, or package it properly if you want it to
   persist (not covered here).

After installing, open the extension's options page (right-click its
toolbar icon → Options, or find it in `chrome://extensions`) and set:

- **Media Display WebSocket URL** - `ws://<host>:<port>/ws`, matching
  `sources.browser.host`/`port` in Media Display's `config.yaml` (default
  `ws://localhost:8096/ws`).
- **Token** - only if `sources.browser.token` is set; must match exactly.
- **Enabled sites** - uncheck any you don't want reported.

## Supported sites (v1)

| Site | Metadata source | Notes |
|---|---|---|
| YouTube | MediaSession + channel name fallback | Reports as `movie` (no series/episode concept) |
| Spotify Web | MediaSession only | Reliably populated - title/artist/album/artwork |
| Netflix | MediaSession + on-page title overlay | DRM-limited; overlay selectors are best-effort, see below |
| Disney+ | MediaSession + `document.title` parsing | DRM-limited; no DOM scraping (shadow-DOM player), see below |
| SVT Play | MediaSession + page heading | Selectors are best-effort, see below |
| Plex Web | MediaSession only | Uses MediaSession's `artist` field as the show name for episodes |

## Known limitations

- **Netflix / Disney+ are DRM-protected streaming services.** Their own
  MediaSession metadata is often minimal, and this extension makes no
  attempt to work around DRM or extract anything beyond what's already
  visible on the rendered page. Series/episode separation on these two
  sites is a best-effort text/selector guess at their *current* UI as of
  when this was written - streaming sites change their markup
  periodically without notice, and when a selector stops matching, the
  affected site's content script just falls back to the generic
  MediaSession/`document.title` baseline (never a hard failure - see
  `shared/media-state.js`'s `refine()` contract). If a site's metadata
  looks wrong, that site's small content script in `content-scripts/` is
  the place to fix a selector.
- **Manifest V3 service workers are not persistent.** Chrome/Edge
  terminate `background.js` after ~30 seconds of inactivity, which can
  drop the WebSocket connection between updates on a long video with no
  state change. A `chrome.alarms`-based keep-alive (`background.js`)
  wakes the worker periodically and reconnects if needed, but there can
  still be a brief gap immediately after termination before the next
  alarm fires.
- **No authentication beyond the optional shared token.** Anyone who can
  reach `sources.browser`'s port and knows (or guesses) the token can send
  it fabricated events. Keep that port off any network you don't trust,
  same as any other locally-hosted service without its own login.
- Only the tabs you actually have open and playing are ever reported -
  there's no background history or scrobbling of any kind.

## Architecture

```text
browser-extension/
  manifest.json              Manifest V3 - permissions, content script matches
  background.js              Holds the one shared WebSocket connection
  content-scripts/
    youtube.js, spotify.js, netflix.js, disneyplus.js, svtplay.js, plex.js
                              One small file per site - calls into shared/media-state.js
  shared/
    media-state.js           MediaSession/video-element extraction + per-site refine() hook
    websocket-client.js       Small reconnecting WS client, used by background.js
  options/
    options.html, options.js  WebSocket URL / token / enabled-sites settings
```

No bundler or build step - every file is loaded as-is (content scripts
declare multiple plain `.js` files per site in `manifest.json`, sharing
one global scope; `background.js` uses `importScripts()` for its one
helper file), matching Media Display's own config UI, which follows the
same no-build-step approach.

## Event format

Each update looks like this (sent as a WebSocket text frame, JSON-encoded):

```json
{
  "source": "browser",
  "site": "youtube",
  "state": "playing",
  "title": "Example title",
  "artist": "Example artist",
  "album": null,
  "media_type": "movie",
  "artwork_url": "https://...",
  "duration": 240,
  "progress": 42,
  "url": "https://...",
  "timestamp": "2026-07-07T00:00:00Z"
}
```

Optional fields `series_title`, `season`, `episode` are added by sites
that can determine them (Netflix, Disney+, SVT Play, Plex Web) - when
present, Media Display's `browser` source reports the item the same way
every other source represents an episode (series name as the title,
"SxxEyy - episode title" as the subtitle) regardless of `media_type`.

## Testing your connection

With the extension installed and Media Display's `sources.browser`
enabled, open a supported site and start playing something - within a few
seconds it should show up on your configured Media Display outputs the
same as any other source. If it doesn't:

- Check the background service worker's console (`chrome://extensions` →
  this extension → "service worker" link) for connection errors.
- Check Media Display's own logs for `Browser source: rejected a
  connection` (token mismatch) or `ignoring a non-JSON message`/`ignoring
  an event with neither 'url' nor 'site'` (a malformed event - likely a
  bug in a content script rather than a config problem).
- Confirm the WebSocket URL's host/port actually reaches Media Display -
  `sources.browser.host` defaults to `0.0.0.0` (listens on every
  interface) but the extension's configured URL still needs the machine's
  real IP/hostname, not `0.0.0.0` itself, unless the browser and Media
  Display are on the same machine.
