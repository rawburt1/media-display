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

function RENDER(c,t,p,still){c.fillStyle='#f1e9da';c.fillRect(0,0,W,H);for(let i=0;i<90;i++){c.fillStyle=i%2?'#9e8c7810':'#ffffff26';c.fillRect((i*79)%W,(i*149)%H,70,2);}
oc.clearRect(0,0,W,H);const colors=['#3f728d','#a16e91','#d28a68','#5b8c81','#846eac'];
const n=Math.floor(points.length*p);for(let i=0;i<n;i+=2){const q=points[i],radius=4+q.size*4;oc.globalAlpha=.13;oc.fillStyle=colors[i%colors.length];oc.beginPath();oc.ellipse(q.x,q.y,radius*1.7,radius, q.angle,0,7);oc.fill();oc.globalAlpha=.23;oc.beginPath();oc.arc(q.x,q.y,radius*.55,0,7);oc.fill();}oc.globalAlpha=1;oc.globalCompositeOperation='destination-in';oc.drawImage(mask,0,0);oc.globalCompositeOperation='source-over';c.drawImage(off,0,0);
c.save();c.globalAlpha=.2*p;c.drawImage(mask,0,0);c.restore();if(!still){c.strokeStyle='#9d7e9a33';for(let i=0;i<12;i++){let x=(i*113)%W,y=(i*173)%H;c.beginPath();c.arc(x,y,3+Math.sin(t+i)*1,0,7);c.stroke();}}}
})();
