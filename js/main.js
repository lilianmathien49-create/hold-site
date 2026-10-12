import { loadGpx, pointAt } from './gpx.js';
import { createNightMap } from './nightmap.js';
import { initAnalyses } from './analyses.js';
import * as audio from './audio.js';

document.documentElement.classList.add('ready');
const $ = (id) => document.getElementById(id);
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const fr = (n, d = 1) => n.toFixed(d).replace('.', ',');
const mobile = () => window.innerWidth <= 760;

// Stratégie d'exemple sur Paris : [km de début, portion, allure, FC].
const PARIS = [[0, 'Concorde → Bastille', '4:57', 148], [5, 'Reuilly', '4:58', 152], [12, 'Vincennes', '4:56', 154], [20, 'Quais de Seine', '4:55', 156],
  [27, 'Trocadéro → Auteuil', '4:56', 159], [35, 'Boulogne', '4:52', 163], [40, 'Avenue Foch', '4:45', null]];

// Trail : pente lissée sur 500 m, qui colore le tracé sur la carte (seuil marche/course d'exemple : 12 %).
const WALK = 12, STEEP_DOWN = -12;
const slope = (route, k) => (pointAt(route, Math.min(route.totalKm, k + 0.25)).ele - pointAt(route, Math.max(0, k - 0.25)).ele) / 5;
// Portions marchées et descentes raides, en tronçons continus (pas de 100 m).
function zones(route) {
  const out = { walk: [], down: [] }; let cur = null, kind = null;
  for (let k = 0; k <= route.totalKm; k += 0.1) {
    const p = pointAt(route, k), g = slope(route, k), z = g >= WALK ? 'walk' : g <= STEEP_DOWN ? 'down' : null;
    if (z !== kind) { cur = z ? [] : null; if (z) out[z].push(cur); kind = z; }
    if (cur) cur.push([p.lon, p.lat]);
  }
  return { type: 'FeatureCollection', features: Object.entries(out).map(([k, l]) => ({ type: 'Feature', properties: { kind: k }, geometry: { type: 'MultiLineString', coordinates: l.filter((x) => x.length > 1) } })) };
}

const ACTS = [
  { sel: '[data-act="paris"]', mapId: 'mapParis', kind: 'city', file: 'data/paris-marathon.gpx', officialKm: 42.195,
    view: { bearing: -8, pitch: 24, start: 'Champs-Élysées', finish: 'Avenue Foch', zoomIn: 1.1, turn: 22, tilt: 22 },
    live: (k) => { const s = [...PARIS].reverse().find((x) => k >= x[0]); return [s[1], `${s[2]} /km${s[3] ? ` · FC ${s[3]}` : ''}`]; } },
  { sel: '[data-act="utmb"]', mapId: 'mapUltra', kind: 'mountain', file: 'data/utmb.gpx', lazy: true,
    view: { bearing: 180, pitch: 50, exaggeration: 1.5, start: 'Chamonix', zoomIn: 0.7, turn: 30, tilt: 10, introMs: 2200 },
    trail: true,
    live: (k, route, p) => {
      const w = [...route.waypoints].reverse().find((x) => x.km <= k);
      return [`${w ? w.name : 'Chamonix'} · ${Math.round(p.ele).toLocaleString('fr-FR')} m`, ''];
    } },
];

/* ---------- Les actes : le scroll fait courir ---------- */
function setupAct(a) {
  a.el = document.querySelector(a.sel);
  a.caps = Array.from(a.el.querySelectorAll('.cap'));
  a.out = Object.fromEntries(Array.from(a.el.querySelectorAll('[data-live]')).map((n) => [n.dataset.live, n]));
  a.cur = 0; a.target = 0; a.shown = -1;
  const start = async () => {
    a.route = await loadGpx(a.file, { officialKm: a.officialKm });
    a.map = createNightMap($(a.mapId), {
      kind: a.kind, route: a.route, view: a.view, reduceMotion: reduce, zones: a.trail ? zones(a.route) : null,
      getPadding: () => mobile()
        ? { top: 90, bottom: Math.round(window.innerHeight * 0.42), left: 24, right: 24 }
        : { top: 110, bottom: 90, left: Math.round(window.innerWidth * 0.42), right: 70 },
    });
    if (!a.map) $(a.mapId).classList.add('no-map');
    a.shown = -1;
  };
  if (a.lazy) new IntersectionObserver(([e], o) => { if (e.isIntersecting) { o.disconnect(); start(); } }, { rootMargin: '150% 0px' }).observe(a.el);
  else start();
}

function measure() {
  for (const a of ACTS) {
    const r = a.el.getBoundingClientRect(), run = a.el.offsetHeight - window.innerHeight;
    a.target = Math.max(0, Math.min(1, -r.top / run));
    a.near = r.bottom > -window.innerHeight && r.top < window.innerHeight * 2;
  }
}

