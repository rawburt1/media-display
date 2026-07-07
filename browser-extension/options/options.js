const DEFAULT_SETTINGS = {
  wsUrl: "ws://localhost:8096/ws",
  token: "",
  enabledSites: ["youtube", "spotify", "netflix", "disneyplus", "svtplay", "plex"],
};

function load() {
  chrome.storage.sync.get(DEFAULT_SETTINGS, function (settings) {
    document.getElementById("wsUrl").value = settings.wsUrl;
    document.getElementById("token").value = settings.token;
    const enabled = new Set(settings.enabledSites);
    document.querySelectorAll(".sites input[data-site]").forEach(function (el) {
      el.checked = enabled.has(el.dataset.site);
    });
  });
}

function save() {
  const wsUrl = document.getElementById("wsUrl").value.trim() || DEFAULT_SETTINGS.wsUrl;
  const token = document.getElementById("token").value;
  const enabledSites = Array.from(document.querySelectorAll(".sites input[data-site]"))
    .filter(function (el) { return el.checked; })
    .map(function (el) { return el.dataset.site; });

  chrome.storage.sync.set({ wsUrl: wsUrl, token: token, enabledSites: enabledSites }, function () {
    const status = document.getElementById("status");
    status.textContent = "Saved.";
    setTimeout(function () { status.textContent = ""; }, 2000);
  });
}

document.addEventListener("DOMContentLoaded", load);
document.getElementById("save").addEventListener("click", save);
