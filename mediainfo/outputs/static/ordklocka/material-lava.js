(function(){'use strict';
const S=OrdklockaSida,T=OrdklockaTid,slug=window.CLOCK_DESIGN.slug;
const canvas=document.getElementById('fx'),ctx=canvas.getContext('2d');
const phrase=document.getElementById('phrase'),sub=document.getElementById('sub'),dots=document.getElementById('dots');
const reduce=matchMedia('(prefers-reduced-motion: reduce)');let W=0,H=0,dpr=1,words='',changeAt=0,oldWords='',hour=0,particles=[];
function resize(){dpr=Math.min(devicePixelRatio||1,2);W=innerWidth;H=innerHeight;canvas.width=Math.round(W*dpr);canvas.height=Math.round(H*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);onResize();}
function text(t){return T.spokenWords(t).join(' ').toLowerCase();}
let mask=document.createElement('canvas'),mc=mask.getContext('2d'),seeds=[],layer=document.createElement('canvas'),lc=layer.getContext('2d');
const clock=S.clock((t,info)=>{const next=text(t);hour=info.now.getHours();dots.textContent=t.extra?'•'.repeat(t.extra):'';if(next!==words){oldWords=words;words=next;changeAt=performance.now();onWords(next,oldWords);} });
S.choice('style','ordklocka-style','tjugo',v=>clock.setStyle(v));
S.choice('mode','ordklocka-'+slug+'-ljus','dag',v=>{document.documentElement.dataset.mode=v;});
S.setup('/ordklocka/'+slug+'/ws');
addEventListener('resize',resize);document.addEventListener('visibilitychange',()=>{if(!document.hidden)last=0;});let last=0;
function loop(ms){if(!document.hidden&&(ms-last>=(reduce.matches?250:33))){last=ms;ctx.clearRect(0,0,W,H);draw(ms,reduce.matches);}requestAnimationFrame(loop);} 

phrase.style.display='none';
function onResize(){rebuild();}function onWords(){rebuild();seeds=Array.from({length:45},()=>({x:Math.random()*W,y:H*.55+Math.random()*H*.4,v:1+Math.random()*2}));}
function rebuild(){if(!W||!H)return;mask.width=Math.round(W);mask.height=Math.round(H);mc.clearRect(0,0,W,H);const font=Math.max(22,Math.min(W/Math.max(9,words.length*.55),H*.16,96));mc.textAlign='center';mc.textBaseline='middle';mc.font=`900 ${font}px system-ui`;const tokens=words.split(' '),lines=[];let line='';for(const token of tokens){if(mc.measureText((line+' '+token).trim()).width>W*.82&&line){lines.push(line);line=token;}else line=(line+' '+token).trim();}if(line)lines.push(line);lines.forEach((l,i)=>mc.fillText(l,W/2,H/2+(i-(lines.length-1)/2)*font*1.2));}
function draw(ms,reduced){if(!words)return;const t=ms*.001,elapsed=Math.min(1,(ms-changeAt)/1600);ctx.fillStyle='#130806';ctx.fillRect(0,0,W,H);
const lw=Math.max(1,Math.floor(W*dpr)),lh=Math.max(1,Math.floor(H*dpr));if(layer.width!==lw||layer.height!==lh){layer.width=lw;layer.height=lh;}const c=lc;c.setTransform(dpr,0,0,dpr,0,0);c.globalCompositeOperation='source-over';c.clearRect(0,0,W,H);
const gradient=c.createLinearGradient(0,H*.25,0,H*.78);gradient.addColorStop(0,'#ffe69b');gradient.addColorStop(.4,'#ff8d22');gradient.addColorStop(.8,'#e42e0a');gradient.addColorStop(1,'#631007');c.fillStyle=gradient;c.fillRect(0,0,W,H);
if(!reduced){for(let i=0;i<24;i++){const y=H*(.3+i*.018),shift=Math.sin(t*1.6+i*.8)*16;c.fillStyle=`rgba(255,${65+i*4},0,.22)`;c.fillRect(shift,y,W,3);}}
c.globalCompositeOperation='destination-in';c.drawImage(mask,0,0);c.globalCompositeOperation='source-over';ctx.save();ctx.shadowColor='#ff4a09';ctx.shadowBlur=28;ctx.globalAlpha=elapsed;ctx.drawImage(layer,0,0,W,H);ctx.restore();
if(!reduced){ctx.save();ctx.globalAlpha=.35;for(const p of seeds){p.y-=p.v;p.x+=Math.sin(t+p.y*.02)*.35;if(p.y<0)p.y=H;ctx.fillStyle='#ff9d29';ctx.fillRect(p.x,p.y,2,3);}ctx.restore();}}
resize();requestAnimationFrame(loop);
})();