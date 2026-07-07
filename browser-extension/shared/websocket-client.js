// Small reconnecting WebSocket client, used only by background.js (loaded
// there via importScripts() - MV3 service workers aren't ES modules by
// default, and this extension has no bundler/build step, matching Media
// Display's own plain-JS convention).
//
// Held in the background service worker rather than in each content
// script: content scripts run in an isolated per-tab page context and
// can't share one outbound connection directly, so every page's content
// script instead relays its own updates here via chrome.runtime.sendMessage
// (see shared/media-state.js), and this is the only place that actually
// talks to Media Display.

(function () {
  let socket = null;
  let url = null;
  let reconnectTimer = null;

  function connect(wsUrl) {
    url = wsUrl;
    _open();
  }

  function _open() {
    if (!url) return;
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;

    try {
      socket = new WebSocket(url);
    } catch (e) {
      _scheduleReconnect();
      return;
    }

    socket.onopen = function () {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };
    socket.onclose = function () {
      socket = null;
      _scheduleReconnect();
    };
    socket.onerror = function () {
      // onclose always follows in every browser this targets - nothing
      // extra to do here.
    };
  }

  function _scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      _open();
    }, 5000);
  }

  function send(event) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(event));
      return true;
    }
    return false;
  }

  function isConnected() {
    return !!socket && socket.readyState === WebSocket.OPEN;
  }

  self.MediaDisplayWS = { connect: connect, send: send, isConnected: isConnected };
})();
