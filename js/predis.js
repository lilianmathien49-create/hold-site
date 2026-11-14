// « Ta stratégie de course » : fenêtre d'appel qui s'ouvre une fois que le visiteur a fait défiler
// deux écrans. Il dépose son GPX, choisit sa course (route, ou trail avec D+), entre jusqu'à trois records.
// Durée estimée réellement calculée : Riegel (records → distance) puis Minetti 2002 (coût de la pente, amorti),
// puis affichée entièrement floutée, avec l'accès à la stratégie construite par Lilian.
import { parseGpx, pointAt } from './gpx.js';

const STRIPE_STRATEGIE = 'https://buy.stripe.com/7sY14gaTT3bPdpw4oU7Zu03';
const DEJA_VU = 'hold-predis-vu';
const track = (ev, props) => { if (typeof window.plausible === 'function') window.plausible(ev, props ? { props } : undefined); };
const store = { get: () => { try { return sessionStorage.getItem(DEJA_VU); } catch { return null; } },
  set: () => { try { sessionStorage.setItem(DEJA_VU, '1'); } catch { /* navigation privée */ } } };

const pad = (n) => String(n).padStart(2, '0');
const fmt = (s) => { s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h} h ${pad(m)}′${pad(s % 60)}` : `${m}′${pad(s % 60)}`; };
const pace = (s) => `${Math.floor(s / 60)}:${pad(Math.round(s % 60))}`;

const COURSES = [['5', '5 km'], ['10', '10 km'], ['21.0975', 'Semi-marathon'], ['42.195', 'Marathon'], ['trail', 'Trail ou autre distance']];
const RECORDS = [['1.5', '1 500 m'], ['3', '3 000 m'], ['5', '5 km'], ['10', '10 km'], ['21.0975', 'Semi'], ['42.195', 'Marathon']];
const MAX_REC = 3;
const toSec = (v) => { const p = String(v || '').trim().replace(/[hH'’]/g, ':').replace(/::+/g, ':').replace(/:$/, '').split(':').map(Number);
  if (p.some((x) => !Number.isFinite(x) || x < 0)) return NaN; return p.length === 2 ? p[0] * 60 + p[1] : p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : NaN; };
const num = (v) => parseFloat(String(v || '').replace(',', '.'));
// Loi puissance t = a·d^b : b ajusté sur les records (borné), ancré sur le record le plus proche de la distance.
function predire(recs, D) {
  let b = 1.06;
  if (recs.length >= 2) {
    const X = recs.map((r) => Math.log(r.d)), Y = recs.map((r) => Math.log(r.t)), mx = X.reduce((a, x) => a + x) / X.length, my = Y.reduce((a, y) => a + y) / Y.length;
    const sxx = X.reduce((a, x) => a + (x - mx) ** 2, 0);
    if (sxx > 1e-6) b = Math.min(1.15, Math.max(1.02, X.reduce((a, x, i) => a + (x - mx) * (Y[i] - my), 0) / sxx));
  }
  const ref = recs.reduce((m, r) => Math.abs(Math.log(r.d / D)) < Math.abs(Math.log(m.d / D)) ? r : m);
  return ref.t * (D / ref.d) ** b;
}

const html = `
<dialog class="modale pr" id="predis" aria-labelledby="pr-titre">
  <button type="button" class="modale-x" data-pr-close aria-label="Fermer">&times;</button>
  <div class="pr-in">
    <section class="pr-step" data-step="form">
      <p class="eyebrow">Gratuit · 30 secondes</p>
      <h2 class="pr-h" id="pr-titre">Ta stratégie de course.</h2>
      <p class="pr-sub">Dépose le GPX de ta course, entre tes records : tu obtiens ta durée de course estimée sur ce parcours.</p>
      <form id="pr-form" novalidate>
        <label class="pr-drop" id="pr-drop">
          <input type="file" id="pr-gpx" accept=".gpx,application/gpx+xml,application/xml,text/xml">
          <span class="pr-ico">GPX</span>
          <span><b id="pr-gpx-n">Dépose le GPX de ta course</b><small id="pr-gpx-i">Site de l'organisateur, Strava, Garmin…</small></span>
        </label>
        <label class="pr-f pr-course">Ta course<select id="pr-dist">${COURSES.map(([v, l]) => `<option value="${v}"${v === '42.195' ? ' selected' : ''}>${l}</option>`).join('')}</select></label>
        <div class="pr-row pr-trail" id="pr-trail" hidden>

          <label class="pr-f">Distance (km)<input id="pr-km" inputmode="decimal" placeholder="32" autocomplete="off"></label>
          <label class="pr-f">D+ (m)<input id="pr-dplus" inputmode="numeric" placeholder="1 800" autocomplete="off"></label>
        </div>
        <p class="pr-lab">Tes records <span>(3 max)</span></p>
        <div class="pr-recs" id="pr-recs"></div>
        <button type="button" class="pr-add" id="pr-add">+ Ajouter un record</button>
        <p class="pr-err" id="pr-err" role="alert"></p>
        <button class="btn pr-go" type="submit">Calculer ma course</button>
        <p class="pr-priv">Ton fichier est lu dans ton navigateur. Rien n'est envoyé.</p>
      </form>
    </section>

    <section class="pr-step" data-step="calc" hidden>
      <p class="eyebrow">Calcul en cours</p>
      <ul class="pr-load" id="pr-load"></ul>
    </section>

    <section class="pr-step" data-step="res" hidden>
      <p class="eyebrow">Ta durée de course estimée</p>
      <div class="pr-res">
        <div class="pr-kpis">
          <div><p class="pr-l">Durée estimée</p><p class="pr-v" id="pr-t"></p></div>
          <div><p class="pr-l">Allure moyenne</p><p class="pr-v s" id="pr-a"></p></div>
          <div><p class="pr-l">Effet du parcours</p><p class="pr-v s" id="pr-d"></p></div>
        </div>
        <div class="pr-prof" id="pr-prof"></div>
        <table class="pr-tab pr-tab-open"><thead><tr><th>Km</th><th>Allure</th><th>Passage</th><th>Terrain</th></tr></thead><tbody id="pr-tab1"></tbody></table>
        <div class="pr-lock">
        <div class="pr-blur" aria-hidden="true">
          <table class="pr-tab"><tbody id="pr-tab"></tbody></table>
        </div>
        <div class="pr-veil">
          <div class="pr-box">
            <h3>La suite de ta course.</h3>
            <p>Ton allure sur chaque kilomètre jusqu'à l'arrivée, où te retenir, où relancer : ta stratégie complète, construite par moi pour ce parcours.</p>
            <a class="btn" id="pr-cta" href="${STRIPE_STRATEGIE}" target="_blank" rel="noopener">Débloquer ma stratégie · 49,99 €</a>
            <a class="pr-alt" href="#contact" data-pr-close>Ou parlons de ta course d'abord</a>
          </div>
        </div>
        </div>
      </div>
    </section>
  </div>
