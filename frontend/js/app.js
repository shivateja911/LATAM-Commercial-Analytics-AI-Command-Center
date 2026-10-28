/* CABI single-page app: data-driven screens over the local API. */
const S = { cur: 'overview', version: -1, lang: 'en', data: {}, pulse: [], meta: null, demoTimer: null };
const API = {
  async get(p) { const r = await fetch('/api/' + p); if (!r.ok) throw new Error(await r.text()); return r.json(); },
  async post(p, body = {}) { const r = await fetch('/api/' + p, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }); if (!r.ok) throw new Error(await r.text()); return r.json(); },
};
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function md(text) {
  const lines = esc(text).split(/\n+/); let html = '', list = null;
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (let l of lines) {
    l = l.trim(); if (!l) continue;
    const b = l.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); let m;
    if ((m = b.match(/^[-•*]\s+(.*)/))) { if (list !== 'ul') { close(); html += '<ul>'; list = 'ul'; } html += `<li>${m[1]}</li>`; }
    else if ((m = b.match(/^\d+[.)]\s+(.*)/))) { if (list !== 'ol') { close(); html += '<ol>'; list = 'ol'; } html += `<li>${m[1]}</li>`; }
    else { close(); html += `<p>${b}</p>`; }
  }
  close(); return html;
}
const F = {
  usdM: v => '$' + (v / 1e6).toFixed(1) + 'M',
  usd: v => (v < 0 ? '−' : '') + (Math.abs(v) >= 1e6 ? '$' + (Math.abs(v) / 1e6).toFixed(1) + 'M' : Math.abs(v) >= 1e3 ? '$' + (Math.abs(v) / 1e3).toFixed(0) + 'k' : '$' + Math.abs(v).toFixed(0)),
  t: v => fmtN(v) + ' t', pct1: v => (v * 100).toFixed(1) + '%', pct0: v => (v * 100).toFixed(0) + '%',
  pctS: v => sgn(v * 100, 1), pctS1: v => sgn(v * 100, 1), int: v => fmtN(v), kcs: v => fmtK(v) + ' cs',
};
const fmtVal = (v, f) => (F[f] || (x => x))(v);
function fmtDelta(d, f) { if (d == null) return ''; if (f === 'pct') return sgn(d * 100, 1); if (f === 'pp') return sgn(d * 100, 1, ' pp'); if (f === 'pts') return sgn(d, 0, ' pts'); return d; }
const mxn = v => (v < 0 ? '−' : '') + 'MXN ' + (Math.abs(v) >= 1e6 ? (Math.abs(v) / 1e6).toFixed(2) + 'M' : Math.abs(v) >= 1e3 ? (Math.abs(v) / 1e3).toFixed(0) + 'k' : Math.abs(v).toFixed(2));
const panel = (cls, head, body, extra = '') => `<div class="panel ${cls}" ${extra}><div class="ph">${head}</div><div class="pb">${body}</div></div>`;
const aiHead = (title, sub = '', right = '') => `<span class="ai-ic">${ico('spark')}</span><h3>${title}</h3>${sub ? `<span class="sub">${sub}</span>` : ''}<div class="right">${right}</div>`;
const shimmer = '<div class="shimmer"></div><div class="shimmer w80"></div><div class="shimmer w60"></div>';

function kpiTiles(el, list) {
  el.innerHTML = list.map(k => {
    const good = k.good ?? (k.delta == null ? null : k.delta >= 0);
    const cls = k.delta == null ? 'mut' : (good ? 'up' : 'dn');
    const sp = (k.spark && k.spark.length > 2) ? spark(k.spark, good === false ? 'var(--neg)' : 'var(--gold)', 70, 26) : '';
    return `<div class="panel kpi"><div class="kl">${k.label}</div><div class="kv">${fmtVal(k.value, k.fmt)}</div><div class="kd">${k.delta != null ? `<span class="${cls}">${fmtDelta(k.delta, k.delta_fmt)}</span>` : ''}<span class="ks">${k.sub || ''}</span></div><div class="ksp">${sp}</div></div>`;
  }).join('');
}
async function narr(el, task, params = {}, fresh = false) {
  if (!el) return;
  el.innerHTML = shimmer;
  const q = new URLSearchParams({ lang: S.lang, ...params, ...(fresh ? { fresh: 1 } : {}) }).toString();
  try { const r = await API.get(`narrative/${task}?${q}`); if (el.isConnected) el.innerHTML = `<div class="md narr">${md(r.text)}</div>`; }
  catch (e) { el.innerHTML = '<div class="empty">AI narrative unavailable right now.</div>'; }
}
async function approveRec(key, btn) {
  try { await API.post(`recs/${key}/approve`); if (btn) { btn.textContent = 'Approved ✓'; btn.classList.add('done'); btn.disabled = true; }
    toast('Approved · queued for SAP write-back. Post it from <b>SAP Data Hub</b>.', ''); refreshMeta(); }
  catch (e) { toast('Could not approve: ' + esc(e.message), 'neg'); }
}

/* ======================================================================= screens */
const SCREENS = {
  overview: { title: 'LATAM Commercial Command Center', sub: () => `${S.meta?.today_label || ''} · 7 markets · USD at constant FX`, load: () => API.get('overview'), render: renderOverview },
  pricing: { title: 'Pricing &amp; Promotions', sub: () => 'Revenue growth management · elasticity models + guardrails · Mexico · modern trade', load: () => API.get('pricing'), render: renderPricing },
  market: { title: 'Market Pulse', sub: () => 'Consumer trends · POS sell-out · competitor activity · macro, regulation &amp; weather', load: () => API.get('market'), render: renderMarket },
  forecast: { title: 'Demand Forecast · SAP AI Overlay', sub: () => 'Predictive demand sensing over SAP S/4HANA history vs the SAP IBP statistical baseline', load: () => API.get(`forecast?dc=${S.fcDc || 'MX1D'}&sku=${S.fcSku || '100045'}`), render: renderForecast },
  inventory: { title: 'Localized Inventory · SAP AI Overlay', sub: () => 'Stock by DC from SAP (MATDOC / I_MaterialStock) · probabilistic stock-out risk · AI rebalancing', load: () => API.get('inventory'), render: renderInventory },
  routes: { title: 'Distribution Route Optimizer · SAP AI Overlay', sub: () => 'Risk-aware vehicle routing over SAP shipments (VTTK/VTTP) · landslides, security, heat &amp; altitude', load: () => API.get('routes'), render: renderRoutes },
  sap: { title: 'SAP Data Hub &amp; AI Overlay', sub: () => 'Read-only extraction from S/4HANA · AI annotations on standard transactions · governed write-back', load: () => API.get('sap'), render: renderSAP },
  demo: { title: 'Demo Control &amp; AI Settings', sub: () => 'Presenter cockpit · LLM gateway · scenario injection · real-time stream', load: () => API.get('demo'), render: renderDemo },
};

async function go(s, opts = {}) {
  S.cur = s;
  $$('.nav').forEach(n => n.classList.toggle('active', n.dataset.s === s));
  const sc = SCREENS[s];
  $('#pgTitle').innerHTML = sc.title; $('#pgSub').innerHTML = sc.sub();
  $('#cpCtx').textContent = $('.nav.active').childNodes[1].textContent;
  if (S.demoTimer) { clearInterval(S.demoTimer); S.demoTimer = null; }
  const content = $('#content');
  if (!opts.keepScroll) { content.innerHTML = `<section class="screen active"><div class="panel"><div class="pb">${shimmer}</div></div></section>`; window.scrollTo({ top: 0 }); }
  try {
    const d = await sc.load();
    if (S.cur !== s) return;
    S.data[s] = d;
    const y = window.scrollY;
    content.innerHTML = `<section class="screen active" id="s-${s}"></section>`;
    sc.render($('#s-' + s), d);
    if (opts.keepScroll) window.scrollTo({ top: y });
  } catch (e) { content.innerHTML = `<section class="screen active"><div class="alert-bar">Could not load: ${esc(e.message)}</div></section>`; }
}
function rerender() { const d = S.data[S.cur]; const el = $('#s-' + S.cur); if (d && el) SCREENS[S.cur].render(el, d, true); }

/* ----------------------------------------------------------------------- 1. command center */
const OV_LANES = [{ a: [25.67, -100.31], b: [19.67, -99.18], flow: 1 }, { a: [25.67, -100.31], b: [32.51, -117.04] }, { a: [25.67, -100.31], b: [20.97, -89.62] }, { a: [20.67, -103.35], b: [19.67, -99.18], flow: 1, k: .3 }, { a: [19.67, -99.18], b: [14.63, -90.51] }, { a: [19.05, -104.32], b: [-12.05, -77.15], sea: 1, k: .12 }, { a: [19.2, -96.13], b: [10.4, -75.53], sea: 1 }, { a: [10.4, -75.53], b: [9.36, -79.9], sea: 1 }, { a: [-23.19, -46.88], b: [-8.05, -34.95] }, { a: [-23.19, -46.88], b: [-3.12, -60.02], sea: 1, k: .15 }, { a: [-23.19, -46.88], b: [-30.03, -51.23] }, { a: [-30.03, -51.23], b: [-34.46, -58.91] }, { a: [-34.46, -58.91], b: [-33.44, -70.79], k: .1 }, { a: [4.71, -74.21], b: [6.24, -75.58] }, { a: [4.71, -74.21], b: [10.96, -74.8] }, { a: [-12.27, -76.87], b: [-16.4, -71.54] }];
const SEV = { neg: 'var(--neg)', warn: 'var(--warn)', info: 'var(--info)', pos: 'var(--pos)' };

