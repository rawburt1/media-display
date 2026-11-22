(function(){'use strict';
const S=OrdklockaSida,T=OrdklockaTid,slug=window.CLOCK_DESIGN.slug;
const canvas=document.getElementById('fx'),ctx=canvas.getContext('2d',{alpha:false});
const phrase=document.getElementById('phrase'),sub=document.getElementById('sub'),dots=document.getElementById('dots');
phrase.hidden=true;sub.hidden=true;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let W=0,H=0,dpr=1,words='',previous='',started=0,points=[],mask=document.createElement('canvas'),mc=mask.getContext('2d',{willReadFrequently:true}),off=document.createElement('canvas'),oc=off.getContext('2d');
const rnd=(a,b)=>a+Math.random()*(b-a),clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function resize(){W=innerWidth;H=innerHeight;dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(W*dpr);canvas.height=Math.round(H*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);mask.width=W;mask.height=H;off.width=W;off.height=H;build();}
function build(){if(!W||!H||!words)return;mc.clearRect(0,0,W,H);let size=Math.min(100,W*.12,H*.18);const parts=words.split(' ');let lines=[];
for(;size>18;size-=2){mc.font=`700 ${size}px Georgia,serif`;lines=[];let line='';for(const part of parts){const trial=(line+' '+part).trim();if(mc.measureText(trial).width>W*.83&&line){lines.push(line);line=part;}else line=trial;}if(line)lines.push(line);if(lines.length*size*1.35<H*.49&&lines.every(l=>mc.measureText(l).width<W*.9))break;}
mc.textAlign='center';mc.textBaseline='middle';mc.font=`700 ${size}px Georgia,serif`;lines.forEach((line,i)=>mc.fillText(line,W/2,H/2+(i-(lines.length-1)/2)*size*1.24));
const data=mc.getImageData(0,0,W,H).data;points=[];const step=slug==='glasmosaik'?12:slug==='mossa'?8:7;
for(let y=0;y<H;y+=step)for(let x=0;x<W;x+=step){if(data[(Math.floor(y)*W+Math.floor(x))*4+3]>80)points.push({x:x+rnd(-step*.25,step*.25),y:y+rnd(-step*.25,step*.25),delay:rnd(0,1),angle:rnd(0,Math.PI*2),size:rnd(.7,1.3)});}
}
const clock=S.clock((t,info)=>{const next=T.spokenWords(t).join(' ').toLowerCase();dots.textContent=t.extra?'•'.repeat(t.extra):'';if(next!==words){previous=words;words=next;started=performance.now();build();}});
S.choice('style','ordklocka-style','tjugo',v=>clock.setStyle(v));
S.choice('mode','ordklocka-'+slug+'-ljus','dag',v=>{document.documentElement.dataset.mode=v;});
S.setup('/ordklocka/'+slug+'/ws');
addEventListener('resize',resize);
let last=0;function frame(now){requestAnimationFrame(frame);if(document.hidden||now-last<(reduced.matches?150:33))return;last=now;if(!words)return;draw(now,(now-started)/1000,reduced.matches);}
function draw(now,elapsed,still){ctx.clearRect(0,0,W,H);const progress=still?1:clamp(elapsed/2.3,0,1);RENDER(ctx,now*.001,progress,still);}
resize();requestAnimationFrame(frame);

function RENDER(c,t,p,still){let g=c.createLinearGradient(0,0,W,H);g.addColorStop(0,'#0a1d31');g.addColorStop(1,'#31516b');c.fillStyle=g;c.fillRect(0,0,W,H);
c.strokeStyle='rgba(210,237,255,.055)';for(let i=0;i<70;i++){let x=(i*131)%W,y=(i*73)%H;c.beginPath();c.moveTo(x,y);c.lineTo(x+23,y-21);c.stroke();}
const count=Math.floor(points.length*p);c.save();c.shadowColor='#c3edff';c.shadowBlur=still?3:9;
for(let i=0;i<count;i++){const q=points[i],r=1.6*q.size,angle=q.angle;c.strokeStyle=`rgba(219,245,255,${.42+.45*p})`;c.lineWidth=.7;c.beginPath();c.moveTo(q.x-r*1.8,q.y);c.lineTo(q.x+r*1.8,q.y);c.moveTo(q.x,q.y-r*1.8);c.lineTo(q.x,q.y+r*1.8);c.stroke();if(i%4===0){c.beginPath();for(let a=0;a<6;a++){let th=a*Math.PI/3+angle;c.moveTo(q.x,q.y);c.lineTo(q.x+Math.cos(th)*r*2.5,q.y+Math.sin(th)*r*2.5);}c.stroke();}}
c.restore();c.globalAlpha=.08;c.drawImage(mask,0,0);c.globalAlpha=1;
if(!still){for(let i=0;i<28;i++){let x=(i*211+t*3)%W,y=(i*91)%H;c.fillStyle='#e4f8ff';c.fillRect(x,y,1,1);}}}
})();
