(()=>{'use strict';
const C=document.getElementById('art'),x=C.getContext('2d'),phrase=document.getElementById('phrase'),sub=document.getElementById('sub'),dots=document.getElementById('dots');
const SLUG='kristall';const T=OrdklockaTid,S=OrdklockaSida,reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
let W=0,H=0,D=1,words='',change=0,mode='dag',pts=[],prev=0;const TAU=Math.PI*2;
function resize(){W=innerWidth;H=innerHeight;D=Math.min(devicePixelRatio||1,2);C.width=Math.round(W*D);C.height=Math.round(H*D);x.setTransform(D,0,0,D,0,0);onResize();}
function textPoints(str,step=5){const o=document.createElement('canvas');o.width=Math.max(1,Math.floor(W/2));o.height=Math.max(1,Math.floor(H/2));const c=o.getContext('2d',{willReadFrequently:true});c.font=`700 ${Math.min(o.width/Math.max(str.length*.54,6),o.height*.32,80)}px system-ui`;c.textAlign='center';c.textBaseline='middle';c.fillStyle='white';c.fillText(str.toUpperCase(),o.width/2,o.height/2,o.width*.9);const a=c.getImageData(0,0,o.width,o.height).data,r=[];for(let j=0;j<o.height;j+=step)for(let i=0;i<o.width;i+=step)if(a[(j*o.width+i)*4+3]>130)r.push({x:i*2,y:j*2});return r;}
function update(t,info){const next=T.spokenWords(t).join(' ').toLowerCase();dots.textContent=t.extra?'•'.repeat(t.extra):'';const part=window.OrdklockaDygn?.part(info.now.getHours());sub.textContent=(part?.phrase||'')+' · '+info.now.toLocaleDateString('sv-SE',{day:'numeric',month:'long'});if(next!==words){const old=words;words=next;change=performance.now();onWords(old,next,info.first);} }

function wordMask(){const m=document.createElement('canvas');m.width=C.width;m.height=C.height;const g=m.getContext('2d');g.scale(D,D);const size=Math.min(H*.20,W/Math.max(7,words.length*.67),125);g.font=`800 ${Math.max(20,size)}px system-ui`;g.textAlign='center';g.textBaseline='middle';g.fillStyle='white';g.fillText(words.toUpperCase(),W/2,H*.49,W*.91);return m;}
let mask=null,oldMask=null;
function rebuildMask(){oldMask=mask;mask=wordMask();}
function applyMasked(drawLayer,progress){if(!mask)return;const layer=document.createElement('canvas');layer.width=C.width;layer.height=C.height;const g=layer.getContext('2d');g.setTransform(D,0,0,D,0,0);drawLayer(g);g.setTransform(1,0,0,1,0,0);g.globalCompositeOperation='destination-in';g.drawImage(mask,0,0);x.save();x.globalAlpha=progress;x.drawImage(layer,0,0,W,H);x.restore();}
let facets=[];
function onResize(){facets=Array.from({length:280},(_,i)=>({x:(i*73.67)%Math.max(1,W),y:(i*113.39)%Math.max(1,H),a:i*2.4,r:10+i%8*7,h:175+i*13%110}));if(words)rebuildMask();}
function onWords(){phrase.textContent='';rebuildMask();}
function draw(t,q){x.fillStyle=mode==='natt'?'#010a14':'#061a29';x.fillRect(0,0,W,H);
applyMasked(g=>{const grad=g.createLinearGradient(0,H*.25,W,H*.75);grad.addColorStop(0,'#b8faff');grad.addColorStop(.5,'#226eac');grad.addColorStop(1,'#e7c3ff');g.fillStyle=grad;g.fillRect(0,0,W,H);for(const f of facets){const a=f.a+Math.sin(t*.4+f.a)*.35,z=f.r;g.beginPath();g.moveTo(f.x+Math.cos(a)*z,f.y+Math.sin(a)*z);g.lineTo(f.x+Math.cos(a+2.1)*z,f.y+Math.sin(a+2.1)*z);g.lineTo(f.x+Math.cos(a+4.2)*z,f.y+Math.sin(a+4.2)*z);g.closePath();g.fillStyle=`hsla(${f.h},90%,${50+20*Math.sin(t+f.a)}%,.48)`;g.fill();g.strokeStyle='rgba(225,255,255,.32)';g.lineWidth=1.3;g.stroke();}},Math.max(.05,q));
}
const clock=S.clock(update);S.choice('style','ordklocka-style','tjugo',v=>clock.setStyle(v));S.choice('mode','ordklocka-'+SLUG+'-ljus','dag',v=>{mode=v;document.documentElement.dataset.mode=v;});S.setup('/ordklocka/'+SLUG+'/ws');
function frame(ms){requestAnimationFrame(frame);if(document.hidden)return;const t=reduce?0:ms/1000; x.clearRect(0,0,W,H);draw(t,Math.min(1,(ms-change)/1800));}
addEventListener('resize',resize);resize();requestAnimationFrame(frame);
})();