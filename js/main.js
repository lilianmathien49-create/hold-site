import { loadGpx, pointAt } from './gpx.js';
import { createNightMap } from './nightmap.js';
import { initAnalyses } from './analyses.js';
import { initAvis } from './avis.js';
import { initRdv } from './rdv.js';
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

const nav = $('nav');
function measure() {
  for (const a of ACTS) {
    const r = a.el.getBoundingClientRect(), run = a.el.offsetHeight - window.innerHeight;
    a.target = Math.max(0, Math.min(1, -r.top / run));
    a.near = r.bottom > -window.innerHeight && r.top < window.innerHeight * 2;
  }
  // La nav est posée sur les actes (nuit) puis sur le contenu (clair) : elle suit la surface.
  const last = ACTS[ACTS.length - 1].el;
  nav?.classList.toggle('dark', last.getBoundingClientRect().bottom > nav.offsetHeight);
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

/* ---------- L'essai : tes équivalents sur les autres distances ---------- */
const DISTANCES = [[5, '5 km'], [10, '10 km'], [21.0975, 'Semi'], [42.195, 'Marathon']];
// Formule de Riegel : t2 = t1 × (d2/d1)^1,06. Table générique, identique pour tous.
const riegel = (t, from, to) => t * Math.pow(to / from, 1.06);
const clock = (s) => (s >= 3600
  ? `${Math.floor(s / 3600)}h${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`
  : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`);

function initTry() {
  const dist = $('t-dist'), time = $('t-time'), out = $('tryOut'), grid = $('tryGrid');
  const update = () => {
    const m = time.value.trim().match(/^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$/), d = +dist.value;
    const t = m ? (m[1] ? +m[1] * 3600 : 0) + +m[2] * 60 + +m[3] : 0;
    if (!t || t < d * 150 || t > d * 720) { out.hidden = true; return; }
    grid.replaceChildren(...DISTANCES.map(([km, name]) => {
      const self = Math.abs(km - d) < 0.01, secs = self ? t : riegel(t, d, km);
      const cell = document.createElement('div');
      cell.className = `try-cell${self ? ' is-self' : ''}`;
      cell.innerHTML = `<p class="try-d mono"></p><p class="try-t"></p><p class="try-p mono"></p>`;
      cell.querySelector('.try-d').textContent = self ? `${name} · ton chrono` : name;
      cell.querySelector('.try-t').textContent = clock(secs);
      cell.querySelector('.try-p').textContent = `${clock(secs / km)} /km`;
      return cell;
    }));
    if (out.hidden) out.hidden = false;
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

  const ouvrir = $('openFilmNav');
  if (ouvrir) ouvrir.addEventListener('click', () => {
    dlg.showModal(); v.currentTime = 0; overlay.classList.remove('hidden');
  });
  $('closeFilm').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener('close', () => { v.pause(); overlay.classList.remove('hidden'); });
}

/* ---------- La demande : un mail déjà rempli ---------- */
const MAIL = 'contact.holdrunning@gmail.com';
// Adresse du service qui reçoit le formulaire (Formspree, Web3Forms…). Vide,
// le formulaire retombe sur le logiciel de mail du visiteur — ce qui échoue
// chez beaucoup de monde. Dès qu'elle est remplie, le message part vraiment.
const ENDPOINT = 'https://formspree.io/f/xgaaydkk';
function initAsk() {
  const form = $('askForm'), hint = $('askHint');
  if (!form || !hint) return;
  const v = (id) => { const e = $(id); return e ? e.value.trim() : ''; };
  const say = (msg, erreur) => {
    hint.textContent = msg;
    hint.classList.toggle('hint-err', !!erreur);
  };

  // L'offre vient soit du menu, soit d'un bouton de carte tarifaire : on
  // n'oblige personne à la retaper.
  const offre = () => v('f-offre');

  const sujet = () => `Réservation d'appel — ${v('f-name') || 'nouveau coureur'}`;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const manque = ['f-name', 'f-mail'].filter((id) => !v(id));
    if (manque.length) {
      const el = $(manque[0]);
      if (el) el.focus();
      say('Il me faut juste ton nom et ton email.', true);
      return;
    }
    const rgpd = $('f-rgpd');
    if (rgpd && !rgpd.checked) {
      rgpd.focus();
      say('Il me faut ton accord pour te recontacter.', true);
      return;
    }
    if (!ENDPOINT) {                       // garde-fou : rien ne part à l'aveugle
      say(`Le formulaire n'est pas encore branché. Écris-moi à ${MAIL}.`, true);
      return;
    }

    const btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    say('Envoi…');
    try {
      const r = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          nom: v('f-name'), email: v('f-mail'), objectif: v('f-goal'),
          disponibilites: v('f-slots'), offre: offre() || 'non précisée',
          _subject: sujet(), _replyto: v('f-mail'),
        }),
      });
      if (!r.ok) throw new Error(`réponse ${r.status}`);
      form.reset();
      say("C'est reçu. Je te réponds sous 24 h avec un créneau. — Lilian");
      if (typeof window.plausible === 'function') window.plausible('Formulaire envoyé');
    } catch {
      say(`L'envoi a échoué. Écris-moi directement à ${MAIL}, je te réponds pareil.`, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // Un bouton de carte tarifaire choisit l'offre et descend au formulaire.
  for (const b of document.querySelectorAll('[data-offer]')) {
    b.addEventListener('click', () => {
      const sel = $('f-offre');
      if (!sel) return;
      const cherche = (b.dataset.offreValeur || '').trim();
      const opt = [...sel.options].find((o) => o.text === cherche);
      if (opt) sel.value = opt.value;
    });
  }
}

function initApercu() {
  // Le curseur du profil, sur la page d'accueil. Amélioration progressive :
  // la barre de lecture est déjà remplie par le générateur, ce script ne fait
  // que la rendre mobile. S'il ne tourne pas, la page reste juste.
  const svg = $('apSvg'), brut = $('apData');
  if (!svg || !brut) return;

  let geo, segs;
  try {
    geo = JSON.parse(svg.dataset.geo);
    segs = JSON.parse(brut.textContent);
  } catch { return; }
  if (!geo || !segs || !segs.length) return;

  const tige = $('apTige'), point = $('apPoint');
  const champs = { km: $('apKm'), alt: $('apAlt'), pente: $('apPente'), mode: $('apMode'),
    allure: $('apAllure'), heure: $('apHeure'), temp: $('apTemp') };
  if (!tige || !point || !champs.km) return;

  // Mêmes formules que le générateur, dans l'autre sens.
  const largeur = geo.w - geo.g - geo.d;
  const xDe = (km) => geo.g + (km / geo.total) * largeur;
  const yDe = (alt) => geo.haut + geo.ph - ((alt - geo.y0) / (geo.y1 - geo.y0)) * geo.ph;
  const fr1 = (v) => Number(v).toFixed(1).replace('.', ',').replace('-', '\u2212');
  const mille = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '\u202f');

  // Les mêmes seuils que classe_pente() côté Python : si l'un bouge, l'autre
  // doit bouger. Ils décident de la couleur ET du sens du mot « raide ».
  const classe = (p) => (p < -4 ? 'descente' : p < 4 ? 'plat' : p < 10 ? 'doux'
    : p < 15 ? 'raide' : 'mur');

  let index = -1;
  function montrer(i) {
    i = Math.max(0, Math.min(segs.length - 1, i));
    if (i === index) return;
    index = i;
    const [km, alt, pente, marche, allure, heure, temp] = segs[i];
    const px = xDe(km), py = yDe(alt);
    tige.setAttribute('x1', px); tige.setAttribute('x2', px);
    point.setAttribute('cx', px); point.setAttribute('cy', py);
    champs.km.textContent = fr1(km);
    champs.alt.innerHTML = `${mille(alt)}<small> m</small>`;
    champs.pente.textContent = `${fr1(pente)} %`;
    champs.pente.className = `ap-p ap-p-${classe(pente)}`;
    champs.mode.textContent = marche ? 'Marche' : 'Course';
    champs.allure.textContent = allure;
    champs.heure.textContent = heure;
    champs.temp.innerHTML = temp === null ? '—' : `${fr1(temp)}<small> °C</small>`;
  }

  // Du pointeur vers le tronçon : on repasse par le kilomètre, pas par une
  // recherche du point le plus proche à l'écran — les tronçons sont réguliers
  // en distance, pas en pixels.
  function auPointeur(clientX) {
    const r = svg.getBoundingClientRect();
    if (!r.width) return;
    const px = ((clientX - r.left) / r.width) * geo.w;
    const km = ((px - geo.g) / largeur) * geo.total;
    let lo = 0, hi = segs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (segs[mid][0] < km) lo = mid + 1; else hi = mid;
    }
    montrer(lo);
  }

  svg.addEventListener('pointermove', (e) => auPointeur(e.clientX));
  svg.addEventListener('pointerdown', (e) => { auPointeur(e.clientX); svg.focus(); });

  // Au clavier : le profil est focalisable, les flèches le parcourent.
  svg.addEventListener('keydown', (e) => {
    const pas = e.shiftKey ? 20 : 1;
    if (e.key === 'ArrowRight') { montrer(index < 0 ? 0 : index + pas); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { montrer(index < 0 ? 0 : index - pas); e.preventDefault(); }
    else if (e.key === 'Home') { montrer(0); e.preventDefault(); }
    else if (e.key === 'End') { montrer(segs.length - 1); e.preventDefault(); }
  });

  const aide = $('apAide');
  if (aide) aide.textContent = 'Balaye le profil · flèches au clavier';
}