function render(a) {
  const f = a.cur;
  a.caps.forEach((c) => c.classList.toggle('on', f >= +c.dataset.from && f < +c.dataset.to));
  a.el.classList.toggle('scrolled', f > 0.01);
  a.out.bar.style.width = `${(f * 100).toFixed(2)}%`;
  if (!a.route) return;
  a.map?.setProgress(f);
  const k = f * a.route.totalKm, p = pointAt(a.route, k), [seg, extra, red] = a.live(k, a.route, p);
  a.out.km.textContent = `km ${fr(k)}`;
  a.out.seg.textContent = seg;
  a.out.pace.textContent = extra;
  a.out.pace.classList.toggle('red', !!red);
  // Feed audio with progress and FC
  if (audio.isRunning() && a.sel === '[data-act="paris"]') {
    const seg = [...PARIS].reverse().find((x) => k >= x[0]);
    audio.setProgress(f, seg && seg[3] ? seg[3] : 140);
  }
}

// Le scroll fixe une cible ; l'affichage la rattrape en douceur à chaque image (pas d'à-coups).
function loop() {
  for (const a of ACTS) {
    if (!a.near) continue;
    const d = a.target - a.cur;
    a.cur = reduce || Math.abs(d) < 0.0004 ? a.target : a.cur + d * 0.12;
    if (a.cur !== a.shown || (a.route && a.shown === -1)) { a.shown = a.cur; render(a); }
  }
  requestAnimationFrame(loop);
}

/* ---------- L'essai : ton marathon d'après la table générique ---------- */
function initTry() {
  const dist = $('t-dist'), time = $('t-time'), out = $('tryOut'), big = $('tryMar');
  const update = () => {
    const m = time.value.trim().match(/^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$/), d = +dist.value;
    const t = m ? (m[1] ? +m[1] * 3600 : 0) + +m[2] * 60 + +m[3] : 0;
    if (!t || t < d * 150 || t > d * 720) { out.hidden = true; return; }
    const mar = t * Math.pow(42.195 / d, 1.06);
    big.textContent = `${Math.floor(mar / 3600)}h${String(Math.floor(mar % 3600 / 60)).padStart(2, '0')}`;
    if (out.hidden) { out.hidden = false; }
  };
  time.addEventListener('input', update);
  dist.addEventListener('change', update);
}

/* ---------- Le film, à la demande ---------- */
function initFilm() {
  const dlg = $('film'), v = $('filmVideo'), overlay = $('filmOverlay'), playBtn = $('filmPlay');
  const bar = $('filmBar'), prog = $('filmProgress'), timeEl = $('filmTime');
  const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  let playing = false;

  function togglePlay() {
    if (v.paused) { v.play().catch(() => {}); } else { v.pause(); }
  }
  function syncUI() {
    playing = !v.paused;
    overlay.classList.toggle('hidden', playing);
    if (audio.isRunning() && playing) audio.stop();
  }

  v.addEventListener('play', syncUI);
  v.addEventListener('pause', syncUI);
  v.addEventListener('ended', () => { overlay.classList.remove('hidden'); });
  v.addEventListener('timeupdate', () => {
    const d = v.duration || 49;
    prog.style.width = `${(v.currentTime / d * 100).toFixed(1)}%`;
    timeEl.textContent = `${fmt(v.currentTime)} / ${fmt(d)}`;
  });

  playBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePlay(); });
  overlay.addEventListener('click', togglePlay);
  v.addEventListener('click', togglePlay);

  bar.addEventListener('click', (e) => {
    const r = bar.getBoundingClientRect();
    v.currentTime = (e.clientX - r.left) / r.width * (v.duration || 49);
  });

  $('openFilm').addEventListener('click', () => { dlg.showModal(); v.currentTime = 0; overlay.classList.remove('hidden'); });
  $('closeFilm').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener('close', () => { v.pause(); overlay.classList.remove('hidden'); });
}

function initReveal() {
  const els = document.querySelectorAll('.reveal');
  if (reduce) { els.forEach((e) => e.classList.add('in')); return; }
  const io = new IntersectionObserver((es) => es.forEach((en) => { if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); } }), { threshold: 0.2 });
  els.forEach((e) => io.observe(e));
}

const run = (fn) => { try { fn(); } catch (e) { console.error(e); } };
ACTS.forEach((a) => run(() => setupAct(a)));
measure();
window.addEventListener('scroll', measure, { passive: true });
window.addEventListener('resize', measure);
requestAnimationFrame(loop);
run(initAnalyses);
run(initTry);
run(initFilm);
run(initReveal);
run(function initSound() {
  const btn = $('navSound');
  if (!btn) return;
  btn.addEventListener('click', function () {
    if (audio.isRunning()) { audio.stop(); btn.setAttribute('aria-pressed', 'false'); }
    else { audio.start(); btn.setAttribute('aria-pressed', 'true'); }
  });
});
