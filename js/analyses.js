// « Sous le capot » : quatre analyses interactives, une visible à la fois. Données d'exemple.
// Les modèles sont regroupés ici pour être remplacés par les vrais (ex. le modèle chaleur en cours).

/* ---------- Modèles d'exemple ---------- */
const MP = 295;                                                                      // allure marathon : 4:55 /km
const heatBpm = (T) => (T <= 10 ? 0 : 0.2 * Math.pow(T - 10, 1.45));                 // coût de la chaleur, bpm à allure égale
const BPM_TO_S = 0.85;                                                               // ≈ s/km perdues par battement
const runKmh = (g) => Math.max(1.5, 10.2 - 0.43 * g);                                // vitesse en courant, FC 150, pente g %
const walkKmh = (g) => Math.max(2.5, 5.8 - 0.064 * g);                               // vitesse en marchant, même FC
const WALK_AT = 12;                                                                  // croisement des deux : ton seuil
const onsetKm = (p) => Math.max(18, Math.min(45, 34 + (p - MP) * 0.65));             // km où la foulée lâche, selon l'allure

/* ---------- Outils ---------- */
const NS = 'http://www.w3.org/2000/svg';
const mk = (t, a = {}) => { const n = document.createElementNS(NS, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
const $ = (id) => document.getElementById(id);
const fr = (n, d = 1) => n.toFixed(d).replace('.', ',');
const pace = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const RED = '#F0443E', GRID = 'rgba(255,255,255,.08)', TXT = { fill: '#7A7A7A', 'font-size': 11, 'font-family': 'IBM Plex Mono, monospace' };
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function gauss(r) { let u = 0, v = 0; while (!u) u = r(); while (!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

// Repère commun : grille, graduations, titres d'axes.
function frame(host, o) {
  host.replaceChildren();
  const W = host.clientWidth, H = host.clientHeight, L = { l: 48, r: 14, t: 22, b: 36 };
  const svg = mk('svg', { viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true' });
  host.append(svg);
  const x = (v) => L.l + (v - o.x0) / (o.x1 - o.x0) * (W - L.l - L.r);
  const y = (v) => H - L.b - (v - o.y0) / (o.y1 - o.y0) * (H - L.t - L.b);
  for (const v of o.yt) {
    svg.append(mk('line', { x1: L.l, x2: W - L.r, y1: y(v), y2: y(v), stroke: GRID }));
    const t = mk('text', { ...TXT, x: L.l - 10, y: y(v) + 4, 'text-anchor': 'end' }); t.textContent = o.yf ? o.yf(v) : v; svg.append(t);
  }
  for (const v of o.xt) { const t = mk('text', { ...TXT, x: x(v), y: H - 12, 'text-anchor': 'middle' }); t.textContent = o.xf ? o.xf(v) : v; svg.append(t); }
  const yl = mk('text', { ...TXT, x: 0, y: 10 }); yl.textContent = o.yl; svg.append(yl);
  const xl = mk('text', { ...TXT, x: W - L.r, y: y(o.y0) - 8, 'text-anchor': 'end' }); xl.textContent = o.xl; svg.append(xl);
  return { svg, x, y, W, H, L };
}
const line = (pts, f) => pts.map((p, i) => (i ? 'L' : 'M') + f.x(p[0]).toFixed(1) + ' ' + f.y(p[1]).toFixed(1)).join('');
const curve = (fn, a, b, f, n = 80) => line(Array.from({ length: n + 1 }, (_, i) => { const v = a + (b - a) * i / n; return [v, fn(v)]; }), f);

/* ---------- 1. Chaleur ---------- */
function heat() {
  const host = $('heatChart'), slider = $('heatT'), r = rng(4);
  const dots = Array.from({ length: 90 }, () => { const T = r() * 33; return [T, heatBpm(T) + gauss(r) * 2.2]; });
  function draw() {
    const T = +slider.value, b = heatBpm(T), s = b * BPM_TO_S, mar = s * 42.195;
    const f = frame(host, { x0: 0, x1: 35, y0: -6, y1: 24, xt: [0, 10, 20, 30], xf: (v) => `${v} °C`, yt: [0, 10, 20], yf: (v) => `+${v}`, yl: 'bpm en plus, à 4:55 /km', xl: 'température' });
    for (const [t, v] of dots) f.svg.append(mk('circle', { cx: f.x(t), cy: f.y(v), r: 2.6, fill: '#fff', opacity: 0.45 }));
    f.svg.append(mk('path', { d: curve(heatBpm, 0, 35, f), fill: 'none', stroke: '#fff', 'stroke-width': 2.5 }));
    f.svg.append(mk('line', { x1: f.x(T), x2: f.x(T), y1: f.L.t, y2: f.H - f.L.b, stroke: '#fff', 'stroke-dasharray': '2 4', opacity: 0.7 }));
    f.svg.append(mk('circle', { cx: f.x(T), cy: f.y(b), r: 6, fill: RED }));
    $('heatTv').textContent = `${T} °C`;
    $('heatBig').textContent = b < 0.5 ? 'Aucun coût' : `+${Math.round(b)} bpm`;
    $('heatRead').textContent = b < 0.5 ? 'En dessous de 10 °C, la chaleur ne te coûte rien.' : `≈ +${Math.round(s)} s/km à effort égal · +${Math.floor(mar / 60)} min ${String(Math.round(mar % 60)).padStart(2, '0')} sur un marathon`;
  }
  slider.addEventListener('input', draw);
  return draw;
}

/* ---------- 2. Marche ou course ---------- */
function walk() {
  const host = $('walkChart'), slider = $('walkG'), r = rng(8);
  const dots = [
    ...Array.from({ length: 70 }, () => { const g = r() * 16; return [g, runKmh(g) + gauss(r) * 0.45, 0]; }),
    ...Array.from({ length: 50 }, () => { const g = 6 + r() * 24; return [g, walkKmh(g) + gauss(r) * 0.3, 1]; }),
  ];
  function draw() {
    const g = +slider.value, run = runKmh(g), wk = walkKmh(g), walking = g >= WALK_AT;
    const f = frame(host, { x0: 0, x1: 30, y0: 0, y1: 12, xt: [0, 10, 20, 30], xf: (v) => `${v} %`, yt: [0, 4, 8, 12], yl: 'km/h à FC 150', xl: 'pente' });
    f.svg.append(mk('rect', { x: f.x(WALK_AT), y: f.L.t, width: f.x(30) - f.x(WALK_AT), height: f.H - f.L.t - f.L.b, fill: RED, opacity: 0.08 }));
    const t = mk('text', { ...TXT, x: f.x(WALK_AT) + 8, y: f.L.t + 14, fill: RED }); t.textContent = `tu marches · seuil ${WALK_AT} %`; f.svg.append(t);
    for (const [x, v, w] of dots) f.svg.append(mk('circle', { cx: f.x(x), cy: f.y(v), r: 2.6, fill: w ? RED : '#fff', opacity: 0.55 }));
    f.svg.append(mk('path', { d: curve(runKmh, 0, 30, f), fill: 'none', stroke: '#fff', 'stroke-width': 2.5 }));
    f.svg.append(mk('path', { d: curve(walkKmh, 0, 30, f), fill: 'none', stroke: RED, 'stroke-width': 2.5 }));
    const lr = mk('text', { ...TXT, x: f.x(2), y: f.y(runKmh(2)) - 10, fill: '#fff' }); lr.textContent = 'en courant'; f.svg.append(lr);
    const lw = mk('text', { ...TXT, x: f.x(24), y: f.y(walkKmh(24)) - 10, fill: RED }); lw.textContent = 'en marchant'; f.svg.append(lw);
    f.svg.append(mk('line', { x1: f.x(g), x2: f.x(g), y1: f.L.t, y2: f.H - f.L.b, stroke: '#fff', 'stroke-dasharray': '2 4', opacity: 0.7 }));
    f.svg.append(mk('circle', { cx: f.x(g), cy: f.y(Math.max(run, wk)), r: 6, fill: walking ? RED : '#fff' }));
    $('walkGv').textContent = `${g} %`;
    const big = $('walkBig'); big.textContent = walking ? 'Tu marches' : 'Tu cours'; big.classList.toggle('red', walking);
    $('walkRead').textContent = `À ${g} % et 150 bpm : ${fr(wk)} km/h en marchant, ${fr(run)} km/h en courant.${walking ? ' Bâtons sortis.' : ''}`;
  }
  slider.addEventListener('input', draw);
  return draw;
}

/* ---------- 3. Allure marathon : séances corrigées ---------- */
function mp() {
  const host = $('mpChart'), r = rng(15), on = new Set();
  const S = Array.from({ length: 48 }, () => {
    const w = r() * 16, T = 4 + r() * 24, dplus = r() * 14, atl = 0.8 + r() * 0.6;
    return { w, T, dplus, atl, trend: 158 - 0.45 * w, temp: heatBpm(T), slope: dplus * 0.35, load: (atl - 1) * 12, noise: gauss(r) * 1.4 };
  });
  const val = (s) => s.trend + s.noise + (on.has('temp') ? heatBpm(15) : s.temp) + (on.has('slope') ? 0 : s.slope) + (on.has('load') ? 0 : s.load);
  function draw() {
    const pts = S.map((s) => [s.w, val(s)]);
    const n = pts.length, mx = pts.reduce((a, p) => a + p[0], 0) / n, my = pts.reduce((a, p) => a + p[1], 0) / n;
    const b = pts.reduce((a, p) => a + (p[0] - mx) * (p[1] - my), 0) / pts.reduce((a, p) => a + (p[0] - mx) ** 2, 0), a0 = my - b * mx;
    const sd = Math.sqrt(pts.reduce((a, p) => a + (p[1] - (a0 + b * p[0])) ** 2, 0) / (n - 2));
    const f = frame(host, { x0: 0, x1: 16, y0: 140, y1: 180, xt: [0, 4, 8, 12, 16], xf: (v) => `S${v}`, yt: [145, 155, 165, 175], yl: 'FC à 4:55 /km', xl: 'semaines' });
    f.svg.append(mk('path', { d: line([[0, a0], [16, a0 + b * 16]], f), stroke: '#fff', 'stroke-width': 2, opacity: 0.9 }));
    S.forEach((s, i) => {
      const c = mk('circle', { cx: f.x(s.w), cy: f.y(pts[i][1]), r: 4, fill: '#fff', opacity: 0.7 });
      const t = mk('title'); t.textContent = `Semaine ${Math.round(s.w)} · ${Math.round(s.T)} °C · ${Math.round(s.dplus)} m D+/km · charge aiguë ${fr(s.atl)}`; c.append(t);
      f.svg.append(c);
    });
    $('mpBig').textContent = `± ${fr(sd)} bpm`;
    $('mpRead').textContent = on.size === 3
      ? `Une fois tout retiré, il reste ta forme : ${fr(b * 4)} bpm par mois à la même allure.`
      : `Dispersion des séances à 4:55 /km. Retire les effets un par un : il reste ta vraie forme.`;
  }
  document.querySelectorAll('[data-mp]').forEach((btn) => btn.addEventListener('click', () => {
    const k = btn.dataset.mp, now = !on.has(k);
    if (now) on.add(k); else on.delete(k);
    btn.setAttribute('aria-pressed', String(now)); draw();
  }));
  return draw;
}

/* ---------- 4. Durabilité & foulée ---------- */
function dur() {
  const host = $('durChart'), slider = $('durP');
  function draw() {
    const p = +slider.value, k0 = onsetKm(p);
    const fc = (k) => 0.12 * k + (k > k0 ? Math.pow(k - k0, 1.5) * 0.2 : 0);       // dérive de la FC, %
    const cad = (k) => -0.03 * k - (k > k0 ? (k - k0) * 0.45 : 0);                    // cadence, %
    const y0 = Math.min(-8, Math.floor(cad(42.2) - 2)), y1 = Math.max(12, Math.ceil(fc(42.2) + 2));
    const f = frame(host, { x0: 0, x1: 42.2, y0, y1, xt: [0, 10, 20, 30, 40], xf: (v) => `${v}`, yt: Array.from({ length: Math.floor(y1 / 5) - Math.ceil(y0 / 5) + 1 }, (_, i) => (Math.ceil(y0 / 5) + i) * 5), yf: (v) => `${v > 0 ? '+' : ''}${v} %`, yl: 'écart au début de course', xl: 'km' });
    if (k0 < 42.2) f.svg.append(mk('rect', { x: f.x(k0), y: f.L.t, width: f.x(42.2) - f.x(k0), height: f.H - f.L.t - f.L.b, fill: RED, opacity: 0.08 }));
    f.svg.append(mk('path', { d: curve(fc, 0, 42.2, f), fill: 'none', stroke: '#fff', 'stroke-width': 2.5 }));
    f.svg.append(mk('path', { d: curve(cad, 0, 42.2, f), fill: 'none', stroke: '#8C8C8C', 'stroke-width': 2, 'stroke-dasharray': '6 4' }));
    const a = mk('text', { ...TXT, x: f.x(3), y: f.y(fc(3)) - 10, fill: '#fff' }); a.textContent = 'fréquence cardiaque'; f.svg.append(a);
    const c = mk('text', { ...TXT, x: f.x(3), y: f.y(cad(3)) + 18 }); c.textContent = 'cadence'; f.svg.append(c);
    if (k0 < 42.2) {
      f.svg.append(mk('line', { x1: f.x(k0), x2: f.x(k0), y1: f.L.t, y2: f.H - f.L.b, stroke: RED, 'stroke-width': 1.5 }));
      const t = mk('text', { ...TXT, x: f.x(k0) + 8, y: f.L.t + 14, fill: RED }); t.textContent = `ta foulée lâche · km ${Math.round(k0)}`; f.svg.append(t);
    }
    $('durPv').textContent = `${pace(p)} /km`;
    const big = $('durBig'); big.textContent = k0 >= 42.2 ? 'Jusqu’au bout' : `km ${Math.round(k0)}`; big.classList.toggle('red', k0 < 35);
    $('durRead').textContent = k0 >= 42.2
      ? `À ${pace(p)} /km, ta foulée tient jusqu'à l'arrivée.`
      : `À ${pace(p)} /km, ta foulée tient jusqu'au km ${Math.round(k0)}. À l'arrivée : cadence ${fr(cad(42.2))} %, FC +${fr(fc(42.2))} %.`;
  }
  slider.addEventListener('input', draw);
  return draw;
}

/* ---------- Onglets : on ne dessine que l'analyse visible ---------- */
export function initAnalyses() {
  const draws = { heat: heat(), walk: walk(), mp: mp(), dur: dur() };
  const tabs = Array.from(document.querySelectorAll('.lab-tabs [role="tab"]'));
  let current = 'heat';
  const show = (tab) => {
    tabs.forEach((t) => { const on = t === tab; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; $(t.getAttribute('aria-controls')).hidden = !on; });
    current = tab.dataset.k; draws[current]();
  };
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => show(t));
    t.addEventListener('keydown', (e) => {
      const j = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length : -1;
      if (j < 0) return;
      e.preventDefault(); tabs[j].focus(); show(tabs[j]);
    });
  });
  new ResizeObserver(() => draws[current]()).observe($('lab'));
  draws.heat();
}
