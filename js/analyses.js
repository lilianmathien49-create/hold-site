// « Sous le capot » : quatre analyses interactives, une visible à la fois. Données d'exemple.
// Les modèles sont regroupés ici pour être remplacés par les vrais (ex. le modèle chaleur en cours).

/* ---------- Modèles d'exemple ---------- */
const MP = 295;                                                                      // allure marathon : 4:55 /km
const heatBpm = (T) => (T <= 10 ? 0 : 0.2 * Math.pow(T - 10, 1.45));                 // coût de la chaleur, bpm à allure égale
const BPM_TO_S = 0.85;                                                               // ≈ s/km perdues par battement
// Seuil de marche : régression logistique sur 39 959 blocs de 15 s (150 sorties).
// La pente où la probabilité de marcher atteint 50 % baisse avec le temps écoulé.
const THR = (t) => 8.8 - 3.1 * t / 240;                                              // seuil (%) après t minutes
const THR_LO = (t) => THR(t) - (0.75 + 4.05 * t / 240);                              // borne basse IC 95 %
const THR_HI = (t) => THR(t) + (1.92 - 0.82 * t / 240);                              // borne haute IC 95 %
const K = 0.27;                                                                      // pente de la logistique
const pWalk = (g, thr) => 100 / (1 + Math.exp(-K * (g - thr)));                      // probabilité de marcher, en %
const FINIEL = 12.6, GIOVANELLI = 27;                                                // repères de la littérature
// Part de marche observée par tranche de pente (taille = nombre de blocs).
const OBS = [[-3, 11, 9], [-0.7, 10.5, 6], [0.7, 13, 6], [3, 19.5, 6], [5, 33, 7], [6.8, 43, 5],
  [8.8, 58, 5], [10.8, 73, 4.5], [12.8, 79, 4], [15, 89, 3.5], [17, 93.5, 3], [19, 96, 3], [21, 98, 2.8], [23, 99, 2.6], [25, 99.5, 2.5]];
const onsetKm = (p) => Math.max(18, Math.min(45, 34 + (p - MP) * 0.65));             // km où la foulée lâche, selon l'allure

