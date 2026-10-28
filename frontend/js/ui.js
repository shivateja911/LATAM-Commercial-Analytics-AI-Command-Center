/* Shared UI helpers: formatting, icons, SVG charts, offline LATAM map. */
/* ---------- utilities ---------- */
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function R(seed){let s=seed%2147483647;if(s<=0)s+=2147483646;return()=>((s=s*16807%2147483647)-1)/2147483646;}
const fmtN=(v,d=0)=>Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtK=v=>{const a=Math.abs(v);if(a>=1e6)return(v/1e6).toFixed(1).replace(/\.0$/,'')+'M';if(a>=1e3)return(v/1e3).toFixed(1).replace(/\.0$/,'')+'k';return String(Math.round(v));};
const sgn=(v,d=1,suf='%')=>(v>0?'+':v<0?'−':'±')+Math.abs(v).toFixed(d)+suf;
const IC={
  grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  tag:'M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8zM7.5 7.5h.01',
  pulse:'M3 12h4l3-8 4 16 3-8h4',
  trend:'M3 17l6-6 4 4 8-8M15 7h6v6',
  box:'M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8',
  route:'M6 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 17V11a4 4 0 0 1 4-4h6M8 19h6a4 4 0 0 0 4-4V9',
  db:'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  sap:'M4 6h16v12H4zM8 10h3M8 14h8',
  sliders:'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
  spark:'M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z',
  send:'M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z',
  sun:'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4'
};
const ico=(n,s=16)=>`<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${IC[n]}"/></svg>`;
$$('[data-ico]').forEach(e=>e.innerHTML=ico(e.dataset.ico,e.closest('.lbl')?12:16));
function series(seed,n,start,drift,vol){const r=R(seed);let v=start;return Array.from({length:n},()=>(v=v*(1+drift+(r()-.5)*vol)));}
function niceTicks(a,b,n){const st0=(b-a)/n,mag=Math.pow(10,Math.floor(Math.log10(st0))),f=st0/mag,st=(f<1.5?1:f<3?2:f<7?5:10)*mag,t=[];for(let v=Math.ceil(a/st)*st;v<=b+1e-9;v+=st)t.push(+v.toFixed(8));return t;}
function spark(data,color,w=96,h=30){const mn=Math.min(...data),mx=Math.max(...data);const X=i=>i/(data.length-1)*w,Y=v=>h-2-(v-mn)/((mx-mn)||1)*(h-5);const d=data.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1)).join('');return `<svg width="${w}" height="${h}"><path d="${d}L${w},${h}L0,${h}Z" style="fill:${color};opacity:.13"/><path d="${d}" style="fill:none;stroke:${color};stroke-width:1.6"/></svg>`;}
function toast(msg,kind='ai'){const t=document.createElement('div');t.className='toast';t.innerHTML=`<span class="dot ${kind}"></span>${msg}`;$('#toasts').appendChild(t);setTimeout(()=>t.remove(),4200);}
document.addEventListener('click',e=>{const b=e.target.closest('[data-toast]');if(b)toast(b.dataset.toast,'');});

