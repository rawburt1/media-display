"""HTML/CSS/JS templates for the web output's pages: the main now-playing
page (_INDEX_HTML) and the status dashboard (_HEALTH_HTML).

Split out from web.py - these are returned verbatim (modulo the
transitions CSS/JS placeholder substitution done once in WebOutput.__init__)
with no further per-instance interpolation, so they're pure static assets
that happen to be Python string literals; keeping them separate from
WebOutput's actual route/business logic keeps that file from growing
without bound every time a button gets added to a page.
"""

_INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Now Playing</title>
  <style>
    html, body { margin: 0; height: 100%; background: #000; color: #fff;
                  font-family: sans-serif; display: flex; flex-direction: column;
                  align-items: center; justify-content: center; }
    #art-container { position: relative; width: 100vw; height: 90vh; }
    #art-container.fullscreen { height: 100vh; }
    #art-container img {
      position: absolute; top: 0; left: 0; width: 100%; height: 100%;
      object-fit: contain; opacity: 0;
      transition: opacity 1s ease-in-out, transform 1s ease-in-out;
    }
    #art-container.fullscreen img { object-fit: cover; }
    /* __TRANSITIONS_CSS__ */
    #meta { text-align: center; padding: 0.5em; }
    #meta.hidden { display: none; }
    #title { font-size: 1.5em; }
    #subtitle { font-size: 1em; opacity: 0.8; }
    #art-label { font-size: 0.8em; opacity: 0.5; margin-top: 0.3em; }
  </style>
</head>
<body>
  <div id="art-container">
    <img id="art-a" alt="">
    <img id="art-b" alt="">
  </div>
  <div id="meta">
    <div id="title"></div>
    <div id="subtitle"></div>
    <div id="art-label"></div>
  </div>
  <script>
    /* __TRANSITIONS_JS__ */

    let lastImage = null;
    let activeImg = document.getElementById("art-a");
    let standbyImg = document.getElementById("art-b");

    function showImage(src) {
      prepareForTransition(standbyImg);
      standbyImg.onload = standbyImg.onerror = () => {
        activeImg.classList.remove("visible");
        standbyImg.classList.add("visible");
        [activeImg, standbyImg] = [standbyImg, activeImg];
      };
      standbyImg.src = src;
    }

    function applyState(data) {
      const title = document.getElementById("title");
      const subtitle = document.getElementById("subtitle");
      const artLabel = document.getElementById("art-label");
      const artContainer = document.getElementById("art-container");
      const meta = document.getElementById("meta");

      if (data.image) {
        if (data.image !== lastImage) {
          showImage(data.image);
          lastImage = data.image;
        }
      } else {
        activeImg.classList.remove("visible");
        standbyImg.classList.remove("visible");
        lastImage = null;
      }

      const isIdle = data.source === "idle";
      artContainer.classList.toggle("fullscreen", isIdle);
      meta.classList.toggle("hidden", isIdle);

      title.textContent = data.title || "";
      subtitle.textContent = data.subtitle || "";
      artLabel.textContent = data.art_label || "";
    }

    function connect() {
      const ws = new WebSocket("ws://" + location.host + "/ws");
      ws.onmessage = (event) => { applyState(JSON.parse(event.data)); };
      ws.onclose = () => { setTimeout(connect, 3000); };
      ws.onerror = () => { ws.close(); };
    }

    connect();
  </script>