/* ---------- Outils ---------- */
const NS = 'http://www.w3.org/2000/svg';
const mk = (t, a = {}) => { const n = document.createElementNS(NS, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
const $ = (id) => document.getElementById(id);
const fr = (n, d = 1) => n.toFixed(d).replace('.', ',');
const pace = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
// Les couleurs viennent des jetons CSS : la section peut être claire ou sombre,
// les tracés suivent sans qu'aucune valeur ne soit écrite en dur ici.
let RED = '#E04038', GRID = 'rgba(21,23,26,.10)', INK = '#15171A', SOFT = '#595D64';
let TXT = { fill: '#666B72', 'font-size': 11, 'font-family': 'IBM Plex Mono, monospace' };
function syncPalette(host) {
  const s = getComputedStyle(host), get = (n, fb) => s.getPropertyValue(n).trim() || fb;
  RED = get('--mark', RED); GRID = get('--grid', GRID);
  INK = get('--text', INK); SOFT = get('--muted', SOFT);
  TXT = { ...TXT, fill: get('--dim', TXT.fill) };
}
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function gauss(r) { let u = 0, v = 0; while (!u) u = r(); while (!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

// Repère commun : grille, graduations, titres d'axes.
function frame(host, o) {
  syncPalette(host);
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

// Étiquette posée à côté d'un repère vertical. Le SVG est en overflow visible : sur écran
// étroit une étiquette ancrée à droite sortirait du cadre, donc on la bascule à gauche.
function annotate(f, xv, yPx, txt, color) {
  const w = txt.length * 6.6, px = f.x(xv), flip = px + 8 + w > f.W - f.L.r;
  const t = mk('text', { ...TXT, x: px + (flip ? -8 : 8), y: yPx, fill: color, 'text-anchor': flip ? 'end' : 'start' });
  t.textContent = txt;
  f.svg.append(t);
}
const curve = (fn, a, b, f, n = 80) => line(Array.from({ length: n + 1 }, (_, i) => { const v = a + (b - a) * i / n; return [v, fn(v)]; }), f);

// Bande d'intervalle de confiance : on longe la borne haute, puis on revient par la basse.
function band(f, a, b, hi, lo, n = 60) {
  const up = [], dn = [];
  for (let i = 0; i <= n; i++) { const v = a + (b - a) * i / n; up.push([v, hi(v)]); dn.push([v, lo(v)]); }
  return line(up, f) + 'L' + line(dn.reverse(), f).slice(1) + 'Z';
}

/* ---------- 1. Chaleur ---------- */
function heat() {
  const host = $('heatChart'), slider = $('heatT'), r = rng(4);
  const dots = Array.from({ length: 90 }, () => { const T = r() * 33; return [T, heatBpm(T) + gauss(r) * 2.2]; });
  function draw() {
    const T = +slider.value, b = heatBpm(T), s = b * BPM_TO_S, mar = s * 42.195;
    const f = frame(host, { x0: 0, x1: 35, y0: -6, y1: 24, xt: [0, 10, 20, 30], xf: (v) => `${v} °C`, yt: [0, 10, 20], yf: (v) => `+${v}`, yl: 'bpm en plus, à 4:55 /km', xl: 'température' });
    for (const [t, v] of dots) f.svg.append(mk('circle', { cx: f.x(t), cy: f.y(v), r: 2.6, fill: INK, opacity: 0.45 }));
    f.svg.append(mk('path', { d: curve(heatBpm, 0, 35, f), fill: 'none', stroke: INK, 'stroke-width': 2.5 }));
    f.svg.append(mk('line', { x1: f.x(T), x2: f.x(T), y1: f.L.t, y2: f.H - f.L.b, stroke: INK, 'stroke-dasharray': '2 4', opacity: 0.7 }));
    f.svg.append(mk('circle', { cx: f.x(T), cy: f.y(b), r: 6, fill: RED }));
    $('heatTv').textContent = `${T} °C`;
    $('heatBig').textContent = b < 0.5 ? 'Aucun coût' : `+${Math.round(b)} bpm`;
    $('heatRead').textContent = b < 0.5 ? 'En dessous de 10 °C, la chaleur ne te coûte rien.' : `≈ +${Math.round(s)} s/km à effort égal · +${Math.floor(mar / 60)} min ${String(Math.round(mar % 60)).padStart(2, '0')} sur un marathon`;
  }
  slider.addEventListener('input', draw);
  return draw;
}

/* ---------- 2. Seuil de marche : la logistique ---------- */
function walk() {
  const host = $('walkChart'), slider = $('walkT');
  function draw() {
    const t = +slider.value, thr = THR(t), lo = THR_LO(t), hi = THR_HI(t);
    const f = frame(host, { x0: -5, x1: 30, y0: 0, y1: 100, xt: [0, 10, 20, 30], xf: (v) => `${v} %`,
      yt: [0, 25, 50, 75, 100], yf: (v) => `${v}`, yl: 'probabilité de marcher (%)', xl: 'pente sur 100 m' });

    // IC 95 % : la logistique décalée aux deux bornes du seuil.
    f.svg.append(mk('path', { d: band(f, -5, 30, (g) => pWalk(g, lo), (g) => pWalk(g, hi)), fill: INK, opacity: 0.08, stroke: 'none' }));

    // Repères de la littérature, en retrait. Étagés en hauteur : côte à côte ils se chevauchent.
    for (const [v, txt, dy] of [[FINIEL, 'Finiel 2026', 10], [GIOVANELLI, 'Giovanelli', 28]]) {
      f.svg.append(mk('line', { x1: f.x(v), x2: f.x(v), y1: f.L.t, y2: f.H - f.L.b, stroke: INK, 'stroke-dasharray': '1 5', opacity: 0.3 }));
      annotate(f, v, f.H - f.L.b - dy, txt, TXT.fill);
    }

    // La barre des 50 %, puis les blocs observés, puis la courbe.
    f.svg.append(mk('line', { x1: f.L.l, x2: f.W - f.L.r, y1: f.y(50), y2: f.y(50), stroke: INK, 'stroke-dasharray': '2 4', opacity: 0.35 }));
    for (const [g, p, w] of OBS) f.svg.append(mk('circle', { cx: f.x(g), cy: f.y(p), r: w * 0.62, fill: INK, opacity: 0.4 }));
    f.svg.append(mk('path', { d: curve((g) => pWalk(g, thr), -5, 30, f), fill: 'none', stroke: RED, 'stroke-width': 2.5 }));
    f.svg.append(mk('line', { x1: f.x(thr), x2: f.x(thr), y1: f.y(50), y2: f.H - f.L.b, stroke: RED, 'stroke-width': 1.5 }));
    f.svg.append(mk('circle', { cx: f.x(thr), cy: f.y(50), r: 6, fill: RED }));
    annotate(f, thr, f.L.t + 14, `seuil 50 % · ${fr(thr)} %`, RED);

    $('walkTv').textContent = t === 0 ? 'au départ' : `${t} min`;
    $('walkBig').textContent = `${fr(thr)} %`;
    $('walkRead').textContent = `IC 95 % ${fr(lo)} – ${fr(hi)} %. Au-delà de cette pente, tu as plus d'une chance sur deux de marcher${t >= 150 ? ' — et peu de sorties dépassent 3 h, donc l\'intervalle s\'élargit.' : '.'}`;
  }
  slider.addEventListener('input', draw);
  return draw;
}

/* ---------- 3. La fatigue abaisse le seuil ---------- */
function fatigue() {
  const host = $('fatChart'), slider = $('fatT');
  function draw() {
    const t = +slider.value, thr = THR(t), drop = THR(0) - thr;
    const f = frame(host, { x0: 0, x1: 240, y0: 0, y1: 12, xt: [0, 60, 120, 180, 240], xf: (v) => `${v}`,
      yt: [0, 4, 8, 12], yf: (v) => `${v} %`, yl: 'pente de passage à la marche', xl: 'minutes de course' });

    f.svg.append(mk('path', { d: band(f, 0, 240, THR_HI, THR_LO), fill: RED, opacity: 0.12, stroke: 'none' }));
    f.svg.append(mk('path', { d: curve(THR, 0, 240, f), fill: 'none', stroke: RED, 'stroke-width': 2.5 }));

    // Les quatre jalons de la sortie type.
    for (const m of [30, 60, 120, 180]) {
      f.svg.append(mk('circle', { cx: f.x(m), cy: f.y(THR(m)), r: 3, fill: INK, opacity: 0.5 }));
      const lbl = mk('text', { ...TXT, x: f.x(m), y: f.y(THR(m)) - 12, 'text-anchor': 'middle' });
      lbl.textContent = `${fr(THR(m))} %`; f.svg.append(lbl);
    }

    f.svg.append(mk('line', { x1: f.x(t), x2: f.x(t), y1: f.L.t, y2: f.H - f.L.b, stroke: INK, 'stroke-dasharray': '2 4', opacity: 0.7 }));
    f.svg.append(mk('circle', { cx: f.x(t), cy: f.y(thr), r: 6, fill: RED }));

    $('fatTv').textContent = t === 0 ? 'au départ' : `${t} min`;
    $('fatBig').textContent = drop < 0.05 ? `${fr(thr)} %` : `− ${fr(drop)} pt`;
    $('fatRead').textContent = drop < 0.05
      ? `Frais, tu tiens la course jusqu'à ${fr(thr)} % de pente.`
      : `Après ${t} min, ton seuil est passé de ${fr(THR(0))} % à ${fr(thr)} %. La même côte se marche, alors qu'elle se courait au départ.`;
  }
  slider.addEventListener('input', draw);
  return draw;
}

/* ---------- 4. Durabilité ---------- */

/* ---------- Onglets : on ne dessine que l'analyse visible ---------- */
export function initAnalyses() {
  // Chaque analyse est montée séparément : si le HTML et ce fichier se retrouvent
  // désynchronisés (un cache qui mélange deux versions), seule l'analyse concernée
  // tombe, les deux autres restent affichables.
  const build = (k, fn) => { try { return fn(); } catch (e) { console.error(`Hold : analyse « ${k} » indisponible`, e); return null; } };
  const draws = { heat: build('heat', heat), walk: build('walk', walk), fat: build('fat', fatigue) };
  const tabs = Array.from(document.querySelectorAll('.lab-tabs [role="tab"]'));
  // L'onglet de départ est celui que le HTML déclare ouvert : réordonner les
  // onglets ne doit pas obliger à retoucher ce fichier.
  const first = tabs.find((t) => t.getAttribute('aria-selected') === 'true') || tabs[0];
  let current = first?.dataset.k;
  const show = (tab) => {
    tabs.forEach((t) => { const on = t === tab; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; $(t.getAttribute('aria-controls')).hidden = !on; });
    current = tab.dataset.k; draws[current]?.();
  };
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => show(t));
    t.addEventListener('keydown', (e) => {
      const j = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length : -1;
      if (j < 0) return;
      e.preventDefault(); tabs[j].focus(); show(tabs[j]);
    });
  });
  new ResizeObserver(() => draws[current]?.()).observe($('lab'));
  draws[current]?.();
}