/* ---------- line chart ---------- */
function lineChart(el,o){
  const w=el.clientWidth||600,h=o.h||240,p={l:o.padL||44,r:14,t:o.padT||20,b:24},n=o.x.length;
  const vals=[];o.series.forEach(s=>s.data.forEach(v=>v!=null&&vals.push(v)));if(o.band){o.band.lo.forEach(v=>v!=null&&vals.push(v));o.band.hi.forEach(v=>v!=null&&vals.push(v));}
  if(o.extra)vals.push(...o.extra);
  let y0=o.yMin!=null?o.yMin:Math.min(...vals),y1=Math.max(...vals);const pad=(y1-y0)*.08;if(o.yMin==null)y0-=pad;y1+=pad;
  const X=i=>p.l+(i/(n-1))*(w-p.l-p.r),Y=v=>p.t+(1-(v-y0)/(y1-y0))*(h-p.t-p.b);
  let g='';
  niceTicks(y0,y1,4).forEach(t=>{g+=`<line x1="${p.l}" x2="${w-p.r}" y1="${Y(t)}" y2="${Y(t)}" class="gl"/><text x="${p.l-6}" y="${Y(t)+3}" class="ax" text-anchor="end">${(o.fmt||fmtK)(t)}</text>`;});
  const ev=o.xEvery||Math.ceil(n/8);o.x.forEach((lb,i)=>{if(i%ev===0)g+=`<text x="${X(i)}" y="${h-6}" class="ax" text-anchor="middle">${lb}</text>`;});
  if(o.zero)g+=`<line x1="${p.l}" x2="${w-p.r}" y1="${Y(0)}" y2="${Y(0)}" style="stroke:var(--tx3)"/>`;
  if(o.split!=null)g+=`<rect x="${X(o.split)}" y="${p.t}" width="${w-p.r-X(o.split)}" height="${h-p.t-p.b}" class="fcr"/><line x1="${X(o.split)}" x2="${X(o.split)}" y1="${p.t-8}" y2="${h-p.b}" class="today"/><text x="${X(o.split)+5}" y="${p.t-9}" class="tt">Today · forecast →</text>`;
  (o.ann||[]).forEach((a,k)=>{g+=`<line x1="${X(a.i)}" x2="${X(a.i)}" y1="${p.t+(k%2?12:2)}" y2="${h-p.b}" class="ann"/><text x="${X(a.i)}" y="${p.t+(k%2?20:10)}" class="annt" text-anchor="middle">${a.label}</text>`;});
  if(o.hline)o.hline.forEach(hl=>{g+=`<line x1="${p.l}" x2="${w-p.r}" y1="${Y(hl.v)}" y2="${Y(hl.v)}" style="stroke:${hl.color};stroke-dasharray:5 4;stroke-width:1.3"/><text x="${w-p.r}" y="${Y(hl.v)-5}" class="ax" text-anchor="end" style="fill:${hl.color}">${hl.label}</text>`;});
  if(o.band){const idx=[...Array(n).keys()].filter(i=>o.band.lo[i]!=null);if(idx.length){const up=idx.map((i,k)=>(k?'L':'M')+X(i).toFixed(1)+','+Y(o.band.hi[i]).toFixed(1)).join('');const dn=idx.slice().reverse().map(i=>'L'+X(i).toFixed(1)+','+Y(o.band.lo[i]).toFixed(1)).join('');g+=`<path d="${up}${dn}Z" style="fill:${o.band.color};opacity:.16"/>`;}}
  o.series.forEach(s=>{let d='',pen=false,first=null,last=null;s.data.forEach((v,i)=>{if(v==null){pen=false;return;}if(first==null)first=i;last=i;d+=(pen?'L':'M')+X(i).toFixed(1)+','+Y(v).toFixed(1);pen=true;});
    if(s.area&&first!=null)g+=`<path d="${d}L${X(last)},${Y(y0)}L${X(first)},${Y(y0)}Z" style="fill:${s.color};opacity:.12"/>`;
    g+=`<path d="${d}" style="fill:none;stroke:${s.color};stroke-width:${s.w||2};${s.dash?'stroke-dasharray:'+s.dash:''}" stroke-linejoin="round" stroke-linecap="round"/>`;
    (s.markers||[]).forEach(m=>{g+=`<circle cx="${X(m.i)}" cy="${Y(s.data[m.i])}" r="${m.r||5}" style="fill:${m.fill||s.color};stroke:var(--panel);stroke-width:2"/>${m.label?`<text x="${X(m.i)}" y="${Y(s.data[m.i])-11}" class="mkt" text-anchor="middle">${m.label}</text>`:''}`;});});
  el.innerHTML=`<svg width="${w}" height="${h}" class="chart">${g}<line class="xh" y1="${p.t}" y2="${h-p.b}" style="display:none"/></svg><div class="tip" style="display:none"></div>`;
  const svg=el.querySelector('svg'),xh=svg.querySelector('.xh'),tip=el.querySelector('.tip');
  svg.addEventListener('mousemove',ev=>{const bx=svg.getBoundingClientRect(),mx=ev.clientX-bx.left;let i=Math.round((mx-p.l)/(w-p.l-p.r)*(n-1));i=Math.max(0,Math.min(n-1,i));
    const rows=o.series.filter(s=>s.data[i]!=null&&!s.noTip).map(s=>`<div class="tr"><span><i class="sw" style="background:${s.color}"></i> ${s.name}</span><b>${(o.tfmt||(v=>fmtN(v)))(s.data[i])}</b></div>`).join('');
    if(!rows){tip.style.display='none';xh.style.display='none';return;}
    xh.setAttribute('x1',X(i));xh.setAttribute('x2',X(i));xh.style.display='';
    tip.innerHTML=`<div class="mut" style="margin-bottom:3px">${o.x[i]}</div>${rows}`;tip.style.display='';
    const tx=X(i)+12+tip.offsetWidth>w?X(i)-tip.offsetWidth-12:X(i)+12;tip.style.left=tx+'px';tip.style.top='6px';});
  svg.addEventListener('mouseleave',()=>{tip.style.display='none';xh.style.display='none';});
}

