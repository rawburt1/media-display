(function(){'use strict';
const cfg=window.CLOCK_DESIGN, S=OrdklockaSida, T=OrdklockaTid;
const stage=document.getElementById('scene'), phrase=document.getElementById('phrase'), canvas=document.getElementById('fx');
const ctx=canvas.getContext('2d',{alpha:true});let W=0,H=0,dpr=1,words='',part='',extra=0,particles=[],last=0;
const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
function resize(){dpr=Math.min(devicePixelRatio||1,2);W=innerWidth;H=innerHeight;canvas.width=Math.round(W*dpr);canvas.height=Math.round(H*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);}
addEventListener('resize',()=>{resize();populate();});resize();
const rand=(a,b)=>a+Math.random()*(b-a);
function populate(){particles=Array.from({length:130},(_,i)=>({x:rand(0,W),y:rand(0,H),vx:rand(-.5,.5),vy:rand(-.5,.5),r:rand(.8,2.6),phase:rand(0,6.28)}));}
populate();
function textStyle(mode){const body=document.body;body.dataset.effect=mode;}
textStyle(cfg.mode);
function render(t,info){const newWords=T.spokenWords(t).join(' ').toLowerCase();extra=t.extra;
 const now=info.now;const dygn=window.OrdklockaDygn?.part(now.getHours());part=dygn?.name||'';
 document.getElementById('sub').textContent=(cfg.mode==='calendar'||cfg.mode==='newspaper')?now.toLocaleDateString('sv-SE',{weekday:'long',day:'numeric',month:'long'}):(['weather','moon','clouds','aurora','organic'].includes(cfg.mode)?part:'');
 document.getElementById('dots').textContent=extra?'•'.repeat(extra):'';
 if(!info.wordsChanged&&words===newWords)return;words=newWords;
 phrase.classList.remove('arrive');phrase.classList.add('depart');
 const delay=reduce?0:340;setTimeout(()=>{phrase.textContent=words;phrase.classList.remove('depart');phrase.classList.add('arrive');
 if(['wordsearch','crossword','binary','ascii','punch','maze'].includes(cfg.mode))buildGrid(words,cfg.mode);
 if(cfg.mode==='world')showWorld(now);
 if(cfg.mode==='dictionary')document.getElementById('sub').textContent='tid · substantiv · '+part;
 },delay);
}
function buildGrid(value,mode){
 const g=document.getElementById('grid');if(!g)return;g.replaceChildren();
 const terms=value.toUpperCase().split(/\s+/).filter(Boolean);
 const chars='ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ';
 const n=Math.max(12,...terms.map(w=>w.length+2));
 const rows=Math.max(12,terms.length*3+2);
 const matrix=Array.from({length:rows},(_,r)=>Array.from({length:n},(_,c)=>chars[(r*19+c*13+7)%chars.length]));
 const lit=new Set();
 if(['wordsearch','crossword','maze'].includes(mode)){
  terms.forEach((word,i)=>{const row=2+i*3,start=Math.floor((n-word.length)/2);
   for(let k=0;k<word.length;k++){matrix[row][start+k]=word[k];lit.add(row*n+start+k);}
  });
 }
 const fragment=document.createDocumentFragment();
 for(let r=0;r<rows;r++)for(let c=0;c<n;c++){
  const e=document.createElement('span'),index=r*n+c;
  if(mode==='binary'){e.textContent=(index%7===0||index%11===0)?'1':'0';if(index%7===0)lit.add(index);}
  else if(mode==='ascii'){e.textContent=index%4===0?'#':index%3===0?'+':'.';if(index%4===0)lit.add(index);}
  else if(mode==='punch'){e.textContent=index%5===0?'●':'·';if(index%5===0)lit.add(index);}
  else e.textContent=matrix[r][c];
  if(lit.has(index))e.className='lit';fragment.append(e);
 }
 g.append(fragment);g.style.gridTemplateColumns=`repeat(${n},minmax(0,1fr))`;
 g.style.gridTemplateRows=`repeat(${rows},minmax(0,1fr))`;
}
function showWorld(now){const sub=document.getElementById('sub');const cities=['Stockholm','London','New York','Tokyo'];sub.textContent=cities.map((c,i)=>c+' '+new Intl.DateTimeFormat('sv-SE',{hour:'2-digit',minute:'2-digit',timeZone:['Europe/Stockholm','Europe/London','America/New_York','Asia/Tokyo'][i]}).format(now)).join(' · ');}
const clock=S.clock(render);
S.choice('style','ordklocka-style','tjugo',v=>clock.setStyle(v));
S.choice('mode','ordklocka-'+cfg.slug+'-ljus','dag',v=>{document.documentElement.dataset.mode=v;});
S.setup('/ordklocka/'+cfg.slug+'/ws');
function draw(ms){if(document.hidden){requestAnimationFrame(draw);return;}const t=ms*.001;ctx.clearRect(0,0,W,H);const mode=cfg.mode;
 if(!reduce){
 if(['particles','dots','organic','aurora','clouds','fractal','voronoi','ripple','wave','contour','kaleido','orbit','spiral','dna','hourglass','pinball','city','maze','crystal','frost','melt','trace','screensaver','optical','holo','hud','moon'].includes(mode)){
 const cx=W/2,cy=H/2;
 if(['aurora','clouds','ripple','wave','contour','fractal','voronoi','kaleido','optical','holo','hud','moon'].includes(mode)){
  for(let j=0;j<9;j++){ctx.beginPath();for(let x=0;x<=W;x+=8){const y=cy+(j-4)*H*.085+Math.sin(x*.008+t*.55+j*.8)*H*.055+Math.cos(x*.014-t*.27+j)*H*.025;if(x===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.strokeStyle=cfg.ink;ctx.globalAlpha=mode==='aurora'?.09:.045;ctx.lineWidth=mode==='aurora'?18:2;ctx.stroke();}ctx.globalAlpha=1;
 }
 if(['particles','dots','organic','aurora','frost','crystal','melt','trace','screensaver','pinball','city','dna','hourglass','orbit','spiral','fractal','kaleido','voronoi'].includes(mode)){
  for(const p of particles){p.x+=p.vx;p.y+=p.vy;if(p.x<0)p.x=W;if(p.x>W)p.x=0;if(p.y<0)p.y=H;if(p.y>H)p.y=0;ctx.beginPath();ctx.arc(p.x,p.y,p.r*(1+.25*Math.sin(t+p.phase)),0,7);ctx.fillStyle=cfg.ink;ctx.globalAlpha=.12+.23*(1+Math.sin(t+p.phase))/2;ctx.fill();}ctx.globalAlpha=1;
 }
 if(['orbit','spiral','hud','dna','hourglass','moon'].includes(mode)){ctx.strokeStyle=cfg.ink;ctx.globalAlpha=.13;ctx.lineWidth=1.4;for(let i=0;i<5;i++){ctx.beginPath();const radius=Math.min(W,H)*(.18+i*.055);ctx.ellipse(cx,cy,radius,radius*(mode==='orbit'?.55:1),t*.06,0,7);ctx.stroke();}ctx.globalAlpha=1;}
 }
 }
 requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
})();