</body>
</html>
"""


_HEALTH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>mediainfo · health</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #080d1a; color: #c0ccdf;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px; min-height: 100vh;
      padding: 24px 20px; max-width: 1080px; margin: 0 auto;
    }
    h1 { font-size: 17px; font-weight: 700; color: #e8f0ff; }

    /* Header */
    .hdr { display: flex; align-items: center; gap: 12px;
           margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #141e33; }
    .hdr-icon { width: 32px; height: 32px; border-radius: 9px; background: #10203f;
                display: flex; align-items: center; justify-content: center; font-size: 17px; }
    .uptime { font-size: 12px; color: #6b7fa8; background: #0d1629;
              padding: 4px 10px; border-radius: 6px; border: 1px solid #1a2540; }
    .pill { margin-left: auto; padding: 5px 14px; border-radius: 999px;
            font-size: 11px; font-weight: 700; letter-spacing: 0.9px; text-transform: uppercase; }
    .pill.healthy  { background: #051a0d; color: #22c55e; border: 1px solid #0d3320; }
    .pill.degraded { background: #1a0505; color: #f87171; border: 1px solid #33100d; }
    .pill.loading  { background: #0d1629; color: #6b7fa8; border: 1px solid #1a2540; }

    /* Now Playing */
    .np { background: #0d1629; border: 1px solid #1a2540; border-radius: 14px;
          padding: 16px 20px; margin-bottom: 18px; display: flex; align-items: center; gap: 14px; }
    .np-bar { width: 5px; height: 44px; border-radius: 3px; flex-shrink: 0; }
    .np-body { flex: 1; min-width: 0; }
    .sect-label { font-size: 10px; font-weight: 700; letter-spacing: 1.3px;
                  text-transform: uppercase; color: #3b5070; margin-bottom: 5px; }
    .np-title { font-size: 16px; font-weight: 600; color: #dce8ff;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .np-meta { font-size: 12px; color: #4a5f7a; margin-top: 3px; }
    .np-idle .np-title { color: #3b5070; font-style: italic; font-size: 14px; }
    .np-count { font-size: 11px; color: #3b5070; white-space: nowrap; }

    /* Grid */
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
    @media (max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }

    /* Cards */
    .card { background: #0d1629; border: 1px solid #1a2540; border-radius: 14px; padding: 16px 18px; }

    /* Items */
    .item { display: grid; grid-template-columns: 12px 1fr auto auto;
            align-items: center; gap: 8px; padding: 7px 0;
            border-bottom: 1px solid #080d1a; }
    .item:last-child { border-bottom: none; }
    .dot { font-size: 7px; }
    .iname { font-size: 13px; font-weight: 500; color: #a0b4cc;
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .idetail { font-size: 11px; color: #4a5f7a; font-family: ui-monospace, monospace;
               text-align: right; white-space: nowrap; }
    .badge { font-size: 10px; font-weight: 700; letter-spacing: 0.3px;
             padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
    .img-tag { display: inline-block; font-size: 11px; color: #6b7fa8;
               background: #111827; border: 1px solid #1a2540;
               border-radius: 4px; padding: 1px 7px; margin: 3px 3px 0 0; }
    .err-msg { grid-column: 2 / -1; font-size: 11px; color: #c87070;
               font-family: ui-monospace, monospace; background: #0d0505;
               border-radius: 4px; padding: 3px 7px; margin-top: -3px;
               white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    /* Status colours — dot colour class / badge style */
    .c-ok  { color: #22c55e; } .bg-ok  { background: #031108; color: #22c55e; }
    .c-act { color: #4ade80; } .bg-act { background: #031108; color: #4ade80; }
    .c-idl { color: #60a5fa; } .bg-idl { background: #050f24; color: #60a5fa; }
    .c-dis { color: #f59e0b; } .bg-dis { background: #150e00; color: #f59e0b; }
    .c-ncf { color: #94a3b8; } .bg-ncf { background: #111827; color: #94a3b8; }
    .c-err { color: #f87171; } .bg-err { background: #130303; color: #f87171; }
    .c-wrn { color: #f59e0b; } .bg-wrn { background: #150e00; color: #f59e0b; }

    .footer { margin-top: 18px; font-size: 11px; color: #1e2d40; text-align: center; }
  </style>
</head>
<body>
<div class="hdr">
  <div class="hdr-icon">&#x1F4FA;</div>
  <h1>mediainfo</h1>
  <span class="uptime" id="uptime">&#x2014;</span>
  <span class="pill loading" id="pill">loading</span>
</div>

<div class="np" id="np">
  <div class="np-bar" id="np-bar" style="background:#1a2540"></div>
  <div class="np-body">
    <div class="sect-label">Now Playing</div>
    <div class="np-title" id="np-title">&#x2014;</div>
    <div class="np-meta"  id="np-meta"></div>
    <div id="np-imgs" style="margin-top:6px"></div>
  </div>
  <div class="np-count" id="np-count"></div>
</div>

<div class="grid2">
  <div class="card"><div class="sect-label">Sources</div><div id="sources"></div></div>
  <div class="card"><div class="sect-label">Outputs</div><div id="outputs"></div></div>
</div>
<div class="grid2">
  <div class="card"><div class="sect-label">Enrichers</div><div id="enrichers"></div></div>
  <div class="card"><div class="sect-label">Idle Sources</div><div id="idle"></div></div>
</div>

<div class="footer" id="footer">connecting&hellip;</div>

<script>
var P = {
  ok:             {dot:'c-ok',  bg:'bg-ok',  lbl:'ok'},
  active:         {dot:'c-act', bg:'bg-act', lbl:'active'},
  idle:           {dot:'c-idl', bg:'bg-idl', lbl:'idle'},
  disabled:       {dot:'c-dis', bg:'bg-dis', lbl:'disabled'},
  not_configured: {dot:'c-ncf', bg:'bg-ncf', lbl:'not configured'},
  error:          {dot:'c-err', bg:'bg-err', lbl:'error'},
  starting:       {dot:'c-wrn', bg:'bg-wrn', lbl:'starting'},
};

function p(s){ return P[s] || P.not_configured; }
function badge(s){ return '<span class="badge ' + p(s).bg + '">' + p(s).lbl + '</span>'; }
function dot(s)  { return '<span class="dot '   + p(s).dot + '">&#9679;</span>'; }

function fmtUp(s){
  s = Math.round(s);
  if (s < 60)   return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm ' + (s%60) + 's';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}
function fmtAgo(s){
  if (s == null) return '';
  s = Math.round(s);
  return s < 60 ? s + 's ago' : Math.floor(s/60) + 'm ago';
}

function row(name, status, detail, errMsg){
  var err = errMsg ? '<div class="err-msg">&#x26A0; ' + errMsg.slice(0,120) + '</div>' : '';
  return '<div class="item">'
    + dot(status)
    + '<span class="iname">' + name + '</span>'
    + '<span class="idetail">' + (detail||'') + '</span>'
    + badge(status) + err
    + '</div>';
}

function render(d){
  var hasErr = (d.outputs||[]).some(function(o){ return o.status === 'error'; });
  var overall = hasErr ? 'degraded' : 'healthy';
  var pill = document.getElementById('pill');
  pill.textContent = overall;
  pill.className = 'pill ' + overall;
  document.getElementById('uptime').textContent = 'up ' + fmtUp(d.uptime_seconds||0);

  var np = d.now_playing;
  var npEl = document.getElementById('np');
  var barColors = {music:'#7c3aed', movie:'#2563eb', episode:'#0891b2', wallpaper:'#1e3a5f'};
  if (np) {
    npEl.classList.remove('np-idle');
    document.getElementById('np-bar').style.background = barColors[np.media_type] || '#3b5070';
    var title = np.title || '&#x2014;';
    if (np.subtitle) title += ' \xb7 ' + np.subtitle;
    document.getElementById('np-title').textContent = title;
    var parts = [];
    if (np.media_type) parts.push(np.media_type);
    if (np.source)     parts.push('via ' + np.source);
    document.getElementById('np-meta').textContent = parts.join(' \xb7 ');
    var imgs = np.images || [];
    document.getElementById('np-count').textContent =
      imgs.length > 0 ? imgs.length + ' image' + (imgs.length > 1 ? 's' : '') : '';
    document.getElementById('np-imgs').innerHTML = imgs.map(function(lbl){
      return '<span class="img-tag">' + lbl + '</span>';
    }).join('');
  } else {
    npEl.classList.add('np-idle');
    document.getElementById('np-bar').style.background = '#1a2540';
    document.getElementById('np-title').textContent = 'Nothing playing';
    document.getElementById('np-meta').textContent = '';
    document.getElementById('np-count').textContent = '';
    document.getElementById('np-imgs').innerHTML = '';
  }

  document.getElementById('sources').innerHTML = (d.sources||[]).map(function(s){
    return row(s.name, s.status, fmtAgo(s.last_polled_ago_seconds));
  }).join('');

  document.getElementById('outputs').innerHTML = (d.outputs||[]).map(function(o){
    var detail = o.ip || (o.port ? ':'+o.port : '') || o.dir || o.device_ip || '';
    return row(o.type, o.status, detail, o.last_error||null);
  }).join('');

  document.getElementById('enrichers').innerHTML = (d.enrichers||[]).map(function(e){
    return row(e.name, e.status, '');
  }).join('');

  var idleSources = d.idle_sources || [];
  document.getElementById('idle').innerHTML = idleSources.length
    ? idleSources.map(function(src){
        var detail = '';
        if (src.wallpapers_loaded != null) detail = src.wallpapers_loaded + ' wallpapers';
        else if (src.videos_loaded != null) detail = src.videos_loaded + ' videos';
        return row(src.type, src.status, detail);
      }).join('')
    : row('none', 'not_configured', '');

  document.getElementById('footer').textContent =
    'Last updated ' + new Date().toLocaleTimeString() + '  \xb7  auto-refresh every 7s';
}

function load(){
  fetch('/health', {headers: {Accept: 'application/json'}})
    .then(function(r){ return r.json(); })
    .then(render)
    .catch(function(){
      var pill = document.getElementById('pill');
      pill.textContent = 'unreachable';
      pill.className = 'pill degraded';
      document.getElementById('footer').textContent = 'Server unreachable — retrying…';
    });
}

load();
setInterval(load, 7000);
</script>
</body>
</html>
"""