/* ---------- map ---------- */
const LAND=[[32.53,-117.12],[31.86,-116.6],[30.5,-115.95],[27.85,-115.08],[24.6,-112.1],[22.88,-109.91],[24.15,-110.3],[26,-111.35],[27.34,-112.27],[28.95,-113.55],[31.02,-114.84],[31.8,-114.8],[31.3,-113.55],[28.8,-111.95],[27.92,-110.9],[26.8,-109.6],[25.6,-109.05],[24.6,-107.7],[23.2,-106.42],[21.54,-105.29],[20.6,-105.24],[20.4,-105.7],[19.05,-104.32],[17.95,-102.2],[17.64,-101.55],[16.85,-99.88],[16.3,-98.2],[15.86,-97.07],[15.75,-96.13],[16.17,-95.2],[16.2,-94.4],[16,-93.9],[14.7,-92.4],[13.92,-90.82],[13.57,-89.83],[13.48,-89.32],[13.2,-87.8],[12.48,-87.17],[11.25,-85.87],[9.56,-85.1],[9.97,-84.83],[9.43,-84.16],[8.4,-83.3],[8.03,-82.88],[7.47,-80],[8.95,-79.53],[8.4,-78.4],[7.5,-78.17],[6.22,-77.4],[5.5,-77.55],[3.88,-77.07],[1.8,-78.78],[0.97,-79.65],[-0.37,-80.5],[-0.95,-80.73],[-2.2,-80.98],[-2.6,-80],[-3.4,-80.3],[-4.1,-81.05],[-4.68,-81.33],[-5.08,-81.11],[-5.8,-81],[-6.8,-79.95],[-7.4,-79.57],[-8.1,-79.05],[-9.08,-78.6],[-10.07,-78.16],[-11.1,-77.62],[-12.05,-77.15],[-12.5,-76.75],[-13,-76.48],[-13.71,-76.22],[-13.9,-76.3],[-15.35,-75.17],[-15.85,-74.25],[-16.62,-72.71],[-17.02,-72.02],[-17.64,-71.34],[-18.48,-70.32],[-20.21,-70.15],[-22.09,-70.2],[-23.1,-70.45],[-23.65,-70.4],[-25.4,-70.48],[-26.35,-70.62],[-27.07,-70.83],[-28.47,-71.22],[-29.9,-71.33],[-31.9,-71.5],[-33.03,-71.63],[-33.6,-71.62],[-35.33,-72.42],[-36.8,-73.1],[-37.6,-73.65],[-39.8,-73.4],[-41.5,-73.8],[-42.5,-74.2],[-43.5,-74.3],[-45,-74.8],[-46.6,-75.6],[-48,-75.5],[-50,-75.3],[-51.6,-74.9],[-52.8,-74.3],[-53.9,-72.5],[-54.6,-71],[-55.2,-69.5],[-55,-67.5],[-54.65,-65.2],[-53.79,-67.7],[-52.65,-68.6],[-51.62,-69.2],[-50,-68.5],[-49.3,-67.7],[-47.75,-65.9],[-46.44,-67.52],[-45.86,-67.48],[-44.8,-65.7],[-44,-65.2],[-43.3,-65.05],[-42.5,-63.6],[-42.05,-63.75],[-40.73,-64.95],[-40.55,-62.25],[-38.95,-62],[-38.98,-61.3],[-38.57,-58.7],[-38,-57.53],[-36.3,-56.75],[-35.7,-57.3],[-34.6,-58.37],[-34.47,-57.85],[-34.9,-56.2],[-34.97,-54.95],[-34.66,-54.16],[-33.7,-53.4],[-32.05,-52.08],[-30,-50.13],[-29.33,-49.73],[-28.48,-48.78],[-27.6,-48.45],[-26.9,-48.65],[-25.52,-48.5],[-24.7,-47.5],[-23.97,-46.3],[-23.43,-45.07],[-23,-44.3],[-22.97,-43.17],[-22.88,-42.02],[-22.37,-41.78],[-22,-40.98],[-20.32,-40.29],[-19.4,-39.7],[-17.7,-39.25],[-16.45,-39.06],[-14.79,-39.03],[-13,-38.5],[-10.9,-37.05],[-9.67,-35.72],[-8.05,-34.88],[-7.12,-34.83],[-5.79,-35.2],[-5.48,-35.26],[-4.95,-37.13],[-3.72,-38.52],[-2.9,-40.84],[-2.9,-41.75],[-2.53,-44.3],[-1.65,-45.4],[-0.6,-47.35],[-0.2,-48.5],[0,-50],[0.03,-51.05],[1.7,-49.9],[4.2,-51.6],[4.93,-52.33],[5.87,-55.17],[5.95,-56.98],[6.8,-58.15],[8.6,-60.5],[10.1,-61.9],[10.72,-62.5],[10.46,-64.17],[10.13,-64.7],[10.48,-66.1],[10.6,-66.93],[10.47,-68],[10.8,-68.32],[11.4,-69.67],[12.18,-70],[11,-71.6],[12.45,-71.67],[11.54,-72.9],[11.24,-74.21],[11.02,-74.85],[10.4,-75.53],[9.5,-75.7],[8.1,-76.73],[8.42,-76.78],[8.68,-77.36],[9.4,-78.5],[9.36,-79.9],[9.34,-82.24],[9.99,-83.03],[10.93,-83.7],[12,-83.76],[14.03,-83.38],[15,-83.15],[15.92,-85.95],[15.78,-86.8],[15.85,-87.95],[15.73,-88.6],[16.1,-88.8],[16.97,-88.22],[17.5,-88.2],[18.27,-87.83],[20.21,-87.46],[20.63,-87.07],[21.16,-86.82],[21.6,-87.07],[21.52,-87.68],[21.28,-89.66],[20.86,-90.4],[19.85,-90.53],[19.35,-90.72],[18.64,-91.83],[18.55,-92.65],[18.15,-94.42],[18.77,-95.76],[19.2,-96.13],[20.2,-96.77],[20.96,-97.4],[22.25,-97.85],[23.78,-97.75],[25.87,-97.15],[26.08,-98.3],[27.5,-99.5],[28.7,-100.52],[29.32,-100.93],[29.18,-102.95],[29.56,-104.42],[31.74,-106.48],[31.78,-107.63],[31.33,-108.2],[31.33,-110.94],[31.86,-112.85],[32.47,-114.77],[32.66,-115.47]];
function mapSVG(el,cfg){
  const w=el.clientWidth||460,[lo0,lo1,la0,la1]=cfg.view,h=Math.round(w*(la1-la0)/(lo1-lo0));
  const P=(lat,lon)=>[(lon-lo0)/(lo1-lo0)*w,(la1-lat)/(la1-la0)*h];
  const land=LAND.map((q,i)=>{const[x,y]=P(q[0],q[1]);return(i?'L':'M')+x.toFixed(1)+','+y.toFixed(1);}).join('')+'Z';
  const id='p'+Math.random().toString(36).slice(2,8);
  let g=`<defs><pattern id="${id}" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="3" cy="3" r="1" class="mdot"/></pattern></defs><path d="${land}" class="land"/><path d="${land}" style="fill:url(#${id})"/>`;
  (cfg.under||[]).forEach(f=>g+=f(P));
  (cfg.labels||[]).forEach(l=>{const[x,y]=P(l.lat,l.lon);g+=`<text x="${x}" y="${y}" class="cl" text-anchor="middle" style="${l.st||''}">${l.t}</text>`;});
  (cfg.bubbles||[]).forEach(b=>{const[x,y]=P(b.lat,b.lon);g+=`<circle cx="${x}" cy="${y}" r="${b.r}" class="bub" style="fill:${b.c};fill-opacity:.16;stroke:${b.c};stroke-opacity:.6"><title>${b.tip}</title></circle><text x="${x}" y="${y+b.r+11}" class="nl" text-anchor="middle">${b.t}</text>`;});
  (cfg.lanes||[]).forEach(l=>{const[a,b]=[P(...l.a),P(...l.b)];const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2,dx=b[0]-a[0],dy=b[1]-a[1],k=l.k||.18;g+=`<path d="M${a[0]},${a[1]}Q${mx-dy*k},${my+dx*k} ${b[0]},${b[1]}" class="lane ${l.sea?'sea':''} ${l.flow?'flow':''}"/>`;});
  (cfg.paths||[]).forEach(r=>{const d=r.pts.map((q,i)=>{const[x,y]=P(q[0],q[1]);return(i?'L':'M')+x.toFixed(1)+','+y.toFixed(1);}).join('');g+=`<path d="${d}" style="fill:none;stroke:${r.c};stroke-width:${r.w||2.4};${r.dash?'stroke-dasharray:'+r.dash:''};stroke-linejoin:round;stroke-linecap:round" class="${r.flow?'flow':''}"/>`;});
  (cfg.nodes||[]).forEach(nd=>{const[x,y]=P(nd.lat,nd.lon);
    if(nd.alert)g+=`<circle cx="${x}" cy="${y}" r="6" class="pulse" style="fill:var(--neg)"/>`;
    if(nd.t==='plant')g+=`<rect x="${x-5}" y="${y-5}" width="10" height="10" rx="2" style="fill:var(--gold);stroke:var(--panel);stroke-width:1.5"><title>${nd.n}</title></rect>`;
    else if(nd.t==='x')g+=`<g style="stroke:var(--neg);stroke-width:3;stroke-linecap:round"><path d="M${x-6},${y-6}L${x+6},${y+6}M${x+6},${y-6}L${x-6},${y+6}"/></g>`;
    else g+=`<circle cx="${x}" cy="${y}" r="${nd.r||3.6}" style="fill:${nd.c||(nd.alert?'var(--neg)':'var(--tx2)')};stroke:var(--panel);stroke-width:1.5"><title>${nd.n||nd.id}</title></circle>`;
    if(nd.lbl)g+=`<text x="${x+(nd.dx||8)}" y="${y+(nd.dy||3)}" class="nl" text-anchor="${nd.anc||'start'}">${nd.lbl}</text>`;});
  el.innerHTML=`<svg width="${w}" height="${h}" class="map">${g}</svg>`;
}