</dialog>`;

function init() {
  document.body.insertAdjacentHTML('beforeend', html);
  const dlg = document.getElementById('predis');
  const $ = (id) => document.getElementById(id);
  let route = null;

  const show = (step) => dlg.querySelectorAll('.pr-step').forEach((s) => { s.hidden = s.dataset.step !== step; });
  const close = () => { if (dlg.open) dlg.close(); };
  dlg.querySelectorAll('[data-pr-close]').forEach((b) => b.addEventListener('click', close));
  dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); }); // clic sur le fond
  dlg.addEventListener('close', () => track('Stratégie : fermée'));

  // Ouverture : une seule fois par visite, après deux écrans de défilement.
  const open = () => { if (dlg.open || store.get() || document.querySelector('dialog[open]')) return; store.set(); show('form'); dlg.showModal(); track('Stratégie : affichée'); };
  const onScroll = () => { if (window.scrollY > window.innerHeight * 2) { window.removeEventListener('scroll', onScroll); open(); } };
  if (!store.get()) window.addEventListener('scroll', onScroll, { passive: true });
  window.hold = Object.assign(window.hold || {}, { predis: () => { show('form'); if (!dlg.open) dlg.showModal(); } });

  // Fichier GPX
  const load = (file) => {
    if (!file) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        route = parseGpx(String(rd.result));
        $('pr-gpx-n').textContent = file.name;
        $('pr-gpx-i').textContent = `${route.totalKm.toFixed(1).replace('.', ',')} km · D+ ${Math.round(route.gain)} m`;
        const near = COURSES.find(([v]) => Math.abs(route.totalKm - v) / v < 0.05);
        if (near) $('pr-dist').value = near[0];
        else { $('pr-dist').value = 'trail'; $('pr-km').value = route.totalKm.toFixed(1).replace('.', ','); }
        if (!near || route.gain > 300) $('pr-dplus').value = Math.round(route.gain);
        trailUI();
      } catch { route = null; $('pr-gpx-n').textContent = 'Fichier illisible'; $('pr-gpx-i').textContent = 'Essaie un autre export GPX.'; }
    };
    rd.readAsText(file);
  };
  $('pr-gpx').addEventListener('change', (e) => load(e.target.files[0]));
  const drop = $('pr-drop');
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => load(e.dataTransfer.files[0]));

  // Course : les champs trail n'apparaissent que si on choisit « Trail ou autre distance ».
  const trailUI = () => { $('pr-trail').hidden = $('pr-dist').value !== 'trail'; };
  $('pr-dist').addEventListener('change', trailUI);

  // Records : jusqu'à trois.
  const addRec = (d) => {
    const box = $('pr-recs'); if (box.children.length >= MAX_REC) return;
    const w = document.createElement('div'); w.className = 'pr-rec';
    w.innerHTML = `<select aria-label="Distance du record">${RECORDS.map(([v, l]) => `<option value="${v}"${v === d ? ' selected' : ''}>${l}</option>`).join('')}</select>
      <input inputmode="numeric" placeholder="${+d > 20 ? '1:35:00' : '42:30'}" aria-label="Temps" autocomplete="off">
      <button type="button" aria-label="Retirer ce record">&times;</button>`;
    w.querySelector('button').onclick = () => { if (box.children.length > 1) { w.remove(); $('pr-add').hidden = false; } else w.querySelector('input').value = ''; };
    box.append(w); $('pr-add').hidden = box.children.length >= MAX_REC;
  };
  addRec('10');
  $('pr-add').addEventListener('click', () => addRec($('pr-recs').children.length === 1 ? '21.0975' : '5'));

  // Calcul
  $('pr-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const err = (m) => { $('pr-err').textContent = m; };
    const trail = $('pr-dist').value === 'trail';
    const D = trail ? num($('pr-km').value) : +$('pr-dist').value;
    const dplus = trail ? Math.max(0, num($('pr-dplus').value) || 0) : 0;
    if (!(D >= 1 && D <= 200)) return err('Indique la distance de ta course en km.');
    const recs = [...$('pr-recs').children].map((w) => ({ d: +w.querySelector('select').value, t: toSec(w.querySelector('input').value) })).filter((r) => r.t > 0);
    if (recs.some((r) => r.t / r.d < 150 || r.t / r.d > 600)) return err('Un de tes temps semble incohérent avec sa distance. Format : 42:30 ou 1:35:00.');
    if (!recs.length) return err('Entre au moins un record, par exemple 42:30 sur 10 km.');
    err('');
    // Riegel donne la durée sur le plat ; Minetti la corrige selon la pente (GPX, sinon D+ déclaré).
    const Tplat = predire(recs, D);
    track('Stratégie : calcul', { course: trail ? 'trail' : String(D), gpx: route ? 'oui' : 'non', records: String(recs.length) });

    show('calc');
    const steps = [route ? 'Lecture du parcours' : trail ? 'Lecture de la distance et du D+' : 'Parcours considéré plat', 'Coût de chaque pente (Minetti)', recs.length > 1 ? 'Calibrage sur tes records (Riegel)' : 'Calibrage sur ton record (Riegel)', 'Durée de course estimée'];
    const ul = $('pr-load'); ul.innerHTML = steps.map((s) => `<li>${s}</li>`).join('');
    [...ul.children].forEach((li, i) => setTimeout(() => li.classList.add('on'), 350 + i * 450));
    setTimeout(() => { (trailMode = trail, fill(D, Tplat, dplus)); show('res'); }, 350 + steps.length * 450 + 200);
  });

  // Coût de la pente (Minetti et al., 2002), amorti pour l'allure de course.
  // Montée : coût de Minetti tel quel. Descente : le gain théorique est peu récupéré (encore moins en trail, terrain technique).
  let trailMode = false;
  const cost = (g) => { g = Math.max(-0.3, Math.min(0.35, g)); const r = (155.4 * g ** 5 - 30.4 * g ** 4 - 43.3 * g ** 3 + 46.3 * g ** 2 + 19.5 * g + 3.6) / 3.6; return r >= 1 ? r : 1 + (trailMode ? 0.2 : 0.5) * (r - 1); };
  const eleAt = (k, D) => { let s = 0; for (let j = -3; j <= 3; j++) s += pointAt(route, Math.min(route.totalKm, Math.max(0, (k + j * 0.05) * route.totalKm / D))).ele; return s / 7; };

  // Altitude moyennée sur une fenêtre de ±w km (w en km de course).
  const eleAvg = (k, D, w) => { const n = 8; let t = 0; for (let j = -n; j <= n; j++) t += pointAt(route, Math.min(route.totalKm, Math.max(0, (k + j * w / n) * route.totalKm / D))).ele; return t / (2 * n + 1); };

  // Profil sans GPX, pour un trail : le D+ déclaré réparti en montées et descentes à 8 %.
  const synth = (D, dplus) => { const L = Math.min(D / 2, dplus / 1000 / 0.08); return (k) => { const ph = (k / D) * 2 % 2; const x = Math.min(1, L / (D / 2)); return ph < 1 ? Math.min(ph / x, 1) * dplus / 2 : Math.max(1 - (ph - 1) / x, 0) * dplus / 2; }; };

  function fill(D, Tplat, dplus) {
    const STEP = 0.1, alt = route ? (k) => eleAvg(k, D, 0.3) : dplus > 0 ? synth(D, dplus) : () => 0;
    const segs = []; let prev = alt(0);
    for (let k = STEP; k <= D + 1e-9; k += STEP) { const e = alt(k); segs.push({ k, e, g: (e - prev) / (STEP * 1000) }); prev = e; }
    const f = segs.map((s) => cost(s.g)), meanF = f.reduce((a, x) => a + x, 0) / f.length;
    // Terrain de trail (+6 %) et fatigue des efforts longs : au-delà de 3 h, la durée s'allonge plus que ne le prévoit Riegel.
    const terrain = trailMode ? 1.06 : 1, T0 = Tplat * meanF * terrain, fatigue = T0 > 10800 ? (T0 / 10800) ** 0.1 : 1;
    const T = T0 * fatigue, unit = Tplat * terrain * fatigue / D, effet = T - Tplat;
    $('pr-t').textContent = fmt(T); $('pr-a').textContent = pace(T / D);
    $('pr-d').textContent = Math.abs(effet) < 5 ? 'Plat' : `${effet >= 0 ? '+' : '−'}${fmt(Math.abs(effet))}`;
    let rows = '', open = '', t = 0;
    for (let km = 1; km <= Math.min(Math.ceil(D), 9); km++) {
      const sl = segs.map((s, i) => [s, f[i]]).filter(([s]) => s.k > km - 1 + 1e-9 && s.k <= km + 1e-9);
      const sec = sl.reduce((a, [, x]) => a + x, 0) / Math.max(1, sl.length) * unit;
      const g = sl.reduce((a, [s]) => a + s.g, 0) / Math.max(1, sl.length);
      t += sec; const row = `<tr><td>km ${km}</td><td>${pace(sec)}</td><td>${fmt(t)}</td><td>${g > 0.02 ? 'Montée' : g < -0.02 ? 'Descente' : 'Plat'}</td></tr>`;
      if (km <= 2) open += row; else rows += row;
    }
    $('pr-tab1').innerHTML = open; $('pr-tab').innerHTML = rows;
    drawProfile(D);
  }

  // Profil : altitude légèrement lissée (bruit GPS), coloré selon la pente de chaque tronçon.
  const PENTES = [
    { max: -0.03, c: 'var(--p-descente)', l: 'Descente' },
    { max: 0.03, c: 'var(--p-plat)', l: 'Plat' },
    { max: 0.08, c: 'var(--p-doux)', l: 'Montée douce' },
    { max: 0.15, c: 'var(--p-raide)', l: 'Montée raide' },
    { max: Infinity, c: 'var(--p-mur)', l: 'Mur' },
  ];
  function drawProfile(D) {
    const box = $('pr-prof');
    if (!route) { box.hidden = true; return; } // sans GPX, pas de profil inventé
    box.hidden = false;
    const N = 260, w = Math.max(0.06, D * 0.004), dk = D / N;
    const e = [...Array(N + 1)].map((_, i) => eleAvg(i * dk, D, w));
    const lo0 = Math.min(...e), hi = Math.max(...e), span = Math.max(hi - lo0, 120), lo = lo0 - (span - (hi - lo0)) * 0.15;
    const W = 600, H = 130, top = 6, base = H - 1;
    const X = (i) => (i / N * W), Y = (v) => top + (1 - (v - lo) / span) * (base - top);
    // Pente pour la couleur : mesurée sur ±h km (≥ 300 m), pour des tronçons lisibles plutôt qu'un clignotement.
    const h = Math.max(0.3, D * 0.008), g = (i) => { const k = (i + 0.5) * dk; return (eleAvg(Math.min(D, k + h), D, w) - eleAvg(Math.max(0, k - h), D, w)) / ((Math.min(D, k + h) - Math.max(0, k - h)) * 1000); };
    let bands = '';
    for (let i = 0; i < N; i++) {
      const c = PENTES.find((k) => g(i) < k.max).c;
      bands += `<path d="M${X(i).toFixed(2)},${base} L${X(i).toFixed(2)},${Y(e[i]).toFixed(2)} L${(X(i + 1) + 0.4).toFixed(2)},${Y(e[i + 1]).toFixed(2)} L${(X(i + 1) + 0.4).toFixed(2)},${base}Z" fill="${c}"/>`;
    }
    const line = e.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(2)},${Y(v).toFixed(2)}`).join('');
    const step = D > 60 ? 20 : D > 25 ? 10 : D > 12 ? 5 : 2;
    let ax = ''; for (let k = 0; k <= D - Math.max(step * 0.6, D * 0.1); k += step) ax += `<span style="left:${(k / D * 100).toFixed(2)}%">${k}</span>`;
    ax += `<span style="left:100%">${Math.round(D)} km</span>`;
    box.innerHTML = `<div class="pr-prof-h"><span>Ton parcours</span><span>${Math.round(lo0)} – ${Math.round(hi)} m</span><span>${String(D.toFixed(1)).replace('.', ',')} km · D+ ${Math.round(route.gain)} m</span></div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Profil du parcours coloré selon la pente"><g opacity=".85" shape-rendering="crispEdges">${bands}</g><path d="${line}" fill="none" stroke="var(--text)" stroke-width="1.4" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>
      <div class="pr-prof-ax">${ax}</div>
      <div class="pr-leg">${PENTES.map((k, i) => `<span><i style="background:${k.c}"></i>${k.l} <em>${i === 0 ? '< −3 %' : i === 1 ? '±3 %' : i === 2 ? '3–8 %' : i === 3 ? '8–15 %' : '> 15 %'}</em></span>`).join('')}</div>`;
  }
  $('pr-cta').addEventListener('click', () => track('Stratégie : vers la stratégie'));
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
