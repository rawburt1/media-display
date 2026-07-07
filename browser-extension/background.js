// Background service worker: relays now-playing events from whichever
// content script sent them to the configured Media Display "browser"
// source, over a single shared WebSocket connection.
//
// Known Manifest V3 limitation: service workers are terminated after
// roughly 30 seconds of inactivity, which can silently drop the
// WebSocket connection between updates (e.g. while a long video plays
// with no state change). The chrome.alarms-based keep-alive below wakes
// this worker periodically and reconnects if needed - not a perfect fix
// (there can still be a brief gap right after termination), but enough
// that a stale connection doesn't stay stale indefinitely.

importScripts("shared/websocket-client.js");

const DEFAULT_SETTINGS = {
  wsUrl: "ws://localhost:8096/ws",
  token: "",
  enabledSites: ["youtube", "spotify", "netflix", "disneyplus", "svtplay", "plex"],
};

let enabledSites = null; // null until loaded, then a Set

function buildWsUrl(settings) {
  const base = (settings.wsUrl || DEFAULT_SETTINGS.wsUrl).replace(/\/$/, "");
  if (!settings.token) return base;
  const sep = base.indexOf("?") !== -1 ? "&" : "?";
  return base + sep + "token=" + encodeURIComponent(settings.token);
}

function loadSettingsAndConnect() {
  chrome.storage.sync.get(DEFAULT_SETTINGS, function (settings) {
    enabledSites = new Set(settings.enabledSites || DEFAULT_SETTINGS.enabledSites);
    MediaDisplayWS.connect(buildWsUrl(settings));
  });
}

chrome.runtime.onMessage.addListener(function (message) {
  if (!message || typeof message !== "object" || !message.site) return;
  if (enabledSites && !enabledSites.has(message.site)) return;
  MediaDisplayWS.send(message);
});

// Reconnect with the new URL/token/site list as soon as the options page
// saves a change, rather than requiring the browser to restart.
chrome.storage.onChanged.addListener(function () {
  loadSettingsAndConnect();
});

chrome.alarms.create("keep-alive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener(function (alarm) {
  if (alarm.name === "keep-alive" && !MediaDisplayWS.isConnected()) {
    loadSettingsAndConnect();
  }
});

loadSettingsAndConnect();
