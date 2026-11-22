/* Shared lifecycle only; each visual clock owns its rendering and transitions. */
(function(){'use strict';
const kind=document.body.dataset.kind, canvas=document.getElementById('scene'),ctx=canvas.getContext('2d');
const phrase=document.getElementById('timewords'),detail=document.getElementById('detail'),minutes=document.getElementById('minutes');
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
let w=0,h=0,dpr=1,words='',oldWords='',changed=0,mode='dag',current=null;
function resize(){w=innerWidth;h=innerHeight;dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);if(window.visualResize)window.visualResize(w,h);}
addEventListener('resize',resize);resize();
const api={ctx,canvas,reduced,get w(){return w},get h(){return h},get words(){return words},get oldWords(){return oldWords},get age(){return performance.now()-changed},get mode(){return mode},get current(){return current}};
const visual=window.createVisual(api);
const clock=OrdklockaSida.clock((t,info)=>{current=t;const next=OrdklockaTid.spokenWords(t).join(' ').toLowerCase();if(next!==words){oldWords=words;words=next;changed=performance.now();visual.change?.(next,oldWords);}
phrase.textContent=words;minutes.textContent=t.extra?'•'.repeat(t.extra):'';const part=OrdklockaDygn.part(info.now.getHours());detail.textContent=part.phrase+' · '+info.now.toLocaleDateString('sv-SE',{weekday:'long',day:'numeric',month:'long'});});
OrdklockaSida.choice('style','ordklocka-style','tjugo',v=>clock.setStyle(v));
OrdklockaSida.choice('mode','ordklocka-'+kind+'-ljus','dag',v=>{mode=v;document.documentElement.dataset.mode=v;visual.mode?.(v);});
OrdklockaSida.setup('/ordklocka/'+kind+'/ws');
function frame(ms){if(!document.hidden)visual.draw(ms);requestAnimationFrame(frame)}requestAnimationFrame(frame);
})();