function initVoie() {
  // Le sélecteur de la méthode : complète, coaching seul, pacing seul.
  // Amélioration progressive — sans ce script, les quatre temps s'affichent,
  // ce qui est exactement la méthode complète.
  const tabs = document.querySelectorAll('.how-tabs [data-voie]');
  const etapes = document.querySelectorAll('.how-steps [data-voie]');
  const sous = $('howSub');
  if (!tabs.length || !etapes.length) return;

  const TEXTES = {
    general: "Quatre temps, dans cet ordre. Chacun sert le suivant : sans objectif pas "
      + "d'entraînement ciblé, et sans entraînement suivi pas de stratégie fiable.",
    coaching: "Tu veux progresser, sans course précise en tête. On s'arrête à "
      + "l'entraînement : objectif, analyse de tes séances, plan réajusté chaque semaine.",
    pacing: "Tu t'entraînes déjà de ton côté. On part de tes données et du parcours pour "
      + "écrire ta course — sans toucher à ton plan.",
  };

  function choisir(voie) {
    for (const t of tabs) t.setAttribute('aria-selected', String(t.dataset.voie === voie));
    let visibles = 0;
    for (const e of etapes) {
      const dedans = (e.dataset.voie || '').split(' ').includes(voie);
      e.hidden = !dedans;
      if (dedans) visibles += 1;
    }
    // La grille compte autant de colonnes que de temps affichés, sinon la
    // place du temps masqué reste vide.
    const liste = etapes[0].parentElement;
    if (liste) liste.style.setProperty('--cols', String(visibles));
    if (sous && TEXTES[voie]) sous.textContent = TEXTES[voie];
  }

  for (const t of tabs) t.addEventListener('click', () => choisir(t.dataset.voie));
}