function renderOverview(el, d, redraw) {
  el.innerHTML = `<div class="kpis" id="ovKpis"></div>
  <div class="grid">
    ${panel('ai-card s7', aiHead('AI morning briefing', `${d.signals.length} signals that need a decision today`, `<span class="ai-tag">${ico('spark', 11)} AI summary</span><button class="btn ghost sm" id="ovRegen">Regenerate</button>`), `<div id="ovSummary"></div><div id="ovBrief" style="margin-top:12px;border-top:1px dashed var(--line);padding-top:10px"></div>`)}
    ${panel('s5', `<h3>LATAM network &amp; market health</h3><div class="right legend"><span><svg width="10" height="10"><rect width="9" height="9" rx="2" style="fill:var(--gold)"/></svg>Plant</span><span><svg width="10" height="10"><circle cx="5" cy="5" r="4" style="fill:var(--tx2)"/></svg>DC</span><span><svg width="10" height="10"><circle cx="5" cy="5" r="4" style="fill:var(--neg)"/></svg>Alert</span><span><svg width="18" height="6"><path d="M0 3h18" style="stroke:var(--info);stroke-dasharray:4 3;stroke-width:1.5"/></svg>Sea / river</span></div>`, `<div id="ovMap" class="mapbox cw"></div>`)}
    ${panel('s7', `<h3>Market performance · MTD</h3><span class="sub">Sell-in from SAP billing · share from POS panel (MAT)</span>`, `<div class="tw"><table class="tbl" id="ovTable"></table></div>`)}
    ${panel('s5', `<h3>Live POS pulse</h3><span class="pill p-pos"><span class="dot blink" style="width:6px;height:6px"></span>streaming</span><div class="right"><span class="sub">sell-out units / min</span></div>`, `<div id="ovPulse" class="cw"></div><div id="ovChan" style="margin-top:8px"></div>`)}
    ${panel('s12', `<h3>AI recommendation queue</h3><span class="sub">${d.recs_pending} pending · ${F.usd(d.recs_value)} value at stake · every action needs human approval before SAP write-back</span>`, `<div class="recs" id="ovRecs"></div>`)}
  </div>`;
  kpiTiles($('#ovKpis'), d.kpis);
  if (!redraw || !S.ovSummary) narr($('#ovSummary'), 'briefing').then(() => S.ovSummary = $('#ovSummary')?.innerHTML);
  else $('#ovSummary').innerHTML = S.ovSummary;
  $('#ovRegen').onclick = () => narr($('#ovSummary'), 'briefing', {}, true).then(() => S.ovSummary = $('#ovSummary')?.innerHTML);
  $('#ovBrief').innerHTML = d.signals.map(b => `<div class="brief"><span class="sev" style="background:${SEV[b.sev]}"></span><div><h4>${esc(b.title)}</h4><p>${esc(b.text)}</p><div class="acts"><span class="pill p-ai">${ico('spark', 11)} ${esc(b.action)}</span><button class="btn sm ghost" data-go="${b.goto}">Open →</button></div></div></div>`).join('');
  const col = m => m.vs_plan >= 0.98 ? 'var(--pos)' : m.vs_plan >= 0.95 ? 'var(--warn)' : 'var(--neg)';
  mapSVG($('#ovMap'), {
    view: [-119, -32, -56, 33.5],
    bubbles: d.markets.map(m => ({ lat: m.centroid[0], lon: m.centroid[1], r: 7 + Math.sqrt(m.rev / 1e6) * 3.6, c: col(m), t: `${m.code === 'CA' ? 'CAM' : m.code} $${(m.rev / 1e6).toFixed(1)}M`, tip: `${m.name}: ${sgn(m.vs_py * 100, 1)} vs PY · ${(m.vs_plan * 100).toFixed(1)}% of plan` })),
    lanes: OV_LANES,
    nodes: d.nodes.map(n => ({ t: n.t === 'plant' ? 'plant' : 'dc', n: n.n, lat: n.lat, lon: n.lon, alert: n.alert, lbl: n.t === 'plant' ? n.id : '', dx: n.id === 'MX02' ? -9 : 9, anc: n.id === 'MX02' ? 'end' : 'start' })),
  });
  $('#ovTable').innerHTML = `<thead><tr><th>Market</th><th class="r">Net rev MTD</th><th class="r">vs PY</th><th>vs plan</th><th class="r">Volume t</th><th class="r">Value share</th><th class="r">GM</th><th class="r">OTIF</th><th class="c">Alerts</th></tr></thead><tbody>${d.markets.map(m => `<tr><td><span class="flag">${m.code}</span>${m.name === 'Central America' ? 'C. America' : m.name}</td><td class="r"><b>$${(m.rev / 1e6).toFixed(1)}M</b></td><td class="r ${m.vs_py >= 0 ? 'up' : 'dn'}">${sgn(m.vs_py * 100, 1)}</td><td><div style="display:flex;gap:8px;align-items:center"><div class="bar-in" style="flex:1"><i style="width:${Math.min(100, m.vs_plan * 100)}%;background:${col(m)}"></i></div><span class="num mut" style="font-size:11px">${(m.vs_plan * 100).toFixed(1)}%</span></div></td><td class="r">${fmtN(m.vol)}</td><td class="r">${(m.share * 100).toFixed(1)}% <span class="${m.share_d >= 0 ? 'up' : 'dn'}" style="font-size:11px">${sgn(m.share_d * 100, 1, '')}</span></td><td class="r">${(m.gm * 100).toFixed(1)}%</td><td class="r ${m.otif < 0.9 ? 'dn' : ''}">${(m.otif * 100).toFixed(1)}%</td><td class="c">${m.alerts ? `<span class="pill p-neg">${m.alerts}</span>` : '<span class="mut">—</span>'}</td></tr>`).join('')}</tbody>`;
  renderPulse();
  const cc = { TT: 'var(--gold)', MT: 'var(--info)', CONV: 'var(--teal)', DISC: 'var(--ai)', ECOM: 'var(--tx3)' };
  $('#ovChan').innerHTML = `<div class="stk" style="height:10px">${d.channel_mix.map(c => `<i style="width:${c.share * 100}%;background:${cc[c.code]}"></i>`).join('')}</div><div class="legend" style="margin-top:6px">${d.channel_mix.map(c => `<span><i class="sw" style="background:${cc[c.code]}"></i>${c.name} ${(c.share * 100).toFixed(0)}%</span>`).join('')}</div>`;
  $('#ovRecs').innerHTML = d.recs.map(r => `<div class="rec"><div class="top"><span class="pill p-${r.tone}">${r.type}</span><span class="pill">${r.market}</span><span class="conf">confidence ${(r.confidence * 100).toFixed(0)}%</span></div><h4>${esc(r.title)}</h4><div class="meta"><span>${r.metric} <b>${esc(r.metric_value)}</b></span><span>Owner <b>${r.owner}</b></span></div><div class="acts">${r.status === 'approved' ? '<button class="btn sm done" disabled>Approved ✓</button>' : `<button class="btn pri sm" data-rec="${r.key}">Approve</button>`}<button class="btn sm" data-go="${r.type === 'Pricing' || r.type === 'Promo' ? 'pricing' : r.type === 'Logistics' ? 'routes' : 'sap'}">Review</button></div></div>`).join('');
}
function renderPulse() {
  const el = $('#ovPulse'); if (!el || !el.offsetParent || S.pulse.length < 3) return;
  lineChart(el, { x: S.pulse.map((_, i) => (i - S.pulse.length + 1) + 's'), xEvery: 15, h: 150, padL: 40, series: [{ name: 'Units / min', data: S.pulse, color: 'var(--pos)', area: 1, w: 1.8 }] });
}