function stackArea(el,x,S){const w=el.clientWidth||500,h=190,p={l:34,r:10,t:8,b:22},n=x.length,X=i=>p.l+i/(n-1)*(w-p.l-p.r),Y=v=>p.t+(1-v/100)*(h-p.t-p.b);let base=Array(n).fill(0),g='';
  [0,25,50,75,100].forEach(t=>g+=`<line x1="${p.l}" x2="${w-p.r}" y1="${Y(t)}" y2="${Y(t)}" class="gl"/><text x="${p.l-6}" y="${Y(t)+3}" class="ax" text-anchor="end">${t}%</text>`);
  S.forEach(s=>{const top=s[2].map((v,i)=>base[i]+v);const d=top.map((v,i)=>(i?'L':'M')+X(i)+','+Y(v)).join('')+base.map((v,i)=>[i,v]).reverse().map(([i,v])=>'L'+X(i)+','+Y(v)).join('')+'Z';g+=`<path d="${d}" style="fill:${s[1]};opacity:.75"/>`;base=top;});
  x.forEach((l,i)=>g+=`<text x="${X(i)}" y="${h-6}" class="ax" text-anchor="middle">${l}</text>`);el.innerHTML=`<svg width="${w}" height="${h}" class="chart">${g}</svg>`;}