function initMesure() {
  // Quatre signaux, pour répondre à quatre questions : combien arrivent,
  // jusqu'où ils descendent, combien commencent à écrire, combien partent
  // payer. Rien d'identifiant n'est envoyé — seulement des étiquettes.
  const envoyer = (nom, props) => {
    if (typeof window.plausible === 'function') window.plausible(nom, props ? { props } : undefined);
  };

  // Profondeur de lecture. On ne signale chaque palier qu'une fois, et on
  // n'écoute le défilement qu'au repos : mesurer ne doit pas ralentir la page.
  const paliers = [25, 50, 75, 100];
  const vus = new Set();
  let enAttente = false;
  function jauger() {
    enAttente = false;
    const h = document.documentElement;
    const total = h.scrollHeight - h.clientHeight;
    if (total < 400) return;                // page trop courte pour un palier
    const pct = Math.min(100, Math.round((h.scrollTop / total) * 100));
    for (const p of paliers) {
      if (pct >= p && !vus.has(p)) {
        vus.add(p);
        envoyer('Lecture', { palier: `${p} %` });
      }
    }
  }
  window.addEventListener('scroll', () => {
    if (enAttente) return;
    enAttente = true;
    requestAnimationFrame(jauger);
  }, { passive: true });

  // Formulaire entamé : la première frappe suffit, et une seule fois.
  const form = $('askForm');
  if (form) {
    let entame = false;
    form.addEventListener('input', () => {
      if (entame) return;
      entame = true;
      envoyer('Formulaire entamé');
    }, { once: false });
    form.addEventListener('submit', () => envoyer('Formulaire envoyé'));
  }

  // Les offres, et les départs vers Stripe depuis n'importe quelle page.
  for (const b of document.querySelectorAll('[data-offer]')) {
    b.addEventListener('click', () => envoyer('Offre regardée', { offre: b.dataset.offer || '' }));
  }
  for (const a of document.querySelectorAll('a[href*="buy.stripe.com"]')) {
    a.addEventListener('click', () => envoyer('Départ vers le paiement'));
  }
}