/* ----------------------------------------------------------------------- 2. pricing */
function renderPricing(el, p) {
  const a = p.alert, o = p.options, ai = o.ai;
  el.innerHTML = `<div class="alert-bar"><span class="dot neg blink"></span><b>Competitor move detected 06:40</b><span>${esc(p.hero.comp_product)} ${sgn(-a.cut * 100, 0)} (MXN ${a.comp_regular.toFixed(2)} → ${a.comp_now.toFixed(2)}) at ${p.hero.customer} · CDMX &amp; Edomex modern trade</span><span class="mut">source: retailer POS scan feed</span><div class="right"><span class="pill p-neg">${esc(p.hero.sku_name)} sell-out ${sgn(a.impact * 100, 0)} vs expected</span><span class="pill">Price index ${a.index_before.toFixed(0)} → ${a.index_now.toFixed(0)}</span></div></div>
  <div class="grid">
    ${panel('s8', `<h3>Response options · ${esc(p.hero.sku_name)} · ${p.hero.customer}</h3><span class="sub">8-week horizon incl. carry-over &amp; post-promo dip · vs pre-disruption baseline</span>`, `<div class="opts" id="prOpts"></div>`)}
    ${panel('ai-card s4', aiHead('Why option C'), `<div id="prWhy" style="margin-bottom:10px"></div><div class="mut" style="font-size:10.5px;margin-bottom:4px">DRIVER CONTRIBUTION (toward promo ← → toward hold)</div><div id="prDrivers"></div><div class="mut" style="font-size:10.5px;margin:10px 0 2px">GUARDRAILS · OPTION C</div><div id="prGuard"></div>`)}
    ${panel('s8', `<h3>What-if simulator</h3><span class="sub">Own-price elasticity ${p.elasticity.own.toFixed(1)} · cross-elasticity vs competitor ${sgn(p.elasticity.cross, 1, '')} · re-estimated from POS with empirical-Bayes shrinkage</span>`,
      `<div class="sim"><div class="ctl">
        <div><label>TPR depth <b id="vD"></b></label><input type="range" id="iD" min="0" max="20" value="${Math.round(ai.depth * 100)}"></div>
        <div><label>Duration <b id="vW"></b></label><input type="range" id="iW" min="1" max="6" value="${ai.weeks || 3}"></div>
        <div><label>Assumed competitor cut <b id="vC"></b></label><input type="range" id="iC" min="0" max="25" value="${Math.round(a.cut * 100)}"></div>
        <label class="tog"><input type="checkbox" id="iDisp" ${ai.display ? 'checked' : ''}> Secondary display (+6% lift, cost per week)</label>
        <div style="display:flex;gap:6px"><button class="btn sm" id="bestBtn">${ico('spark', 13)}Snap to AI optimum</button></div></div>
        <div><div class="outs"><div class="out"><div class="l">Shelf price</div><div class="v num" id="oP"></div></div><div class="out"><div class="l">Price index vs competitor</div><div class="v num" id="oI"></div></div><div class="out"><div class="l">Volume · 8 wks</div><div class="v num" id="oV"></div></div><div class="out"><div class="l">Gross profit Δ · 8 wks</div><div class="v num" id="oG"></div></div></div>
        <div class="legend" style="margin-bottom:4px"><span><i class="sw" style="background:var(--ai)"></i>Gross profit Δ vs depth (MXN)</span><span><svg width="10" height="10"><circle cx="5" cy="5" r="4" style="fill:var(--gold)"/></svg>Your scenario</span><span><svg width="10" height="10"><circle cx="5" cy="5" r="4" style="fill:var(--ai)"/></svg>Best within guardrails</span><span id="oGuard"></span></div>
        <div id="prCurve" class="cw"></div></div></div>`)}
    ${panel('s4', `<h3>Price-pack architecture · Mexico</h3><span class="sub">Coin price points matter in traditional trade</span>`, `<div class="tw"><table class="tbl" id="prPPA"></table></div>`)}
    ${panel('s8', `<h3>Promotion calendar · Mexico · Q4</h3><span class="sub">Promo ROI from post-event analysis; AI flags below-hurdle events</span><div class="right legend"><span><i class="sw" style="background:var(--pos);height:8px"></i>ROI ≥ 1.3x</span><span><i class="sw" style="background:var(--warn);height:8px"></i>1.0–1.3x</span><span><i class="sw" style="background:var(--neg);height:8px"></i>&lt; 1.0x</span><span><i class="sw" style="background:var(--ai);height:8px"></i>AI draft</span></div>`, `<div id="prGantt"></div>`)}
    ${panel('s4', `<h3>Cocoa cost pass-through</h3><span class="sub">Cocoa cost index (Jan-24 = 100)${p.cocoa.shock ? ' · +8% shock applied' : ''}</span>`, `<div id="prCocoa" class="cw"></div><div class="tw"><table class="tbl" id="prPass" style="margin-top:6px"></table></div>`)}
  </div>`;
  const O = [['A · Hold price', `Keep MXN ${o.hold.price.toFixed(2)}; rely on brand loyalty`, o.hold, false], ['B · Full match', `Match the ${sgn(-a.cut * 100, 0)} cut at MXN ${o.match.price.toFixed(2)} for 3 weeks`, o.match, false], [`C · TPR ${sgn(-ai.depth * 100, 0)}`, `MXN ${ai.price.toFixed(2)} for ${ai.weeks} weeks${ai.display ? ' + display' : ''}, timed to the competitor window`, ai, true]];
  const rec = (S.data.overview?.recs || []).find(r => r.key === 'rec-pricing');
  $('#prOpts').innerHTML = O.map(x => { const r = x[2], bad = r.guardrails.filter(g => g.ok === 'x').length; return `<div class="opt ${x[3] ? 'best' : ''}"><div style="display:flex;align-items:center;gap:6px"><h4>${x[0]}</h4>${x[3] ? `<span class="pill p-ai" style="margin-left:auto">${ico('spark', 11)} Recommended</span>` : (bad ? `<span class="pill p-neg" style="margin-left:auto">${bad} guardrail${bad > 1 ? 's' : ''} broken</span>` : '')}</div><div class="desc">${x[1]}</div>
    <div class="mrow"><span>Shelf price</span><b>MXN ${r.price.toFixed(2)}</b></div><div class="mrow"><span>Price index vs competitor</span><b class="${r.index > 105 || r.index < 95 ? 'dn' : 'up'}">${r.index.toFixed(0)}</b></div>
    <div class="mrow"><span>Volume · 8 wks</span><b class="${r.vol >= 0 ? 'up' : 'dn'}">${sgn(r.vol * 100)}</b></div><div class="mrow"><span>Value share Δ (est.)</span><b class="${r.vol >= 0 ? 'up' : 'dn'}">${sgn(r.vol * 10, 1, ' pp')}</b></div>
    <div class="mrow"><span>Gross profit Δ</span><b class="${r.dgp >= 0 ? 'up' : 'dn'}">${mxn(r.dgp)}</b></div><div class="mrow"><span>Promo ROI vs hold</span><b>${r.roi == null ? '—' : r.roi.toFixed(1) + 'x'}</b></div>
    ${x[3] ? `<div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">${rec && rec.status === 'approved' ? '<button class="btn sm done" disabled>Approved ✓</button>' : '<button class="btn pri sm" data-rec="rec-pricing">Approve → SAP condition</button>'}</div>` : ''}</div>`; }).join('');
  narr($('#prWhy'), 'pricing');
  $('#prDrivers').innerHTML = p.drivers.map(dv => `<div class="drv"><span class="mut">${esc(dv.label)}</span><div class="trk"><i style="${dv.value >= 0 ? `left:50%;width:${Math.min(50, dv.value * 100)}%;background:var(--ai)` : `right:50%;width:${Math.min(50, -dv.value * 100)}%;background:var(--warn)`}"></i></div><span class="num r" style="font-size:11px">${dv.value > 0 ? '+' : '−'}${Math.abs(dv.value).toFixed(2)}</span></div>`).join('');
  $('#prGuard').innerHTML = ai.guardrails.map(g => `<div class="gl-item"><span class="ck ${g.ok}">${g.ok === 'ok' ? '✓' : g.ok === 'w' ? '!' : '✕'}</span><div><b>${g.name}</b> · ${esc(g.detail)}</div></div>`).join('');
  $('#prPPA').innerHTML = `<thead><tr><th>Pack</th><th>Channel</th><th class="r">Now</th><th>AI</th></tr></thead><tbody>${p.ppa.map(r => `<tr><td><b>${esc(r.sku)}</b></td><td class="mut">${r.channel}</td><td class="r">${r.price == null ? '—' : (r.price < 30 ? '$' + r.price.toFixed(0) : '$' + r.price.toFixed(2))}</td><td><span class="pill p-${r.tone}">${esc(r.rec)}</span><div class="mut" style="font-size:10.5px;margin-top:2px">${esc(r.note)}</div></td></tr>`).join('')}</tbody>`;
  const wk = ['W44', 'W45', 'W46', 'W47', 'W48', 'W49', 'W50', 'W51', 'W52', 'W53', 'W01', 'W02'], ci = w => w >= 30 ? w - 44 : 9 + w, pc = i => `${(i / 12 * 100).toFixed(2)}%`;
  const roiCol = c => c.status === 'ai_draft' ? 'var(--ai)' : c.roi == null ? 'var(--tx3)' : c.roi >= 1.3 ? 'var(--pos)' : c.roi >= 1.0 ? 'var(--warn)' : 'var(--neg)';
  const evs = [['Muertos', 0], ['Buen Fin', 2], ['Guadalupe–Reyes', 6.4], ['Navidad', 8.6]];
  $('#prGantt').innerHTML = `<div class="gantt"><div></div><div class="gh">${wk.map(w => `<span>${w}</span>`).join('')}</div><div class="gl2 mut">Events</div><div class="gt" style="height:32px">${evs.map(e => `<span class="ev" style="left:${pc(e[1])}">${e[0]}</span>`).join('')}</div>
    ${p.calendar.map(c => `<div class="gl2" title="${esc(c.name)}">${esc(c.name)}</div><div class="gt" style="height:32px"><span class="gb" style="left:${pc(Math.max(0, ci(c.start)))};width:${pc(Math.min(12 - Math.max(0, ci(c.start)), c.weeks + Math.min(0, ci(c.start))))};background:${roiCol(c)};${c.status === 'ai_draft' ? 'outline:1px dashed #fff;outline-offset:-3px' : ''}">${c.status === 'ai_draft' ? 'AI draft · ' : ''}${c.roi == null ? '' : 'ROI ' + c.roi.toFixed(1) + 'x'}${c.roi != null && c.roi < 1 ? ' ⚠' : ''}</span></div>`).join('')}</div>`;
  lineChart($('#prCocoa'), { x: p.cocoa.months, xEvery: 6, h: 130, padL: 34, series: [{ name: 'Cocoa cost index', data: p.cocoa.series, color: 'var(--gold)', area: 1 }] });
  $('#prPass').innerHTML = `<thead><tr><th>Mkt</th><th class="r">COGS Δ</th><th class="r">Price</th><th>How</th></tr></thead><tbody>${p.cocoa.rows.map(r => `<tr><td><span class="flag">${r.market}</span></td><td class="r dn">${sgn(r.cogs * 100, 1)}</td><td class="r">${sgn(r.price * 100, 1)}</td><td style="font-size:11.5px">${r.how}</td></tr>`).join('')}</tbody>`;
  let tmr;
  const upd = () => { $('#vD').textContent = $('#iD').value + '%'; $('#vW').textContent = $('#iW').value + ($('#iW').value > 1 ? ' wks' : ' wk'); $('#vC').textContent = $('#iC').value + '%'; clearTimeout(tmr); tmr = setTimeout(runSim, 120); };
  ['iD', 'iW', 'iC', 'iDisp'].forEach(id => $('#' + id).addEventListener('input', upd));
  $('#bestBtn').onclick = () => { if (S.simBest != null) { $('#iD').value = S.simBest; upd(); } };
  upd();
}
async function runSim() {
  const body = { depth: +$('#iD').value, weeks: +$('#iW').value, comp: +$('#iC').value, display: $('#iDisp').checked };
  const r = await API.post('pricing/simulate', body); const x = r.result; S.simBest = r.best;
  if (!$('#oP')) return;
  const band = x.index >= 95 && x.index <= 105, broken = x.guardrails.filter(g => g.ok === 'x');
  $('#oP').textContent = 'MXN ' + x.price.toFixed(2); $('#oI').innerHTML = `<span class="${band ? 'up' : 'dn'}">${x.index.toFixed(0)}</span>`;
  $('#oV').innerHTML = `<span class="${x.vol >= 0 ? 'up' : 'dn'}">${sgn(x.vol * 100)}</span>`; $('#oG').innerHTML = `<span class="${x.dgp >= 0 ? 'up' : 'dn'}">${mxn(x.dgp)}</span>`;
  $('#oGuard').innerHTML = broken.length ? `<span class="pill p-neg">✕ ${broken.map(g => g.name).join(', ')}</span>` : '<span class="pill p-pos">✓ all guardrails</span>';
  lineChart($('#prCurve'), { x: r.curve.map((_, i) => i + '%'), xEvery: 2, h: 200, padL: 52, fmt: v => fmtK(v), tfmt: v => mxn(v), series: [{ name: 'GP Δ (8 wks)', data: r.curve, color: 'var(--ai)', markers: [{ i: r.best, fill: 'var(--ai)', label: 'Best ' + r.best + '%' }, { i: body.depth, fill: 'var(--gold)', r: 6 }] }] });
}

/* ----------------------------------------------------------------------- 3. market */
function renderMarket(el, m) {
  el.innerHTML = `<div class="kpis k5" id="mkKpis"></div><div class="grid">
    ${panel('ai-card s7', aiHead('Consumer trend signals', 'Search, social &amp; basket data · YoY momentum · AI implications'), `<div class="trends" id="mkTrends"></div>`)}
    ${panel('s5', `<h3>Value share by market</h3><span class="sub">Chocolate tablets &amp; bars · MAT</span>`, `<div class="legend" id="mkShareLg" style="margin-bottom:8px"></div><div id="mkShare"></div>`)}
    ${panel('s7', `<h3>POS sell-out index by region</h3><span class="sub">% vs prior year · last 12 weeks</span>`, `<div class="tw"><div id="mkHeat"></div></div>`)}
    ${panel('s5', `<h3>Local market dynamics</h3><span class="sub">What the models are conditioning on</span>`, `<div class="feed" id="mkLocal"></div>`)}
    ${panel('s6', `<h3>Channel mix shift · our sell-out</h3><span class="sub">Share of value by channel, by half-year</span>`, `<div class="legend" id="mkChLg" style="margin-bottom:6px"></div><div id="mkChan" class="cw"></div>`)}
    ${panel('s6', `<h3>Competitor activity</h3><span class="sub">Detected from POS, shelf audits, retailer portals &amp; field notes</span>`, `<div class="feed" id="mkComp"></div>`)}
  </div>`;
  kpiTiles($('#mkKpis'), m.kpis);
  $('#mkTrends').innerHTML = m.trends.map(t => `<div class="trend"><div class="tt2"><div><h4>${esc(t.label)}</h4><div class="mk">${t.markets}</div></div><div style="text-align:right"><b class="${t.yoy >= 0 ? 'up' : 'dn'}">${sgn(t.yoy * 100, 0)}</b><div class="mk">YoY</div></div></div>${spark(t.spark, 'var(--teal)', 200, 28)}<div class="imp"><span class="aic">AI →</span> ${t.implication}</div></div>`).join('');
  const SC = ['var(--gold)', 'var(--info)', 'var(--ai)', 'var(--tx3)', 'var(--line2)'];
  $('#mkShareLg').innerHTML = m.share.players.map((p, i) => `<span><i class="sw" style="background:${SC[i]};height:8px"></i>${p}</span>`).join('');
  $('#mkShare').innerHTML = m.share.rows.map(r => `<div class="srow"><span><span class="flag">${r.market}</span><b class="num">${(r.values[0] * 100).toFixed(1)}%</b></span><div class="stk">${r.values.map((v, i) => `<i style="width:${v * 100}%;background:${SC[i]}" title="${m.share.players[i]} ${(v * 100).toFixed(1)}%"></i>`).join('')}</div></div>`).join('');
  $('#mkHeat').innerHTML = `<div class="hm" style="grid-template-columns:130px repeat(${m.heat.weeks.length},minmax(34px,1fr))"><div></div>${m.heat.weeks.map(w => `<div class="ch">${w}</div>`).join('')}${m.heat.rows.map(r => `<div class="rl">${r.region}</div>${r.values.map((v, i) => { if (v == null) return '<div class="c">·</div>'; const a = Math.min(.85, Math.abs(v) / 18 + .08), c = v >= 0 ? `rgba(63,207,142,${a})` : `rgba(242,100,111,${a})`; return `<div class="c" style="background:${c}" title="${r.region} ${m.heat.weeks[i]}: ${v > 0 ? '+' : ''}${v}%">${v > 0 ? '+' : ''}${v}</div>`; }).join('')}`).join('')}</div>`;
  $('#mkLocal').innerHTML = m.local.map(l => `<div class="fi"><span class="sev" style="background:var(--${l.color});width:3px;border-radius:3px"></span><div><b style="font-size:12px">${l.title}</b><div class="mut" style="font-size:11.5px;margin-top:2px">${esc(l.text)}</div></div></div>`).join('');
  const CC = { TT: 'var(--gold)', MT: 'var(--info)', CONV: 'var(--teal)', DISC: 'var(--ai)', ECOM: 'var(--tx3)' };
  $('#mkChLg').innerHTML = m.channel_mix.series.map(c => `<span><i class="sw" style="background:${CC[c.code]};height:8px"></i>${c.name}</span>`).join('');
  stackArea($('#mkChan'), m.channel_mix.periods, m.channel_mix.series.map(c => [c.name, CC[c.code], c.values.map(v => v * 100)]));
  $('#mkComp').innerHTML = m.competitor.map(c => `<div class="fi"><span class="tm">${c.when}</span><div style="flex:1">${esc(c.text)}<div class="src">${c.source}</div></div><span class="pill p-${c.tone}" style="align-self:flex-start">${c.type}</span></div>`).join('');
}

/* ----------------------------------------------------------------------- 4. forecast */
function renderForecast(el, f) {
  el.innerHTML = `<div class="alert-bar sap">${ico('db')}<b>SAP sources</b><span class="mut">VBAK/VBAP sales orders · LIKP/LIPS deliveries · PBIM/PBED PIRs · MARC MRP data</span><span class="mut">+ POS sell-out · promo plan · weather · events</span><div class="right"><span class="pill p-pos">Synced 06:00</span><span class="pill">${fmtN(f.kpis[3].value)} SKU × DC series</span></div></div>
  <div class="kpis k5" id="fcKpis"></div><div class="grid">
    ${panel('s8', `<h3>Weekly demand · ${esc(f.sku_name)} · ${esc(f.dc_name)}</h3><div class="right"><select class="sel sm" id="fcSku">${f.options.skus.map(s => `<option value="${s.id}" ${s.id === f.sku ? 'selected' : ''}>${s.id} · ${esc(s.name)}</option>`).join('')}</select><select class="sel sm" id="fcDc">${f.options.dcs.map(s => `<option value="${s.id}" ${s.id === f.dc ? 'selected' : ''}>${s.id} · ${esc(s.name)}</option>`).join('')}</select></div>`,
      `<div class="legend" style="margin-bottom:6px"><span><i class="sw" style="background:var(--tx)"></i>Actual shipments (SAP LIPS)</span><span><i class="sw" style="background:var(--tx3)"></i>SAP IBP statistical baseline</span><span><i class="sw" style="background:var(--teal)"></i>AI forecast</span><span><i class="lg-band" style="background:var(--teal)"></i>P10–P90</span></div><div id="fcChart" class="cw"></div>`)}
    ${panel('ai-card s4', aiHead('Forecast bridge · next 8 weeks', 'SAP baseline → AI forecast (cases)'), `<div id="fcBridge"></div>`)}
    ${panel('s6', `<h3>Accuracy by market · 13-week backtest</h3><span class="sub">1 − WAPE at SKU × DC × week</span>`, `<div class="tw"><table class="tbl" id="fcAcc"></table></div>`)}
    ${panel('ai-card s6', aiHead('Why the forecast changed'), `<div id="fcWhy"></div><div style="margin-top:12px;border-top:1px dashed var(--line);padding-top:10px"><div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap"><b style="font-size:12px">Write back to SAP</b><span class="pill p-info">MD61 · BAPI_REQUIREMENTS_CHANGE</span><span class="pill p-warn">Simulated</span></div><div class="tw"><table class="tbl" id="fcWB"></table></div><div style="display:flex;gap:6px;margin-top:8px"><button class="btn pri sm" id="fcSend">Send PIR update for approval</button></div></div>`)}
  </div>`;
  kpiTiles($('#fcKpis'), f.kpis.map((k, i) => ({ ...k, good: i === 1 ? Math.abs(k.value) < 0.03 : k.good })));
  const s = f.series;
  lineChart($('#fcChart'), { x: s.labels, xEvery: 8, h: 290, split: s.split, tfmt: v => fmtN(v) + ' cs', ann: s.ann, band: { lo: s.lo, hi: s.hi, color: 'var(--teal)' },
    series: [{ name: 'Actual', data: s.actual, color: 'var(--tx)', w: 1.6 }, { name: 'SAP IBP baseline', data: s.sap, color: 'var(--tx3)', dash: '5 4', w: 1.6 }, { name: 'AI forecast', data: s.ai, color: 'var(--teal)', w: 2.2 }] });
  const tot = f.bridge.filter(b => b.kind === 'total').map(b => b.value), lo0 = Math.min(...tot) * 0.86, sp = Math.max(...tot) * 1.08 - lo0;
  let run = 0; const pc = v => (v - lo0) / sp * 100;
  $('#fcBridge').innerHTML = f.bridge.map(b => { let l, w, c; if (b.kind === 'total') { l = 0; w = pc(b.value); c = b.label.startsWith('AI') ? 'var(--teal)' : 'var(--tx3)'; run = b.value; } else { const st = b.value > 0 ? run : run + b.value; l = pc(st); w = Math.abs(b.value) / sp * 100; c = b.value > 0 ? 'var(--pos)' : 'var(--neg)'; run += b.value; }
    return `<div class="wf"><span class="${b.kind === 'delta' ? 'mut' : ''}" style="${b.kind === 'total' ? 'font-weight:600' : ''}">${b.label}</span><div class="trk"><i style="left:${Math.max(0, l)}%;width:${Math.max(w, .6)}%;background:${c}"></i></div><span class="r num" style="${b.kind === 'total' ? 'font-weight:600' : ''}">${b.kind === 'total' ? fmtN(b.value) : (b.value > 0 ? '+' : b.value < 0 ? '−' : '±') + fmtN(Math.abs(b.value))}</span></div>`; }).join('') + `<div class="bridge-note">Axis starts at ${fmtK(lo0)} cases · each step switches one feature group on in the model</div>`;
  $('#fcAcc').innerHTML = `<thead><tr><th>Market</th><th class="r">SAP IBP</th><th class="r">AI</th><th>Improvement</th><th class="r">Bias AI</th></tr></thead><tbody>${f.accuracy.map(a => `<tr><td><span class="flag">${a.market}</span>${a.name}</td><td class="r mut">${(a.sap * 100).toFixed(1)}%</td><td class="r"><b>${(a.ai * 100).toFixed(1)}%</b></td><td><div style="display:flex;gap:8px;align-items:center"><div class="bar-in" style="flex:1"><i style="width:${Math.max(0, (a.ai - a.sap) * 600)}%;background:var(--teal)"></i></div><span class="${a.ai >= a.sap ? 'up' : 'dn'} num" style="font-size:11px">${sgn((a.ai - a.sap) * 100, 1, ' pp')}</span></div></td><td class="r">${sgn(a.bias_ai * 100, 1)}</td></tr>`).join('')}</tbody>`;
  narr($('#fcWhy'), 'forecast', { dc: f.dc, sku: f.sku });
  $('#fcWB').innerHTML = `<thead><tr><th>Week</th><th class="r">PIR now</th><th class="r">AI proposal</th><th class="r">Δ</th></tr></thead><tbody>${f.writeback.map(x => `<tr><td>${x.week} · 2026</td><td class="r mut">${fmtN(x.pir)}</td><td class="r"><b>${fmtN(x.ai)}</b></td><td class="r ${x.ai >= x.pir ? 'up' : 'dn'}">${x.ai >= x.pir ? '+' : '−'}${fmtN(Math.abs(x.ai - x.pir))}</td></tr>`).join('')}</tbody>`;
  $('#fcSend').onclick = async () => { await API.post('forecast/writeback', { dc: f.dc, sku: f.sku }); $('#fcSend').textContent = 'Queued for approval ✓'; $('#fcSend').classList.add('done'); $('#fcSend').disabled = true; toast('PIR update queued for demand-planner approval in <b>SAP Data Hub</b>', ''); refreshMeta(); };
  const reload = () => { S.fcSku = $('#fcSku').value; S.fcDc = $('#fcDc').value; go('forecast'); };
  $('#fcSku').onchange = reload; $('#fcDc').onchange = reload;
}

/* ----------------------------------------------------------------------- 5. inventory */
function renderInventory(el, v) {
  const k = v.kpis;
  el.innerHTML = `<div class="kpis k5" id="invKpis"></div><div class="grid">
    ${panel('s8', `<h3>Inventory health · days of supply by DC × SKU</h3><div class="right legend"><span><i class="sw" style="background:var(--neg);height:8px"></i>&lt; 7 d</span><span><i class="sw" style="background:var(--warn);height:8px"></i>7–14 d</span><span><i class="sw" style="background:var(--pos);height:8px"></i>15–45 d</span><span><i class="sw" style="background:var(--info);height:8px"></i>46–60 d</span><span><i class="sw" style="background:var(--ex);height:8px"></i>&gt; 60 d excess</span></div>`, `<div class="tw"><div id="invMx"></div></div>`)}
    ${panel('ai-card s4', aiHead('AI rebalancing actions', 'Stock transfers, pull-ins &amp; markdowns'), `<div id="invNote" style="margin-bottom:10px"></div><div style="display:flex;flex-direction:column;gap:8px" id="invAct"></div>`)}
    ${panel('s6', `<h3>Projected stock · ${esc(v.projection.sku)} · ${esc(v.projection.dc)}</h3><span class="sub">AI demand · open orders · planned receipts · stock-out risk ${Math.round(v.projection.p14 * 100)}%</span>`, `<div class="legend" style="margin-bottom:6px"><span><i class="sw" style="background:var(--neg)"></i>Without action</span><span><i class="sw" style="background:var(--teal)"></i>With AI plan</span><span><i class="sw" style="background:var(--warn)"></i>Safety stock</span></div><div id="invProj" class="cw"></div>`)}
    ${panel('s6', `<h3>Shelf-life exposure</h3><span class="sub">Value at cost by remaining shelf life (USD)</span>`, `<div id="invAge"></div>`)}
  </div>`;
  kpiTiles($('#invKpis'), [
    { label: 'Network days of supply', value: k.dos, fmt: 'int', sub: '18 DCs · AI demand next 14 d', delta: null },
    { label: 'At-risk SKU × DC (14 d)', value: k.at_risk, fmt: 'int', sub: `${k.critical} critical (≥ 60%)`, delta: null },
    { label: 'Short shelf-life (< 60 d)', value: k.short_life_usd, fmt: 'usdM', sub: 'seasonal leftovers', delta: null },
    { label: 'Projected case fill rate', value: k.fill, fmt: 'pct1', sub: 'next 14 days, no action', delta: null },
    { label: 'Inventory value (cost)', value: k.inv_value, fmt: 'usdM', sub: `${F.usd(k.ss_release)} safety stock releasable`, delta: null }]);
  const col = x => x == null ? 'transparent' : x < 7 ? 'var(--neg)' : x < 15 ? 'var(--warn)' : x <= 45 ? 'var(--pos)' : x <= 60 ? 'var(--info)' : 'var(--ex)';
  const mx = v.matrix;
  $('#invMx').innerHTML = `<div class="mx" style="grid-template-columns:62px repeat(${mx.skus.length},minmax(58px,1fr))"><div></div>${mx.skus.map(s => `<div class="mut" style="font-size:10px;text-align:center;line-height:1.2;padding-bottom:3px">${esc(s)}</div>`).join('')}${mx.codes.map((c, i) => `<div class="mut" style="display:flex;align-items:center;font-weight:600">${c}</div>${mx.values[i].map((x, j) => x == null ? '<div class="c" style="color:var(--tx3)">·</div>' : `<div class="c" title="${c} · ${mx.skus[j]}: ${x} days · stock-out risk ${Math.round(mx.risk[i][j] * 100)}%" style="background:color-mix(in oklab,${col(x)} ${x < 15 || x > 60 ? 42 : 20}%,transparent);color:${x < 15 || x > 60 ? 'var(--tx)' : 'var(--tx2)'}">${x > 999 ? '∞' : x}</div>`).join('')}`).join('')}</div>`;
  narr($('#invNote'), 'inventory');
  const recs = S.data.overview?.recs || [];
  $('#invAct').innerHTML = v.actions.map(a => { const key = a.kind === 'rebalance' && a.dc === 'MX1D' ? 'rec-sto' : a.kind === 'prebuild' ? `rec-pre-${a.sku}` : null; const r = recs.find(x => x.key === key);
    const btn = key ? (r && r.status === 'approved' ? '<button class="btn sm done" disabled>Approved ✓</button>' : `<button class="btn pri sm" data-rec="${key}">${a.kind === 'markdown' ? 'Send to RGM' : 'Create STO in SAP (UB)'}</button>`) : `<button class="btn pri sm" data-toast="${a.kind === 'markdown' ? 'Markdown proposal sent to RGM for approval' : 'Draft created and sent for approval (simulated)'}">${a.kind === 'markdown' ? 'Send to RGM' : 'Create draft'}</button>`;
    return `<div class="sto"><h4>${esc(a.title)}</h4><div class="ln">${esc(a.detail)}</div><div class="ln aic" style="font-size:11px">${esc(a.why)}${a.value ? ' · ' + F.usd(a.value) + ' value' : ''}</div><div class="acts">${btn}<button class="btn sm ghost" data-go="sap">MD04 view</button></div></div>`; }).join('') || '<div class="empty">No actions needed.</div>';
  const pj = v.projection;
  lineChart($('#invProj'), { x: pj.dates, xEvery: 3, h: 230, padT: 30, tfmt: x => fmtN(x) + ' cs', hline: [{ v: pj.ss, color: 'var(--warn)', label: 'Safety stock ' + fmtN(pj.ss) }], zero: 1,
    series: [{ name: 'Without action', data: pj.asis, color: 'var(--neg)', dash: '5 4' }, { name: 'With AI plan', data: pj.plan, color: 'var(--teal)', w: 2.4, markers: pj.markers }] });
  const mxv = Math.max(...v.aging.map(a => a.usd));
  $('#invAge').innerHTML = v.aging.map((g, i) => `<div class="wf" style="grid-template-columns:90px 1fr 60px"><span class="mut">${g.label}</span><div class="trk"><i style="left:0;width:${Math.max(1.2, Math.sqrt(g.usd / mxv) * 100)}%;background:${['var(--neg)', 'var(--warn)', 'var(--info)', 'var(--pos)', 'var(--pos)'][i]};opacity:.8"></i></div><span class="r num">${F.usd(g.usd)}</span></div>`).join('') + '<div class="mut" style="font-size:10.5px;margin-top:4px">Bar length on a square-root scale</div>';
}

/* ----------------------------------------------------------------------- 6. routes */
function renderRoutes(el, r) {
  const dis = r.disruption;
  el.innerHTML = `${dis ? `<div class="alert-bar warn"><span class="dot warn blink"></span><b>Disruption 05:12</b><span>Landslide (huaico) closes Carretera Central at km 98, San Mateo. Estimated reopening in 36–48 h.</span><span class="mut">source: road-authority alert feed (mock)</span><div class="right"><button class="btn sm ghost" id="rtClear">Clear disruption</button></div></div>`
    : `<div class="alert-bar ok"><span class="dot"></span><b>Network nominal</b><span>No active road closures in Peru. The risk-aware plan is compared with a cost-only plan.</span><div class="right"><button class="btn pri sm" id="rtInject">${ico('spark', 13)}Simulate huaico on Carretera Central</button></div></div>`}
  <div class="grid">
    ${panel('s7', `<h3>Network view · Central &amp; Southern Peru</h3><div class="right legend">${dis ? '<span><i class="sw" style="background:var(--neg)"></i>Blocked original route</span>' : ''}<span><i class="sw" style="background:var(--teal)"></i>AI plan · Junín &amp; centre</span><span><i class="sw" style="background:var(--gold)"></i>From DC Arequipa</span><span><i class="sw" style="background:var(--tx3)"></i>Other routes</span></div>`, `<div id="rtMap" class="mapbox cw"></div>`)}
    ${panel('ai-card s5', aiHead(dis ? 'Re-optimized plan' : 'Risk-aware plan', '', `<span class="pill p-ai">${r.solver} · ${r.stops} stops · ${r.used}/${r.vehicles} trucks · ${r.solve_s.toFixed(1)} s</span>`),
      `<div id="rtWhy" style="margin-bottom:10px"></div><div class="cmp" id="rtCmp"></div><div style="display:flex;flex-direction:column;gap:8px;margin-top:12px" id="rtRoutes"></div>
       <div style="display:flex;gap:6px;margin-top:10px">${dis ? '<button class="btn pri sm" data-rec="rec-route">Approve &amp; update SAP shipments</button>' : ''}<button class="btn sm ghost" data-toast="Customers notified through the pre-venta app (simulated)">Notify customers</button></div>`)}
    ${panel('s4', `<h3>Risk layers &amp; constraints</h3>`, `<div id="rtLayers"></div>`)}
    ${panel('s8', `<h3>Lane risk scoring · network top lanes</h3><span class="sub">Risk-weighted cost = freight + λ·risk (λ = 0.35) · scores 0–100</span>`, `<div class="tw"><table class="tbl" id="rtLanes"></table></div>`)}
  </div>`;
  if ($('#rtInject')) $('#rtInject').onclick = () => inject('huaico_pe');
  if ($('#rtClear')) $('#rtClear').onclick = async () => { await API.post('demo/clear/huaico_pe'); };
  const kc = { blocked: 'var(--neg)', ai: 'var(--teal)', south: 'var(--gold)', other: 'var(--tx3)' };
  const routes = [...r.map.routes].sort((a, b) => ['other', 'south', 'blocked', 'ai'].indexOf(a.kind) - ['other', 'south', 'blocked', 'ai'].indexOf(b.kind));
  const show = new Set(['LUR', 'AQP', 'HYO', 'ORY', 'CPS', 'CNT', 'CUZ', 'JUL', 'AYA', 'ICA', 'TAR', 'JAU', 'HCO', 'PUN', 'NAZ', 'SMT']);
  mapSVG($('#rtMap'), { view: [r.map.view[0], r.map.view[1], r.map.view[2], r.map.view[3]],
    under: [P => { const pts = [[-9.6, -77.3], [-10.5, -76.6], [-11.6, -76.1], [-12.8, -75], [-13.8, -73.5], [-14.6, -72], [-15.8, -70.6], [-17.5, -69.8]]; const d = pts.map((q, i) => { const [x, y] = P(q[0], q[1]); return (i ? 'L' : 'M') + x + ',' + y; }).join(''); const [tx, ty] = P(-14.55, -73.9); return `<path d="${d}" style="fill:none;stroke:var(--cocoa);stroke-width:34;stroke-opacity:.3;stroke-linecap:round;stroke-linejoin:round"/><text x="${tx}" y="${ty}" class="cl" style="font-size:8.5px" transform="rotate(34 ${tx} ${ty})">CORDILLERA DE LOS ANDES</text>`; }],
    labels: [{ t: 'PERU', lat: -11.4, lon: -73.2, st: 'font-size:13px;letter-spacing:.3em' }, { t: 'PACIFIC OCEAN', lat: -15.6, lon: -77.2, st: 'font-size:9px;fill:var(--info);opacity:.7' }, { t: 'BRAZIL', lat: -10.5, lon: -70.3 }],
    paths: routes.map(x => ({ pts: x.pts, c: kc[x.kind], w: x.kind === 'other' ? 1.4 : 2.6, dash: x.kind === 'blocked' ? '6 4' : '', flow: x.kind === 'ai' || x.kind === 'south' })),
    nodes: r.map.towns.filter(t => show.has(t.code)).map(t => ({ n: t.name, lat: t.lat, lon: t.lon, r: t.code === 'LUR' || t.code === 'AQP' ? 6 : 3.6, c: t.code === 'LUR' || t.code === 'AQP' ? 'var(--tx)' : undefined, lbl: t.code === 'SMT' ? '' : t.name, dx: ['LUR', 'AQP', 'CNT', 'JUL'].includes(t.code) ? -9 : 9, anc: ['LUR', 'AQP', 'CNT', 'JUL'].includes(t.code) ? 'end' : 'start', dy: t.code === 'CNT' ? -3 : 3 }))
      .concat(r.map.closure ? [{ t: 'x', lat: r.map.closure.lat, lon: r.map.closure.lon, lbl: 'km 98 · closed', dx: -4, dy: 22, anc: 'end' }] : []) });
  narr($('#rtWhy'), 'routes');
  $('#rtCmp').innerHTML = `<div class="h">KPI</div><div class="h">${dis ? 'Original plan' : 'Cost-only plan'}</div><div class="h">${dis ? 'AI re-optimized' : 'AI risk-aware'}</div>${r.kpis.map(x => `<div class="mut">${x[0]}</div><div>${x[1]}</div><div class="${x[3] ? 'up' : 'dn'}"><b>${x[2]}</b></div>`).join('')}`;
  const cc = { teal: 'var(--teal)', gold: 'var(--gold)', neg: 'var(--neg)', tx3: 'var(--tx3)' };
  $('#rtRoutes').innerHTML = r.cards.map(c => `<div class="route"><span class="sw2" style="background:${cc[c.color]}"></span><div><h4>${c.vehicle !== '—' ? c.vehicle + ' · ' : ''}${esc(c.title)}</h4><p>${esc(c.detail)}</p></div></div>`).join('');
  $('#rtLayers').innerHTML = [['var(--neg)', 'Landslides & road closures', dis ? '1 critical' : 'none active'], ['var(--info)', 'Rain & flooding', 'Andes: moderate'], ['var(--ai)', 'Cargo-theft corridors', 'MX 57D, BR-116'], ['var(--warn)', 'Heat & melt risk (> 28°C)', 'Ica, Nazca, north coast'], ['var(--cocoa)', 'Altitude > 4,000 m', 'Ticlio 4,818 m'], ['var(--teal)', 'Border & port delays', 'Callao 14 h'], ['var(--tx3)', 'Urban truck windows', 'Lima, Bogotá, CDMX']].map(l => `<label class="layer"><input type="checkbox" checked style="accent-color:var(--ai)"><span class="sw3" style="background:${l[0]}"></span>${l[1]}<span class="v">${l[2]}</span></label>`).join('')
    + `<div class="mut" style="font-size:10.5px;margin:10px 0 4px;letter-spacing:.06em">CONSTRAINTS</div><div class="kv2" style="grid-template-columns:120px 1fr;font-size:11.5px"><span>Fleet</span><span>${r.vehicles} trucks · 6 reefer · 1,400 cs each</span><span>Product temp</span><span>Reefer for hot towns (&gt; 28°C)</span><span>Time windows</span><span>Lima 14 h · urgent 24 h · others 34 h</span><span>Unpaved roads</span><span>Daylight only, slower</span><span>Deferral</span><span>Non-urgent stops only, during disruptions</span></div>`;
  const rc = x => x >= 70 ? 'var(--neg)' : x >= 50 ? 'var(--warn)' : x >= 35 ? 'var(--info)' : 'var(--pos)';
  $('#rtLanes').innerHTML = `<thead><tr><th>Lane</th><th>Mode</th><th>Primary risk</th><th class="c">Risk</th><th>AI action</th></tr></thead><tbody>${r.lanes.map(l => `<tr><td><b>${esc(l.lane)}</b>${l.active ? ' <span class="pill p-neg">live</span>' : ''}</td><td class="mut">${l.mode}</td><td>${esc(l.risk)}</td><td class="c"><span class="risk" style="background:color-mix(in oklab,${rc(l.score)} 22%,transparent);color:${rc(l.score)}">${l.score}</span></td><td class="aic" style="font-size:11.5px">${esc(l.action)}</td></tr>`).join('')}</tbody>`;
}

/* ----------------------------------------------------------------------- 7. SAP hub */
function renderSAP(el, s) {
  const c = s.connection, m = s.md04;
  el.innerHTML = `<div class="grid">
    ${panel('s4', `<h3>Connection</h3><span class="pill p-pos">Healthy</span><span class="pill p-warn">${c.mode === 'mock' ? 'Mock replica' : 'Live'}</span>`, `<div class="kv2">${[['System', c.system], ['Client', c.client], ['Company codes', c.company_codes], ['Access', c.access], ['Live connection', esc(c.switch)], ['Last full sync', c.last_sync], ['Delta sync', c.delta], ['Write-back', c.writeback]].map(x => `<span>${x[0]}</span><span>${x[1]}</span>`).join('')}</div>`)}
    ${panel('s8', `<h3>Data lineage · SAP objects → CABI models</h3><span class="sub">The mock adapter serves extracts shaped like the OData / CDS payloads</span>`, `<div class="tw"><table class="tbl" id="sapLin"></table></div>`)}
    ${panel('s8 md04', aiHead('AI overlay on MD04 · Stock/Requirements List', '', '<label class="tog"><input type="checkbox" checked id="sapAiTog"> Show AI annotations</label>'),
      `<div class="fiori"><div class="fh"><b>Stock/Requirements List</b><span class="mut">Material</span>${m.sku} ${esc(m.sku_name)}<span class="mut">Plant</span>${m.dc} ${esc(m.dc_name)}<span class="mut">MRP type</span>${m.mrp_type}<span class="mut">Safety stock</span>${fmtN(m.ss)} CS</div><div class="tw"><table class="tbl" id="sapMd04"></table></div></div>`)}
    ${panel('s4', `<h3>Write-back queue</h3><span class="sub">Human-in-the-loop · audit-logged</span>`, `<div class="q" id="sapQ"></div>`)}
  </div>`;
  $('#sapLin').innerHTML = `<thead><tr><th>Domain</th><th>SAP object</th><th>Interface</th><th class="r">Rows (replica)</th><th>Fresh</th><th>Feeds</th></tr></thead><tbody>${s.lineage.map(l => `<tr><td><b>${l.domain}</b></td><td><code style="font-size:11px">${esc(l.objects)}</code></td><td class="mut" style="font-size:11px">${esc(l.api)}</td><td class="r">${fmtN(l.records)}</td><td class="mut">${l.fresh}</td><td style="font-size:11.5px">${l.feeds}</td></tr>`).join('')}</tbody>`;
  const draw = showAI => { $('#sapMd04').innerHTML = `<thead><tr><th>Date</th><th>MRP element</th><th>MRP element data</th><th class="r">Rec./reqd</th><th class="r">Avail. as-is</th>${showAI ? '<th class="r">Avail. AI plan</th><th>AI annotation</th>' : ''}</tr></thead><tbody>${m.rows.filter(r => showAI || r.kind !== 'ai').map(r => `<tr class="${r.kind === 'ai' ? 'aiw' : ''}"><td>${r.date}</td><td><b>${r.el}</b></td><td class="mut">${esc(r.data)}</td><td class="r">${r.kind === 'ai' ? '<span class="mut">—</span>' : (r.qty > 0 ? '+' : r.qty < 0 ? '−' : '') + fmtN(Math.abs(r.qty))}</td><td class="r ${r.flag === 'stockout' ? 'dn' : r.flag === 'below_ss' ? 'wn' : ''}">${r.kind === 'ai' ? '—' : (r.avail < 0 ? '<b>−' + fmtN(-r.avail) + '</b>' : fmtN(r.avail))}</td>${showAI ? `<td class="r"><b>${fmtN(r.avail_ai)}</b></td><td style="font-size:11px">${r.kind === 'ai' ? `<span class="pill p-ai">${ico('spark', 10)} ${esc(r.note.split(' · ')[0])}</span> ${esc(r.note.split(' · ').slice(1).join(' · '))}` : r.flag === 'stockout' ? '<span class="pill p-neg">stock-out as-is</span> ' + esc(r.note) : r.flag === 'below_ss' && r.el !== 'CusOrd' ? '<span class="pill p-warn">below safety stock</span> ' + esc(r.note) : esc(r.note)}</td>` : ''}</tr>`).join('')}</tbody>`; };
  draw(true); $('#sapAiTog').onchange = e => draw(e.target.checked);
  $('#sapQ').innerHTML = (s.queue.length ? s.queue.map(q => `<div class="qi"><b>${esc(q.title)}</b><div class="meta">${q.tcode} · ${q.api} · approver: ${q.approver}</div><details><summary class="mut" style="font-size:11px;cursor:pointer">Payload preview</summary><div class="code">${esc(JSON.stringify(q.preview, null, 2))}</div></details><div class="acts"><button class="btn pri sm" data-post="${q.id}">Approve &amp; post</button></div></div>`).join('') : '<div class="empty">No pending write-backs. Approve a recommendation on any screen to queue it here.</div>')
    + (s.done.length ? `<div class="mut" style="font-size:10.5px;margin-top:6px;letter-spacing:.06em">POSTED (SIMULATED)</div>` + s.done.map(q => `<div class="qi posted"><b>${esc(q.title)}</b><div class="meta">Document ${q.sap_document} · ${q.posted.slice(11)} · by ${q.approved_by}</div></div>`).join('') : '')
    + '<div class="mut" style="font-size:10.5px">Demo mode: write-backs are simulated and appended to data/audit.log with user, timestamp &amp; payload. No SAP system is changed.</div>';
}

/* ----------------------------------------------------------------------- 8. demo control */
function renderDemo(el, d) {
  const L = d.llm;
  el.innerHTML = `<div class="grid">
    ${panel('ai-card s6', aiHead('LLM gateway', 'Hugging Face model on this machine, with cached-answer fallback'), `<div id="dmLLM"></div>`)}
    ${panel('s6', `<h3>Scenario injector</h3><span class="sub">Trigger live events during the presentation</span><div class="right"><button class="btn sm ghost" id="dmReset">Reset demo</button></div>`, `<div id="dmScn"></div>`)}
    ${panel('s4', `<h3>Real-time stream &amp; narrative language</h3>`, `<div class="ctl"><div><label>POS events / sec <b id="vRate">${d.stream.rate}</b></label><input type="range" min="1" max="40" value="${d.stream.rate}" id="iRate"></div><div><label>AI narrative language (screens)</label><div class="seg" id="dmLang">${['en', 'es', 'pt'].map(l => `<button data-l="${l}" class="${S.lang === l ? 'on' : ''}">${l.toUpperCase()}</button>`).join('')}</div></div><div class="mut" style="font-size:11px">Copilot answers follow the language of each question.</div></div>`)}
    ${panel('s8', `<h3>Presenter script · ~18 min</h3><span class="sub">Suggested storyline for a commercial + supply-chain audience</span>`, `<div>${d.script.map((s, i) => `<div class="step"><span class="n">${i + 1}</span><div><b>${s.title}</b><div class="mut" style="font-size:11.5px">${s.text}</div></div><span class="t">${s.time}</span><button class="btn sm ghost" data-go="${s.goto}">Open</button></div>`).join('')}</div>`)}
  </div>`;
  drawLLM(L); drawScn(d.scenarios);
  $('#dmReset').onclick = async () => { await API.post('demo/reset'); toast('Demo reset to 27 Oct 2026 07:42', ''); };
  $('#iRate').oninput = e => { $('#vRate').textContent = e.target.value; API.post('demo/llm', { rate: +e.target.value }); };
  $$('#dmLang button').forEach(b => b.onclick = () => { S.lang = b.dataset.l; S.ovSummary = null; $$('#dmLang button').forEach(x => x.classList.toggle('on', x === b)); toast('Screen narratives will be written in ' + ({ en: 'English', es: 'Spanish', pt: 'Portuguese' })[S.lang], ''); });
  S.demoTimer = setInterval(async () => { if (S.cur !== 'demo') return; try { const x = await API.get('demo'); if (!$('#dmLLM')?.contains(document.activeElement)) drawLLM(x.llm); drawScn(x.scenarios); } catch (e) { } }, 2500);
}
function drawLLM(L) {
  const el = $('#dmLLM'); if (!el) return;
  const st = { ready: ['up', 'Loaded'], loading: ['wn', 'Loading…'], downloading: ['wn', 'Downloading from Hugging Face…'], not_loaded: ['mut', 'Not loaded'], missing: ['wn', 'Not downloaded'], error: ['dn', 'Error'] }[L.status] || ['mut', L.status];
  const total = L.stats.live + L.stats.cache + L.stats.template;
  el.innerHTML = `<div class="radio" id="dmMode">${[['auto', 'Auto (recommended)', 'Hugging Face model first. Reuses an identical earlier answer; falls back to the cache if the model is slow, missing or ungrounded.'], ['live', 'Live model only', 'Every narrative generated on this laptop. Shows real latency.'], ['cache', 'Cache only (offline-safe)', 'Never calls the model: cached answers, else a template built from the same facts. Instant.']].map(m => `<label data-m="${m[0]}" class="${L.mode === m[0] ? 'on' : ''}"><input type="radio" name="m" ${L.mode === m[0] ? 'checked' : ''}><div><b>${m[1]}</b><small>${m[2]}</small></div></label>`).join('')}</div>
    <div class="kv2" style="margin-top:12px">
      <span>Model</span><span><select class="sel sm" id="dmModel">${L.models.map(m => `<option value="${m.id}" ${m.id === L.model ? 'selected' : ''}>${esc(m.label)} · ${m.size_gb} GB · ${m.license}</option>`).join('')}</select></span>
      <span>Hugging Face repo</span><span><code>${esc(L.model)}</code></span>
      <span>Runtime</span><span>${L.runtime} · on-device, no cloud calls</span>
      <span>Status</span><span><span class="${st[0]}">● ${st[1]}</span>${L.load_seconds ? ` in ${L.load_seconds} s` : ''}${L.tps ? ` · ${L.tps} tok/s` : ''}${L.downloaded ? '' : ' · <span class="wn">not in local HF cache</span>'}${L.error && L.status !== 'ready' ? `<div class="dn" style="font-size:11px">${esc(L.error)}</div>` : ''}</span>
      <span>Answer cache</span><span>${fmtN(L.cache_entries)} grounded answers stored in data/llm_cache.json${L.prewarm.running ? ` · pre-warming ${L.prewarm.done}/${L.prewarm.total}` : ''}</span>
      <span>This session</span><span>${total} narratives · <span class="src-live">${L.stats.live} live</span> · <span class="src-cache">${L.stats.cache} cache</span> · <span class="src-template">${L.stats.template} template</span> · ${L.stats.rejected} rejected by grounding check</span>
      <span>Grounding guard</span><span>Every figure in a narrative must exist in the computed facts; otherwise it is regenerated or replaced.</span>
    </div>
    <div style="display:flex;gap:6px;margin-top:12px;flex-wrap:wrap"><button class="btn sm" id="dmLoad">${L.downloaded ? 'Load model' : 'Download &amp; load'}</button><button class="btn sm" id="dmWarm">Pre-warm answer cache</button><button class="btn sm" id="dmTest">Test generation</button></div>
    <div id="dmTestOut" class="narr md" style="margin-top:8px">${S.dmTest || ''}</div>
    ${L.log.length ? `<div class="mut" style="font-size:10.5px;margin:12px 0 4px;letter-spacing:.06em">RECENT REQUESTS</div><table class="tbl log"><thead><tr><th>Time</th><th>Task</th><th>Lang</th><th>Source</th><th class="r">ms</th></tr></thead><tbody>${L.log.slice(0, 8).map(x => `<tr><td>${x.ts}</td><td>${esc(x.task)}</td><td>${x.lang}</td><td class="src-${x.source}">${x.source}</td><td class="r">${fmtN(x.ms)}</td></tr>`).join('')}</tbody></table>` : ''}`;
  $$('#dmMode label').forEach(l => l.onclick = async () => { const x = await API.post('demo/llm', { mode: l.dataset.m }); drawLLM(x); toast('LLM mode: ' + l.querySelector('b').textContent, ''); });
  $('#dmModel').onchange = async e => { const x = await API.post('demo/llm', { model: e.target.value, download: true }); drawLLM(x); toast('Switching model · downloads once from Hugging Face if needed', ''); };
  $('#dmLoad').onclick = async () => { drawLLM(await API.post('demo/llm', { load: true, download: true })); };
  $('#dmWarm').onclick = async () => { await API.post('demo/prewarm'); toast('Pre-warming narratives & Copilot answers for the current scenario', ''); };
  $('#dmTest').onclick = async () => { $('#dmTestOut').innerHTML = shimmer; const r = await API.post('demo/llm/test'); S.dmTest = md(r.text) + `<div class="mut" style="font-size:10.5px">${fmtN(r.ms)} ms · source: <span class="src-${r.source}">${r.source}</span></div>`; if ($('#dmTestOut')) $('#dmTestOut').innerHTML = S.dmTest; };
}
function drawScn(list) {
  const el = $('#dmScn'); if (!el) return;
  el.innerHTML = list.map(s => `<div class="scn ${s.active ? 'on' : ''}"><span class="dot ${s.active ? 'neg blink' : 'warn'}"></span><div><b>${s.label}</b><div class="d">${s.desc}</div></div>${s.active ? `<button class="btn sm ghost" data-clear="${s.id}">Clear</button>` : `<button class="btn sm" data-inject="${s.id}">Inject</button>`}</div>`).join('');
}
async function inject(id) { try { await API.post('demo/inject/' + id); } catch (e) { toast('Could not inject: ' + esc(e.message), 'neg'); } }

/* ======================================================================= copilot */
function cpAdd(html) { const b = $('#cpBody'); b.insertAdjacentHTML('beforeend', html); b.scrollTop = b.scrollHeight; }
async function ask(q) {
  cpAdd(`<div class="msg u">${esc(q)}</div><div class="msg a typing" id="typing"><span></span><span></span><span></span></div>`);
  try {
    const a = await API.post('copilot', { q });
    $('#typing')?.remove();
    const table = a.table ? `<div class="table-wrap"><table><tr>${a.table.cols.map(c => `<th>${c}</th>`).join('')}</tr>${a.table.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table></div>` : '';
    const code = a.code ? `<div class="code" style="margin-top:6px">${esc(a.code)}</div>` : '';
    const act = a.rec_key ? `<div style="margin-top:8px"><button class="btn pri sm" data-rec="${a.rec_key}">Approve draft → write-back queue</button></div>` : '';
    cpAdd(`<div class="msg a"><div class="mh"><span class="ai-ic">${ico('spark', 13)}</span><b style="font-size:12px">CABI</b><span class="pill" style="margin-left:auto">${a.lang.toUpperCase()}</span></div><div class="md">${md(a.text)}</div>${table}${code}${act}${a.sources.length ? `<div class="src-chips">${a.sources.map(s => `<span class="pill">${esc(s)}</span>`).join('')}</div>` : ''}<details><summary>Agent trace · ${a.trace.length} steps</summary><ol>${a.trace.map(t => `<li>${esc(t)}</li>`).join('')}</ol></details></div>`);
  } catch (e) { $('#typing')?.remove(); cpAdd(`<div class="msg a">Sorry, that failed: ${esc(e.message)}</div>`); }
}
async function initCopilot() {
  cpAdd(`<div class="msg a"><div class="mh"><span class="ai-ic">${ico('spark', 13)}</span><b style="font-size:12px">CABI</b></div><div class="md"><p>Hi! I can diagnose share moves, scan stock-out risk, simulate cost shocks, explain forecasts and route risks, and draft SAP actions for approval. Ask in English, Español or Português.</p></div></div>`);
  try { const sug = await API.get('copilot/suggestions'); $('#cpSugg').innerHTML = sug.map(q => `<span class="chip">${esc(q)}</span>`).join(''); $$('#cpSugg .chip').forEach(c => c.onclick = () => ask(c.textContent)); } catch (e) { }
  const send = () => { const v = $('#cpIn').value.trim(); if (v) { ask(v); $('#cpIn').value = ''; } };
  $('#cpSend').onclick = send; $('#cpIn').onkeydown = e => { if (e.key === 'Enter') send(); };
  $('#fab').onclick = () => $('#copilot').classList.add('open'); $('#cpClose').onclick = () => $('#copilot').classList.remove('open');
}

/* ======================================================================= live stream + ticker */
const TK = { queue: [], x: 0, last: performance.now() };
function tickerLoop(t) {
  const dt = Math.min(0.1, (t - TK.last) / 1000); TK.last = t;
  const track = $('#track'), wrap = $('#trackWrap');
  TK.x -= 42 * dt;
  const first = track.firstElementChild;
  if (first) { const w = first.offsetWidth + 28; if (-TK.x > w) { track.removeChild(first); TK.x += w; } }
  while (track.scrollWidth + TK.x < wrap.offsetWidth * 1.5 && TK.queue.length) { const s = document.createElement('span'); s.innerHTML = TK.queue.shift(); track.appendChild(s); }
  track.style.transform = `translateX(${TK.x}px)`;
  requestAnimationFrame(tickerLoop);
}
function connectStream() {
  const es = new EventSource('/api/stream');
  es.addEventListener('tick', e => {
    const d = JSON.parse(e.data);
    $('#liveTx').textContent = fmtN(d.tx_per_min);
    S.pulse.push(d.units_per_min); if (S.pulse.length > 90) S.pulse.shift();
    if (S.cur === 'overview') renderPulse();
    if (TK.queue.length < 30) d.events.slice(0, 3).forEach(x => TK.queue.push(`${S.meta?.clock || ''} · POS · ${esc(x.store)} · ${esc(x.city)} · <b>${esc(x.sku)}</b> × ${x.qty} · ${x.ccy} ${fmtN(x.value, x.value < 100 ? 2 : 0)}`));
  });
  es.addEventListener('state', async e => {
    const d = JSON.parse(e.data);
    if (S.version === -1) { S.version = d.version; return; }
    if (d.version === S.version) return;
    S.version = d.version; S.ovSummary = null;
    const last = d.events[d.events.length - 1];
    if (last && d.active.includes(last.name)) { toast(`Scenario live: <b>${esc(last.label)}</b>. Models, alerts and recommendations recomputed`, 'neg'); TK.queue.unshift(`<span class="al">ALERT · ${esc(last.label)}</span>`); }
    await refreshMeta();
    go(S.cur, { keepScroll: true });
  });
}
async function refreshMeta() {
  try {
    const m = await API.get('meta'); S.meta = m;
    const dt = new Date(m.today + 'T12:00:00'); S.meta.today_label = dt.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short', year: 'numeric' }) + ' · Week 44';
    $('#coName').textContent = `${m.company.name} · ${m.company.region}`; $('#coTag').textContent = m.company.tagline;
    if (m.counts) Object.entries(m.counts).forEach(([k, v]) => { const c = $(`[data-cnt="${k}"]`); if (c) c.textContent = v || ''; });
    const n = m.active.length; $('#scnDot').className = 'dot ' + (n ? 'neg blink' : '');
    $('#scnTitle').textContent = n ? `${n} live scenario${n > 1 ? 's' : ''}` : 'No live scenarios';
    $('#scnSub').textContent = n ? m.active.map(a => m.scenarios[a].label).join(' · ') : 'network nominal';
    if (S.cur === 'overview') $('#pgSub').innerHTML = SCREENS.overview.sub();
    return m;
  } catch (e) { return null; }
}

/* ======================================================================= boot */
document.addEventListener('click', e => {
  const g = e.target.closest('[data-go]'); if (g) { go(g.dataset.go); return; }
  const r = e.target.closest('[data-rec]'); if (r) { approveRec(r.dataset.rec, r); return; }
  const p = e.target.closest('[data-post]'); if (p) { API.post(`sap/queue/${p.dataset.post}/approve`).then(x => { toast(`Posted to SAP mock replica · document <b>${x.sap_document}</b> · audit-logged`, ''); refreshMeta(); go('sap', { keepScroll: true }); }); return; }
  const i = e.target.closest('[data-inject]'); if (i) { inject(i.dataset.inject); return; }
  const c = e.target.closest('[data-clear]'); if (c) { API.post('demo/clear/' + c.dataset.clear); return; }
});
$$('.nav').forEach(n => n.onclick = () => go(n.dataset.s));
$('#themeBtn').onclick = () => { const d = document.documentElement; d.dataset.theme = d.dataset.theme === 'dark' ? 'light' : 'dark'; try { localStorage.setItem('cabi-theme', d.dataset.theme); } catch (e) { } rerender(); };
try { const t = localStorage.getItem('cabi-theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) { }
let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(rerender, 150); });
(async function boot() {
  for (let i = 0; i < 240; i++) {
    const m = await refreshMeta();
    if (m && m.ready) break;
    if (m && m.boot_error) { $('#bootMsg').textContent = 'Startup error: ' + m.boot_error; return; }
    await new Promise(r => setTimeout(r, 500));
  }
  $('#boot').classList.add('gone');
  connectStream(); requestAnimationFrame(tickerLoop); initCopilot();
  await go('overview');
  API.get('overview').then(d => S.data.overview = d).catch(() => { });
})();
