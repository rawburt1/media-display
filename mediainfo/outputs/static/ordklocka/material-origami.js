(function(){'use strict';
const S=OrdklockaSida,T=OrdklockaTid,slug=window.CLOCK_DESIGN.slug;
const canvas=document.getElementById('fx'),ctx=canvas.getContext('2d');
const phrase=document.getElementById('phrase'),sub=document.getElementById('sub'),dots=document.getElementById('dots');
const reduce=matchMedia('(prefers-reduced-motion: reduce)');let W=0,H=0,dpr=1,words='',changeAt=0,oldWords='',hour=0,particles=[];
function resize(){dpr=Math.min(devicePixelRatio||1,2);W=innerWidth;H=innerHeight;canvas.width=Math.round(W*dpr);canvas.height=Math.round(H*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);onResize();}
function text(t){return T.spokenWords(t).join(' ').toLowerCase();}
const scene=document.getElementById('scene');phrase.style.display='none';
const board=document.createElement('div');board.className='paper-board';scene.insertBefore(board,sub);
const clock=S.clock((t,info)=>{const next=text(t);hour=info.now.getHours();dots.textContent=t.extra?'•'.repeat(t.extra):'';if(next!==words){oldWords=words;words=next;changeAt=performance.now();onWords(next,oldWords);} });
S.choice('style','ordklocka-style','tjugo',v=>clock.setStyle(v));
S.choice('mode','ordklocka-'+slug+'-ljus','dag',v=>{document.documentElement.dataset.mode=v;});
S.setup('/ordklocka/'+slug+'/ws');
addEventListener('resize',resize);document.addEventListener('visibilitychange',()=>{if(!document.hidden)last=0;});let last=0;
function loop(ms){if(!document.hidden&&(ms-last>=(reduce.matches?250:33))){last=ms;ctx.clearRect(0,0,W,H);draw(ms,reduce.matches);}requestAnimationFrame(loop);} 

function onResize(){}
function onWords(next){const tokens=next.split(' ');const old=[...board.children];old.forEach((e,i)=>{e.style.setProperty('--delay',`${i*65}ms`);e.classList.add('fold-away');});
setTimeout(()=>{board.replaceChildren();tokens.forEach((word,i)=>{const tile=document.createElement('span');tile.className='paper-tile';tile.style.setProperty('--delay',`${i*105}ms`);const front=document.createElement('span');front.className='paper-front';front.textContent=word;const crease=document.createElement('span');crease.className='paper-crease';tile.append(front,crease);board.append(tile);requestAnimationFrame(()=>tile.classList.add('unfold'));});},reduce.matches?0:480);}
function draw(ms,reduced){if(reduced)return;const t=ms*.001;ctx.strokeStyle='rgba(115,82,92,.07)';for(let i=0;i<18;i++){ctx.beginPath();ctx.moveTo(0,i*H/17);ctx.lineTo(W,i*H/17+Math.sin(t*.2+i)*2);ctx.stroke();}}
resize();requestAnimationFrame(loop);
})();