function initEssai() {
  // L'estimateur a quitté le défilement : il vit dans une fenêtre, ouverte
  // depuis le menu. Le calcul lui-même n'a pas bougé.
  const dlg = $('essaiDlg'), ouvrir = $('openEssaiNav'), fermer = $('closeEssai');
  if (!dlg || !ouvrir) return;
  ouvrir.addEventListener('click', () => dlg.showModal());
  if (fermer) fermer.addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
}


function initReveal() {
  const els = document.querySelectorAll('.reveal');
  if (reduce) { els.forEach((e) => e.classList.add('in')); return; }
  const io = new IntersectionObserver((es) => es.forEach((en) => { if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); } }), { threshold: 0.2 });
  els.forEach((e) => io.observe(e));
}

// Les portions de la table de marche. Chaque ligne de ravitaillement cache le
// détail de la portion qui y mène. Le repli est posé ici et non dans la
// feuille de style : si ce script ne part pas, les détails restent dépliés.
function initPortions() {
  const boutons = document.querySelectorAll('.ap-ouvre');
  boutons.forEach((b) => {
    const det = $(b.getAttribute('aria-controls'));
    if (!det) return;
    det.classList.add('ap-det-js');
    b.setAttribute('aria-expanded', 'false');
    b.addEventListener('click', () => {
      const ouvert = b.getAttribute('aria-expanded') === 'true';
      b.setAttribute('aria-expanded', String(!ouvert));
      det.classList.toggle('ap-det-on', !ouvert);
    });
  });
}

const run = (fn) => { try { fn(); } catch (e) { console.error(e); } };
ACTS.forEach((a) => run(() => setupAct(a)));
measure();
window.addEventListener('scroll', measure, { passive: true });
window.addEventListener('resize', measure);
requestAnimationFrame(loop);
run(initAnalyses);
run(initTry);
run(initAsk);
run(initFilm);
run(initApercu);
run(initPortions);
run(initVoie);
run(initEssai);
run(initMesure);
run(initAvis);
run(initRdv);
run(initReveal);
