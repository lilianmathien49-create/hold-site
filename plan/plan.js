// Plan de course : le fichier servi est chiffré, le mot de passe ne quitte jamais le navigateur.
// Clé dérivée en PBKDF2-SHA256, contenu scellé en AES-GCM (qui échoue si on altère le fichier).
const $ = (id) => document.getElementById(id);
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function decrypt(pack, password) {
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: b64(pack.salt), iterations: pack.iter, hash: 'SHA-256' },
    base, { name: 'AES-GCM', length: 256 }, false, ['decrypt'],
  );
  const clear = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(pack.iv) }, key, b64(pack.data));
  return JSON.parse(new TextDecoder().decode(clear));
}

/* ---------- Petits formats ---------- */
const km1 = (v) => Number(v).toFixed(1).replace('.', ',');
const degC = (v) => `${Math.round(v)} °C`;
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
// Les premiers plans ont été générés avec des dates anglaises (« Friday 27 August
// 2027 », « Fri 18:02 ») : on les traduit à l'affichage, les nouveaux sont déjà en français.
const FR = { Monday: 'lundi', Tuesday: 'mardi', Wednesday: 'mercredi', Thursday: 'jeudi', Friday: 'vendredi',
  Saturday: 'samedi', Sunday: 'dimanche', Mon: 'lun.', Tue: 'mar.', Wed: 'mer.', Thu: 'jeu.', Fri: 'ven.',
  Sat: 'sam.', Sun: 'dim.', January: 'janvier', February: 'février', March: 'mars', April: 'avril',
  May: 'mai', June: 'juin', July: 'juillet', August: 'août', September: 'septembre', October: 'octobre',
  November: 'novembre', December: 'décembre' };
const fr = (t) => String(t ?? '').replace(/\b[A-Z][a-z]+\b/g, (w) => FR[w] || w);
const LIGHT_ICON = { nuit: '●', jour: '○', 'entre chien et loup': '◐' };

/* ---------- Le parcours, lu d'un coup d'œil ----------
   Un profil seul ne dit pas grand-chose. On empile sous lui trois bandes qui
   se lisent à la verticale : la pente, ce que tu y fais, et la lumière. */
// Mêmes seuils que le découpage en portions, pour que couleur et texte s'accordent.
const terrainOf = (g) => g >= 12 ? 'raide' : g >= 4 ? 'montee' : g > -4 ? 'plat'
  : g > -12 ? 'descente' : 'plongeon';

/* ---------- Le poste de pilotage ----------
   Un seul curseur commande tout : le profil, les compteurs, la consigne.
   On balaye le parcours et on lit où on sera, quand, par quel temps. */
/* ---------- Moteur de graphiques ----------
   Un seul endroit décide des axes, des graduations et des couleurs : sans ça
   chaque courbe invente sa propre échelle et plus rien ne se compare. */
const NICE = [1, 2, 2.5, 5, 10];
function niceStep(span, target = 5) {
  const raw = span / target, mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  return (NICE.find((n) => raw / mag <= n) || 10) * mag;
}
function axisTicks(lo, hi, target = 5) {
  if (!(hi > lo)) return { lo: lo - 1, hi: lo + 1, ticks: [lo] };
  const step = niceStep(hi - lo, target);
  const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = a; v <= b + step * 0.001; v += step) ticks.push(+v.toFixed(6));
  return { lo: a, hi: b, ticks };
}

/* series : { pts:[[x,y]], kind:'line'|'area'|'bars'|'band', cls, axis:'l'|'r', label } */
function chart(o) {
  const W = o.width || 1000, H = o.height || 260;
  const P = { l: o.padLeft ?? 54, r: o.padRight ?? (o.right ? 54 : 16), t: 16, b: 34 };
  const all = (ax) => o.series.filter((s) => (s.axis || 'l') === ax).flatMap((s) => s.pts);
  const xs = o.series.flatMap((s) => s.pts.map((p) => p[0]));
  const xa = axisTicks(o.x0 ?? Math.min(...xs), o.x1 ?? Math.max(...xs), o.xTicks || 5);
  const mk = (ax, forced) => {
    const v = all(ax).map((p) => p[1]).filter((n) => Number.isFinite(n));
    if (!v.length) return null;
    return axisTicks(forced?.[0] ?? Math.min(...v), forced?.[1] ?? Math.max(...v), 4);
  };
  const ya = mk('l', o.yRange), yb = o.right ? mk('r', o.yRangeRight) : null;

  const X = (v) => P.l + (v - xa.lo) / (xa.hi - xa.lo || 1) * (W - P.l - P.r);
  const Y = (v, ax) => {
    const a = ax === 'r' && yb ? yb : ya;
    return P.t + (H - P.t - P.b) - (v - a.lo) / (a.hi - a.lo || 1) * (H - P.t - P.b);
  };
  const fmt = (f, v) => (f ? f(v) : String(Math.round(v * 100) / 100).replace('.', ','));

  const grid = ya.ticks.map((v) =>
    `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v, 'l').toFixed(1)}" y2="${Y(v, 'l').toFixed(1)}" class="ch-grid"/>
     <text x="${P.l - 9}" y="${(Y(v, 'l') + 4).toFixed(1)}" text-anchor="end" class="ch-lab">${fmt(o.yFmt, v)}</text>`).join('');
  const gridR = yb ? yb.ticks.map((v) =>
    `<text x="${W - P.r + 9}" y="${(Y(v, 'r') + 4).toFixed(1)}" class="ch-lab ch-lab-r">${fmt(o.yFmtRight, v)}</text>`).join('') : '';
  const xlab = xa.ticks.map((v) =>
    `<text x="${X(v).toFixed(1)}" y="${H - 11}" text-anchor="middle" class="ch-lab">${fmt(o.xFmt, v)}</text>`).join('');

  const bands = (o.bands || []).map((b) =>
    `<rect x="${X(b.x0).toFixed(1)}" y="${P.t}" width="${Math.max(0.5, X(b.x1) - X(b.x0)).toFixed(1)}"
       height="${H - P.t - P.b}" class="${b.cls || 'ch-band'}"/>`).join('');
  const marks = (o.marks || []).map((m) =>
    `<line x1="${X(m.x).toFixed(1)}" x2="${X(m.x).toFixed(1)}" y1="${P.t}" y2="${H - P.b}" class="${m.cls || 'ch-mark'}"/>`).join('');

  const draw = o.series.map((s) => {
    const ax = s.axis || 'l';
    const pts = s.pts.filter((p) => Number.isFinite(p[1]));
    if (!pts.length) return '';
    if (s.kind === 'bars') {
      const bw = Math.max(1.5, (W - P.l - P.r) / pts.length * 0.72);
      return pts.map((p) => {
        const y = Y(Math.max(p[1], ya.lo), ax), base = Y(Math.max(0, ya.lo), ax);
        return `<rect x="${(X(p[0]) - bw / 2).toFixed(1)}" y="${Math.min(y, base).toFixed(1)}"
          width="${bw.toFixed(1)}" height="${Math.max(1, Math.abs(base - y)).toFixed(1)}" class="${s.cls}"/>`;
      }).join('');
    }
    const d = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)} ${Y(p[1], ax).toFixed(1)}`).join('');
    if (s.kind === 'area') {
      const base = Y(Math.max(ya.lo, 0), ax);
      return `<path d="${d}L${X(pts[pts.length - 1][0]).toFixed(1)} ${base.toFixed(1)}L${X(pts[0][0]).toFixed(1)} ${base.toFixed(1)}Z" class="${s.cls}"/>`;
    }
    if (s.kind === 'band') {
      const up = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)} ${Y(p[1], ax).toFixed(1)}`).join('');
      const dn = pts.slice().reverse().map((p) => `L${X(p[0]).toFixed(1)} ${Y(p[2], ax).toFixed(1)}`).join('');
      return `<path d="${up}${dn}Z" class="${s.cls}"/>`;
    }
    return `<path d="${d}" class="${s.cls}"/>`;
  }).join('');

  const legend = (o.series.filter((s) => s.label).map((s) =>
    `<span class="lg"><i class="sw ${s.swatch || s.cls}"></i>${esc(s.label)}</span>`).join('')
    + (o.extraLegend || ''));

  return `<figure class="ch">
    ${o.title ? `<figcaption class="ch-t">${esc(o.title)}</figcaption>` : ''}
    ${o.note ? `<p class="ch-n">${esc(o.note)}</p>` : ''}
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.title || 'graphique')}">
      ${bands}${grid}${gridR}${draw}${marks}${xlab}
      ${o.yLabel ? `<text x="2" y="11" class="ch-ax">${esc(o.yLabel)}</text>` : ''}
      ${o.yLabelRight ? `<text x="${W - 2}" y="11" text-anchor="end" class="ch-ax">${esc(o.yLabelRight)}</text>` : ''}
      ${o.xLabel ? `<text x="${W - P.r}" y="${H - 11}" text-anchor="end" class="ch-ax">${esc(o.xLabel)}</text>` : ''}
    </svg>
    ${legend ? `<div class="pf-legend">${legend}</div>` : ''}
  </figure>`;
}

/* ---------- Ta course en quelques consignes ----------
   Tout le reste du rapport est une justification. Ici, on dit quoi faire :
   chaque consigne est calculée à partir du plan, pas écrite à la main. */
function briefing(plan) {
  const S = plan.segments || [], secs = plan.sections || [], aid = plan.aid || [];
  if (!S.length) return '';
  const m = plan.model || {}, g = plan.gam || {};
  const items = [];

  // 1. L'allure de départ, et ce qu'elle coûte si on la dépasse.
  const early = secs.filter((s) => s.km1 <= 15);
  if (early.length) {
    const dt = early.reduce((a, s) => a + s.split, 0);
    const km = early[early.length - 1].km1;
    const bw = plan.blowups && (plan.blowups.points || [])[0];
    const hm = (x) => `${Math.floor(x / 3600)}h${String(Math.round(x % 3600 / 60)).padStart(2, '0')}`;
    items.push({
      n: '01', title: `Pars à ${mmss(dt / km)} au kilomètre, pas plus vite`,
      body: `Sur les ${km1(km)} premiers kilomètres. C'est la consigne la plus facile à trahir et la plus chère.`,
      proof: bw ? `Sur douze éditions, ceux qui passaient sur les bases de ${esc(plan.goal)} à ce stade
        ont fini en ${hm(bw.median)} en médiane. Un sur dix au-delà de ${hm(bw.p90)}.` : '',
      big: mmss(dt / km), unit: '/km',
    });
  }

  // 2. Le seuil de marche, qui bouge avec les heures.
  const thr0 = (g.walk || {}).thr0 ?? m.walkThr;
  const curve = (g.walk || {}).curve;
  const late = curve ? (curve.find((c) => c[0] === 4) || [])[1] : null;
  if (thr0) {
    items.push({
      n: '02', title: `Marche dès ${km1(thr0)} % de pente${late ? `, puis dès ${km1(late)} % après quatre heures` : ''}`,
      body: `Ton seuil n'est pas fixe : il descend au fil de la course. Ce qui se court au départ
        se marche à la quinzième heure, et s'entêter coûte plus que ça ne rapporte.`,
      proof: m.walkKm != null ? `Au total ${km1(m.walkKm)} km marchés sur ${km1(plan.distanceKm)}.` : '',
      big: `${km1(thr0)} %`, unit: 'au départ',
    });
  }

  // 3. Où sortir les bâtons — on fusionne les portions contiguës.
  const poleRuns = [];
  for (const s of secs) {
    if (!s.poles) continue;
    const last = poleRuns[poleRuns.length - 1];
    if (last && s.km0 - last.km1 < 3) last.km1 = s.km1;
    else poleRuns.push({ km0: s.km0, km1: s.km1 });
  }
  if (poleRuns.length) {
    const tot = poleRuns.reduce((a, r) => a + r.km1 - r.km0, 0);
    items.push({
      n: '03', title: 'Bâtons sortis sur ces portions',
      body: poleRuns.slice(0, 6).map((r) => `km ${km1(r.km0)} – ${km1(r.km1)}`).join(' · ')
        + (poleRuns.length > 6 ? ` · et ${poleRuns.length - 6} autres` : ''),
      proof: 'Rangés ailleurs : les sortir et les ranger coûte du temps, le faire trop souvent en coûte plus.',
      big: `${km1(tot)}`, unit: 'km avec bâtons',
    });
  }

  // 4. Le gros arrêt, celui qu'on ne doit pas écourter.
  const stops = (plan.lessons || {}).stops || [];
  if (stops.length) {
    const top = stops[0];
    const totMin = Math.round(stops.reduce((a, s) => a + s.median, 0) / 60);
    items.push({
      n: '04', title: `À ${esc(top.name)}, arrête-toi vraiment`,
      body: `Les finishers du même chrono y passent ${Math.round(top.median / 60)} minutes en médiane,
        et un sur dix y reste ${Math.round(top.p90 / 60)}. C'est un investissement, pas une perte.`,
      proof: `Sur l'ensemble des points, ils cumulent environ ${totMin} minutes à l'arrêt.`,
      big: `${Math.round(top.median / 60)}`, unit: 'minutes',
    });
  }

  // 5. Ce qu'il faut avaler, par heure.
  const hours = S.length ? hmsToSec(S[S.length - 1].cumul) / 3600 : 0;
  if (hours > 1) {
    const carbs = Math.round(CARB_PER_H * hours), tempMoy =
      S.reduce((a, s) => a + s.temp, 0) / S.length;
    const fluid = S.reduce((a, s, i) => {
      const prev = i ? hmsToSec(S[i - 1].cumul) : 0;
      return a + fluidPerH(s.temp) * (hmsToSec(s.cumul) - prev) / 3600;
    }, 0);
    items.push({
      n: '05', title: `Mange ${CARB_PER_H} g de glucides par heure, sans attendre la faim`,
      body: `Soit un gel toutes les vingt-cinq minutes, ou l'équivalent en solide. Et bois
        ${Math.round(fluidPerH(tempMoy) / 50) * 50} ml par heure en moyenne, davantage quand il fera chaud.`,
      proof: `Sur la course entière : ${(carbs / 1000).toFixed(1).replace('.', ',')} kg de glucides
        et ${(fluid / 1000).toFixed(1).replace('.', ',')} litres. Teste ces volumes à l'entraînement avant.`,
      big: `${CARB_PER_H}`, unit: 'g/h',
    });
  }

  // 6. La nuit et le froid.
  const night = (plan.windows || []).filter((w) => w.light === 'nuit');
  if (night.length) {
    const tot = night.reduce((a, w) => a + w.km1 - w.km0, 0);
    const cold = aid.filter((a2) => (a2.gear || []).includes('gants'))[0];
    items.push({
      n: '06', title: `Frontale de ${night.map((w) => `km ${km1(w.km0)} à ${km1(w.km1)}`).join(', et de ')}`,
      body: cold ? `Gants à partir de ${esc(cold.name)} : il y fera ${degC(cold.temp)}.
        L'air perd six degrés et demi par millier de mètres : les cols de nuit passent sous zéro.`
        : 'Calculé sur la position réelle du soleil à la date et au lieu de ta course.',
      proof: `${km1(tot)} km de nuit sur ${km1(plan.distanceKm)}.`,
      big: `${km1(tot)}`, unit: 'km de nuit',
    });
  }

  return `<section class="brief">
    <div class="brief-head">
      <p class="eyebrow">Ta course, en ${items.length} consignes</p>
      <h2 class="title">Ce que tu dois faire.</h2>
      <p class="sub">Si tu ne lis rien d'autre, lis celles-ci. Le « pourquoi » se déplie
        sous chacune.</p>
    </div>
    <ol class="brief-list">
      ${items.map((i) => `<li class="bi">
        <div class="bi-big"><span class="bi-v">${esc(i.big)}</span><span class="bi-u mono">${esc(i.unit)}</span></div>
        <div class="bi-main">
          <h3>${i.title}</h3>
          <p class="bi-b">${i.body}</p>
          ${i.proof ? `<details class="bi-why"><summary>pourquoi</summary>
            <p class="bi-p">${i.proof}</p></details>` : ''}
        </div>
      </li>`).join('')}
    </ol>
  </section>`;
}

function cockpit(plan) {
  const S = plan.segments || [];
  if (!S.length) return '';
  const tile = (k, label, hint) => `<div class="tl" data-tile="${k}">
    <p class="tl-l mono">${esc(label)}</p>
    <p class="tl-v" id="tv-${k}">—</p>
    <p class="tl-h mono" id="th-${k}">${esc(hint || '')}</p></div>`;
  return `<section class="cock" id="cock">
    <div class="cock-head">
      <p class="eyebrow">Poste de pilotage</p>
      <p class="cock-hint mono" id="cockHint">Balaye le profil, ou fais glisser le curseur du temps</p>
    </div>
    <div class="chartwrap" id="chartWrap"></div>
    <label class="scrub">
      <span class="mono">Temps écoulé</span>
      <input type="range" id="scrub" min="0" max="1000" step="1" value="0" aria-label="Avancer dans la course">
    </label>
    <div class="tiles">
      ${tile('km', 'Kilomètre', 'depuis le départ')}
      ${tile('alt', 'Altitude', 'mètres')}
      ${tile('slope', 'Pente', 'sur 500 m')}
      ${tile('mode', 'Consigne', '')}
      ${tile('pace', 'Allure', 'par kilomètre')}
      ${tile('vam', 'Ascension', 'mètres par heure')}
      ${tile('clock', 'Heure', 'au mur')}
      ${tile('temp', 'Température', 'ressentie au point')}
    </div>
    <p class="cock-gear mono" id="cockGear"></p>
  </section>`;
}

// Le générateur écrit les cumuls de deux façons : « 12:53:35 » pour les tronçons,
// « 12h53 » pour les ravitaillements. Un parseur qui n'en connaît qu'une produit
// des NaN silencieux jusque dans les totaux affichés.
function hmsToSec(c) {
  const t = String(c ?? '').trim();
  let m = t.match(/^(\d+):(\d{1,2})(?::(\d{1,2}))?$/);
  if (m) return (+m[1]) * 3600 + (+m[2]) * 60 + (+(m[3] || 0));
  m = t.match(/^(\d+)h(\d{1,2})?$/i);
  if (m) return (+m[1]) * 3600 + (+(m[2] || 0)) * 60;
  return NaN;
}

/* ---------- Nutrition : ce qu'il faut emporter, portion par portion ---------- */
// Repères d'ultra-endurance : 60 à 90 g de glucides par heure, et un besoin en
// liquide qui grimpe avec la chaleur. On les applique aux durées réelles du plan.
const CARB_PER_H = 65;
const fluidPerH = (t) => Math.round(450 + Math.max(0, t - 15) * 35);

function profile(plan, interactive) {
  const segs = plan.segments || [];
  const pts = plan.profile || [];
  if (pts.length < 2) return '';
  const W = 1000, PH = 210, P = { l: 48, r: 14, t: 14, b: 26 };
  const H = P.t + PH + P.b;

  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x1 = Math.max(...xs);
  // Échelle en valeurs rondes — mais pas au prix d'un profil écrasé : arrondir
  // 805–2529 m aux 500 m donnerait un axe 500–3000, où les données n'occupent
  // que deux tiers de la hauteur. On retient le plus grand pas qui ne gonfle
  // pas l'étendue de plus d'un quart.
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const step = [500, 250, 200, 100, 50].find((k) =>
    (Math.ceil(hi / k) * k - Math.floor(lo / k) * k) <= span * 1.25) || 50;
  const y0 = Math.floor(lo / step) * step;
  const y1 = Math.ceil(hi / step) * step;
  const X = (v) => P.l + v / (x1 || 1) * (W - P.l - P.r);
  const Y = (v) => P.t + PH - (v - y0) / (y1 - y0 || 1) * PH;

  const bands = (plan.windows || []).filter((w) => w.light === 'nuit').map((w) =>
    `<rect x="${X(w.km0).toFixed(1)}" y="${P.t}" width="${Math.max(0.5, X(w.km1) - X(w.km0)).toFixed(1)}"
       height="${PH}" class="pf-night"/>`).join('');

  const cols = segs.map((s) => `<rect x="${X(s.km0).toFixed(1)}" y="${Y(s.alt).toFixed(1)}"
      width="${Math.max(0.7, X(s.km1) - X(s.km0)).toFixed(1)}" height="${(P.t + PH - Y(s.alt)).toFixed(1)}"
      class="t-${terrainOf(s.slope)}"/>`).join('');

  const ticks = [];
  for (let v = y0; v <= y1; v += step) {
    ticks.push(`<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="pf-grid"/>
      <text x="${P.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" class="pf-lab">${v}</text>`);
  }

  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join('');
  const marks = (plan.aid || []).filter((a) => a.km > 1 && a.km < x1 - 1).map((a) =>
    `<line x1="${X(a.km).toFixed(1)}" x2="${X(a.km).toFixed(1)}" y1="${P.t}" y2="${P.t + PH}" class="pf-aid"/>`).join('');

  const xlab = [0, .25, .5, .75, 1].map((f) => {
    const v = x1 * f;
    return `<text x="${X(v).toFixed(1)}" y="${H - 8}" class="pf-lab"
      text-anchor="${f === 0 ? 'start' : f === 1 ? 'end' : 'middle'}">${Math.round(v)} km</text>`;
  }).join('');

  const geo = JSON.stringify({ w: W, l: P.l, r: P.r, t: P.t, ph: PH, y0, y1 });
  const cursor = interactive
    ? `<line id="curLine" x1="${P.l}" x2="${P.l}" y1="${P.t}" y2="${P.t + PH}" class="cur"/>
       <circle id="curDot" cx="${P.l}" cy="${P.t}" r="5" class="cur-dot"/>
       <rect id="curHit" x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${PH}" fill="transparent"/>`
    : '';
  return `<div class="pf${interactive ? ' pf-live' : ''}">
    <svg viewBox="0 0 ${W} ${H}" data-geo='${geo}' role="img"
         aria-label="Profil du parcours">${bands}${ticks.join('')}${cols}<path d="${line}" class="pf-line"/>${marks}${xlab}${cursor}</svg>
    <div class="pf-legend">
      <span class="lg"><i class="sw t-raide"></i>raide · 12 % et plus</span>
      <span class="lg"><i class="sw t-montee"></i>montée</span>
      <span class="lg"><i class="sw t-plat"></i>plat</span>
      <span class="lg"><i class="sw t-descente"></i>descente</span>
      <span class="lg"><i class="sw pf-nightsw"></i>nuit</span>
    </div>
  </div>`;
}

/* ---------- La distribution des chronos simulés ---------- */
function windows(plan) {
  if (!(plan.windows || []).length) return '';
  const rows = plan.windows.map((w) => `<tr class="lt-${w.light === 'nuit' ? 'night' : w.light === 'jour' ? 'day' : 'dusk'}">
    <td class="nowrap">${LIGHT_ICON[w.light] || ''} ${esc(w.light)}</td>
    <td class="mono nowrap">km ${km1(w.km0)} à ${km1(w.km1)}</td>
    <td class="mono num">${km1(w.km1 - w.km0)} km</td>
    <td class="mono num">${esc(w.start)} → ${esc(w.end)}</td>
    <td class="mono num">${degC(w.tmin)} / ${degC(w.tmax)}</td>
  </tr>`).join('');
  const night = plan.windows.filter((w) => w.light === 'nuit').reduce((a, w) => a + w.km1 - w.km0, 0);
  return `<section class="pl-block">
    <h2 class="pl-h">Où il fera nuit</h2>
    <p class="sub pl-wide">Calculé sur la position réelle du soleil à ta latitude, d'après tes heures de passage.
      Au total, ${km1(night)} km de nuit, frontale obligatoire.</p>
    <div class="tw"><table class="tbl">
      <thead><tr><th>Lumière</th><th>Portion</th><th class="num">Distance</th><th class="num">Heures</th><th class="num">Température</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
  </section>`;
}

/* ---------- Températures heure par heure ---------- */
function hours(plan) {
  if (!(plan.hours || []).length) return '';
  const rows = plan.hours.map((h) => `<tr>
    <td class="mono nowrap">${esc(h.h)}</td>
    <td class="mono nowrap">km ${km1(h.km0)} à ${km1(h.km1)}</td>
    <td class="mono num">${h.alt} m</td>
    <td class="mono num strong">${degC(h.tmin)}${Math.round(h.tmax) !== Math.round(h.tmin) ? ` → ${degC(h.tmax)}` : ''}</td>
    <td class="nowrap">${LIGHT_ICON[h.light] || ''} ${esc(h.light)}</td>
  </tr>`).join('');
  return `<section class="pl-block">
    <h2 class="pl-h">Température, heure par heure</h2>
    <p class="sub pl-wide">La prévision est donnée en vallée ; on la corrige de l'altitude du point où tu seras
      (−6,5 °C par 1000 m de montée). C'est pourquoi les cols de nuit descendent sous zéro.</p>
    <div class="tw tw-tall"><table class="tbl">
      <thead><tr><th>Heure</th><th>Tu seras</th><th class="num">Altitude</th><th class="num">Température</th><th>Lumière</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
  </section>`;
}

/* ---------- Ravitaillements ---------- */
function aidTable(plan) {
  if (!(plan.aid || []).length) return '';
  const rows = plan.aid.map((a) => `<tr>
    <td class="mono nowrap">${km1(a.km)}</td>
    <td>${esc(a.name)}</td>
    <td class="mono num">${a.alt} m</td>
    <td class="mono num strong">${esc(fr(a.eta))}</td>
    <td class="mono num">${esc(a.cumul)}</td>
    <td class="mono num">${degC(a.temp)}</td>
    <td>${(a.gear || []).map((g) => `<span class="tag">${esc(g)}</span>`).join(' ') || '<span class="muted">—</span>'}</td>
  </tr>`).join('');
  return `<section class="pl-block">
    <h2 class="pl-h">Ravitaillements</h2>
    <div class="tw"><table class="tbl tbl-aid">
      <thead><tr><th>km</th><th>Point</th><th class="num">Alt.</th><th class="num">Passage</th>
        <th class="num">Cumul</th><th class="num">Temp.</th><th>À sortir du sac</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
  </section>`;
}

/* ---------- Le parcours découpé là où il change vraiment ---------- */
const CLS_LABEL = { raide: 'raide', montee: 'montée', plat: 'plat', descente: 'descente', plongeon: 'plongeon' };

/* ---------- Le curseur qui relie tout ---------- */
let goToKm = null;   // posé par wireCockpit, utilisé par les clics sur le tableau
let redrawCockpit = () => {};

function wireCockpit(plan) {
  const wrap = $('chartWrap'), scrub = $('scrub');
  if (!wrap || !scrub) return;
  wrap.innerHTML = profile(plan, true);
  const svg = wrap.querySelector('svg');
  if (!svg || !svg.dataset.geo) return;
  const S = plan.segments || [];
  const totalKm = S[S.length - 1].km1;
  const geo = JSON.parse(svg.dataset.geo);          // posé par profile()
  const cur = svg.querySelector('#curLine');
  const dot = svg.querySelector('#curDot');
  const set = (id, v) => { const e = $(`tv-${id}`); if (e) e.textContent = v; };
  const hint = (id, v) => { const e = $(`th-${id}`); if (e) e.textContent = v; };

  const show = (i) => {
    const s = S[Math.max(0, Math.min(S.length - 1, i))];
    const x = geo.l + (s.km1 / totalKm) * (geo.w - geo.l - geo.r);
    const y = geo.t + geo.ph - (s.alt - geo.y0) / (geo.y1 - geo.y0 || 1) * geo.ph;
    cur.setAttribute('x1', x); cur.setAttribute('x2', x);
    dot.setAttribute('cx', x); dot.setAttribute('cy', y);
    set('km', km1(s.km1)); hint('km', `sur ${km1(totalKm)} km`);
    set('alt', s.alt); hint('alt', `${s.up ? `+${s.up}` : '0'} m sur ce tronçon`);
    set('slope', `${s.slope > 0 ? '+' : ''}${km1(s.slope)} %`);
    hint('slope', CLS_LABEL[terrainOf(s.slope)] || '');
    set('mode', s.mode === 'marche' ? (s.poles ? 'Marche · bâtons' : 'Marche') : 'Course');
    hint('mode', `seuil du moment ${km1(s.thr)} %`);
    set('pace', s.pace); hint('pace', `${km1(s.kmh)} km/h`);
    set('vam', s.vam ? s.vam : '—'); hint('vam', s.vam ? 'mètres par heure' : 'pas de montée ici');
    set('clock', s.clock); hint('clock', `cumul ${s.cumul.slice(0, 5)}`);
    set('temp', degC(s.temp)); hint('temp', s.light);
    const gear = [];
    if (s.light === 'nuit') gear.push('frontale');
    if (s.temp <= 8) gear.push('gants');
    if (s.temp <= 4) gear.push('veste chaude');
    if (s.temp <= 0) gear.push('bonnet');
    if (s.poles) gear.push('bâtons sortis');
    const g = $('cockGear');
    if (g) g.innerHTML = gear.length
      ? `À sortir ici : ${gear.map((x) => `<span class="tag">${esc(x)}</span>`).join(' ')}`
      : '';
    const near = (plan.aid || []).filter((a) => a.km <= s.km1).pop();
    const next = (plan.aid || []).find((a) => a.km > s.km1);
    const ch = $('cockHint');
    if (ch) ch.textContent = next
      ? `Prochain ravitaillement : ${next.name} dans ${km1(next.km - s.km1)} km`
      : `Dernier passage : ${near ? near.name : ''}`;
    scrub.value = Math.round(i / (S.length - 1) * 1000);
  };

  // Un clic sur une portion du tableau amène le curseur au bon endroit.
  goToKm = (km) => {
    const i = S.findIndex((x) => x.km1 >= km);
    if (i >= 0) { show(i); $('cock')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  };
  redrawCockpit = () => show(Math.round(+scrub.value / 1000 * (S.length - 1)));

  const fromX = (clientX) => {
    const r = svg.getBoundingClientRect();
    const f = (clientX - r.left) / r.width * geo.w;
    const km = (f - geo.l) / (geo.w - geo.l - geo.r) * totalKm;
    return S.findIndex((s) => s.km1 >= km);
  };
  const onMove = (e) => {
    const cx = e.touches ? e.touches[0].clientX : e.clientX;
    const i = fromX(cx);
    if (i >= 0) show(i);
  };
  const hit = svg.querySelector('#curHit') || svg;
  hit.addEventListener('mousemove', onMove);
  hit.addEventListener('touchmove', onMove, { passive: true });
  hit.addEventListener('click', onMove);
  scrub.addEventListener('input', () => show(Math.round(+scrub.value / 1000 * (S.length - 1))));
  show(0);
}

/* ---------- Export vers la montre ----------
   Le plan reste chiffré sur le serveur ; le fichier est fabriqué ici, dans le
   navigateur, à partir des données déjà déchiffrées. Rien ne repart en ligne. */
function toGpx(plan) {
  const esx = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]));
  const wpts = [];
  for (const a of plan.aid || []) {
    if (a.lat == null || a.lon == null) continue;
    wpts.push(`<wpt lat="${a.lat}" lon="${a.lon}"><ele>${a.alt ?? 0}</ele>
  <name>${esx(a.name)}</name>
  <desc>Passage visé ${esx(a.cumul || '')} · ${esx(fr(a.eta))} · ${a.temp ?? '?'} °C · ${esx(a.light || '')}${(a.gear || []).length ? ' · ' + esx(a.gear.join(', ')) : ''}</desc>
  <sym>Flag</sym></wpt>`);
  }
  for (const s of plan.sections || []) {
    if (s.lat == null || s.lon == null) continue;
    wpts.push(`<wpt lat="${s.lat}" lon="${s.lon}"><ele>${s.alt0 ?? 0}</ele>
  <name>km ${s.km0} ${CLS_LABEL[s.cls] || s.cls} ${s.slope > 0 ? '+' : ''}${s.slope}%</name>
  <desc>${s.dist} km · ${s.up ? `+${s.up} m · ` : ''}${s.pace}/km${s.vam ? ` · ${s.vam} m/h` : ''} · ${s.walkShare}% marche${s.poles ? ' · bâtons' : ''} · cumul ${esx(s.cumul || '')}</desc>
  <sym>Waypoint</sym></wpt>`);
  }
  // La trace complète si elle est là, sinon le repli sur les tronçons de 500 m.
  const trk = (plan.track && plan.track.length
    ? plan.track.map(([la, lo, el]) => `<trkpt lat="${la}" lon="${lo}"><ele>${el}</ele></trkpt>`)
    : (plan.segments || []).filter((s) => s.lat != null)
        .map((s) => `<trkpt lat="${s.lat}" lon="${s.lon}"><ele>${s.alt}</ele></trkpt>`)
  ).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Hold" xmlns="http://www.topografix.com/GPX/1/1">
<metadata><name>${esx(plan.race || 'Course')} · ${esx(plan.runner || '')} · objectif ${esx(plan.goal || '')}</name></metadata>
${wpts.join('\n')}
<trk><name>${esx(plan.race || 'Course')}</name><trkseg>
${trk}
</trkseg></trk>
</gpx>`;
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function toCsv(plan) {
  const head = ['km_debut', 'km_fin', 'distance_km', 'pente_pct', 'terrain', 'denivele_pos_m',
    'allure_min_km', 'vam_m_h', 'part_marche_pct', 'batons', 'cumul', 'heure', 'temp_c', 'lumiere'];
  const rows = (plan.sections || []).map((s) => [s.km0, s.km1, s.dist, s.slope, s.cls, s.up,
    s.pace, s.vam ?? '', s.walkShare, s.poles ? 'oui' : 'non', s.cumul, s.clock,
    Math.round((s.tmin + s.tmax) / 2), s.light]);
  return [head, ...rows].map((r) => r.map((c) => {
    const v = String(c ?? '');
    return /[",;\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  }).join(';')).join('\n');
}

function exporter(plan) {
  const n = (plan.aid || []).filter((a) => a.lat != null).length
    + (plan.sections || []).filter((s) => s.lat != null).length;
  return `<section class="pl-block">
    <h2 class="pl-h">Emporter le plan</h2>
    <p class="sub pl-wide">Le fichier est fabriqué ici, dans ton navigateur, à partir du plan
      déchiffré : il ne repasse jamais par le serveur. Le GPX contient la trace et
      ${n} points nommés (chaque ravitaillement et chaque changement de terrain),
      avec l'heure de passage visée, l'allure et le matériel à sortir.</p>
    <div class="f-actions">
      <button type="button" class="btn" id="dlGpx">Télécharger le GPX</button>
      <button type="button" class="btn btn-ghost" id="dlCsv">Télécharger le tableau (CSV)</button>
      <button type="button" class="btn btn-ghost" id="doPrint">Imprimer</button>
    </div>
    <p class="hint" id="dlHint">Le GPX s'importe sur Garmin Connect, Coros, Suunto et Strava.
      Les points nommés apparaissent comme alertes au fil du parcours.
      Le FIT n'est pas proposé : son format binaire est propre à Garmin, et un fichier
      mal formé est refusé par la montre sans message. Le GPX, lui, passe partout.</p>
  </section>`;
}

/* ---------- Assemblage : un onglet à la fois ----------
   Tout afficher d'un bloc noyait l'essentiel. Chaque onglet répond à une
   seule question, et le parcours est celui qui s'ouvre. */
// Quatre onglets, dans l'ordre où un coureur se pose les questions : qu'est-ce
// que je fais, quand est-ce que ça devient dur, qu'est-ce qui peut déraper, et
// d'où ça sort. Tout ce qui relève de la méthode part au dernier : c'est vrai,
// c'est vérifiable, mais ça n'aide pas à courir.
/* ---------- Modélisation et pacing ----------
   Un seul onglet pour une seule question : à quelle heure dois-je passer, et
   comment. Les éditions précédentes donnent la fenêtre, les séances placent la
   cible dedans, et chaque portion entre deux ravitaillements s'ouvre sur ce
   qu'il faut savoir pour la courir : profil, rythme, météo, matériel.
   La nutrition n'y figure pas : on n'a aucune mesure pour la calculer, et on
   ne l'invente pas. */
const hmin = (x) => `${Math.floor(x / 3600)}h${String(Math.round(x % 3600 / 60)).padStart(2, '0')}`;
const monte = (sg) => (sg.cls === 'raide' || sg.cls === 'montee') && sg.vam;
const rythme = (sg) => monte(sg) ? `${sg.vam} m/h` : `${sg.pace} /km`;

// Les aptitudes tirées des séances, en une ligne : ce qui cale la cible.
function aptitudes(plan) {
  const m = plan.model || {}, g = plan.gam || plan.athlete || {}, sp = g.speed || {};
  const S = plan.sections || [];
  const v = S.filter(monte);
  const vam = v.length ? Math.round(v.reduce((a, sg) => a + sg.vam * sg.up, 0) / v.reduce((a, sg) => a + sg.up, 0)) : null;
  const statut = (k) => ((m.params || {})[k] || '').startsWith('mesur') ? 'mesuré sur toi' : 'valeur de référence';
  const item = (v_, l, st) => v_ == null ? '' : `<div class="apt-i"><p class="apt-v">${v_}</p>
    <p class="apt-l">${esc(l)}</p><p class="apt-s mono">${esc(st)}</p></div>`;
  const items = [
    item(m.walkThr != null ? `${km1(m.walkThr)} %` : null, 'pente où tu passes en marche', statut('seuil de marche')),
    item(vam ? `${vam} m/h` : null, 'vitesse ascensionnelle', 'calculée sur ton plan'),
    item(m.fatigue != null ? `−${km1(m.fatigue)} %` : null, 'de vitesse perdue par heure', statut('durabilité')),
    item(sp.runFlat ? `${km1(sp.runFlat)} km/h` : null, 'en course sur le plat', statut('rapport course/marche')),
  ].join('');
  return items ? `<div class="apt">${items}</div>` : '';
}

// Le profil d'une portion, en petit : l'altitude, et en rouge ce qui se marche.
function miniProfil(segs, debut, fin) {
  if (segs.length < 2) return '';
  const W = 640, H = 150, P = { l: 46, r: 10, t: 12, b: 24 };
  const k0 = debut ?? segs[0].km0, k1 = fin ?? segs[segs.length - 1].km1;
  const alts = segs.map((sg) => sg.alt);
  const lo = Math.min(...alts) - 20, hi = Math.max(...alts) + 20;
  const X = (k) => P.l + (k - k0) / (k1 - k0 || 1) * (W - P.l - P.r);
  const Y = (a) => P.t + (hi - a) / (hi - lo || 1) * (H - P.t - P.b);
  const pts = segs.map((sg) => [(sg.km0 + sg.km1) / 2, sg.alt]);
  const ligne = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join('');
  const aire = `${ligne}L${X(pts[pts.length - 1][0]).toFixed(1)} ${H - P.b}L${X(pts[0][0]).toFixed(1)} ${H - P.b}Z`;
  const marche = segs.map((sg, i) => sg.mode === 'marche' && i
    ? `<path d="M${X(pts[i - 1][0]).toFixed(1)} ${Y(pts[i - 1][1]).toFixed(1)}L${X(pts[i][0]).toFixed(1)} ${Y(pts[i][1]).toFixed(1)}" class="mp-marche"/>` : '').join('');
  return `<svg class="mp" viewBox="0 0 ${W} ${H}" role="img" aria-label="Profil de la portion">
    <path d="${aire}" class="mp-aire"/><path d="${ligne}" class="mp-ligne"/>${marche}
    <text x="${P.l - 8}" y="${Y(Math.max(...alts)) + 4}" text-anchor="end" class="mp-lab">${Math.max(...alts)} m</text>
    <text x="${P.l - 8}" y="${Y(Math.min(...alts)) + 4}" text-anchor="end" class="mp-lab">${Math.min(...alts)} m</text>
    <text x="${P.l}" y="${H - 6}" class="mp-lab">km ${km1(k0)}</text>
    <text x="${W - P.r}" y="${H - 6}" text-anchor="end" class="mp-lab">km ${km1(k1)}</text>
  </svg>`;
}

// Les portions stratégiques : d'un ravitaillement au suivant, là où l'on vérifie son temps.
function portions(plan) {
  const A = plan.aid || [], S = plan.segments || [], T = plan.sections || [];
  const E = plan.editions, P = (E && E.points) || [];
  const repere = (a) => P.find((p) => p.name === a.name) || P.find((p) => Math.abs(p.km - a.km) < 0.6);
  const out = [];
  for (let i = 1; i < A.length; i++) {
    const a = A[i - 1], b = A[i];
    const segs = S.filter((sg) => sg.km0 >= a.km - 0.01 && sg.km0 < b.km);
    if (!segs.length) continue;
    const t0 = hmsToSec(a.cumul) || 0, t1 = hmsToSec(b.cumul);
    const temps = segs.map((sg) => sg.temp);
    const ed = repere(b), edAv = i > 1 ? repere(a) : { med: 0 };
    out.push({
      n: out.length + 1, a, b, segs,
      secs: T.filter((sg) => sg.km0 < b.km - 0.05 && sg.km1 > a.km + 0.05),
      up: Math.round(segs.reduce((s, sg) => s + (sg.up || 0), 0)),
      down: Math.round(segs.reduce((s, sg) => s + (sg.down || 0), 0)),
      altMax: Math.max(...segs.map((sg) => sg.alt)), pmax: Math.max(...segs.map((sg) => sg.slope)),
      marche: segs.filter((sg) => sg.mode === 'marche').reduce((s, sg) => s + sg.km1 - sg.km0, 0),
      batons: segs.some((sg) => sg.poles),
      t0, t1, tmin: Math.min(...temps), tmax: Math.max(...temps),
      nuit: segs.filter((sg) => sg.light === 'nuit').length / segs.length,
      ed, medTroncon: ed && edAv ? ed.med - edAv.med : null,
    });
  }
  return out;
}

function pacing(plan) {
  const E = plan.editions, P = (E && E.points) || [];
  const PO = portions(plan);
  if (!PO.length) return '';

  const graphe = P.length ? chart({
    title: 'Ton temps face au temps habituel',
    note: `Écart, en minutes, au finisher médian de ${E.target}. Au-dessus tu es plus lent que lui, en dessous plus rapide.`,
    height: 230, x0: 0, xTicks: 8, xFmt: (v) => `km ${Math.round(v)}`, yFmt: (v) => `${v > 0 ? '+' : ''}${Math.round(v)} min`,
    series: [
      { pts: P.map((p) => [p.km, (p.hi - p.med) / 60, (p.lo - p.med) / 60]), kind: 'band', cls: 'c-bandfill',
        label: '8 finishers sur 10', swatch: 'c-bandfill' },
      { pts: P.map((p) => [p.km, 0]), kind: 'line', cls: 'c-grey', label: 'temps médian habituel' },
      ...(P[0].mcLo ? [{ pts: P.map((p) => [p.km, (p.mcHi - p.med) / 60, (p.mcLo - p.med) / 60]), kind: 'band',
        cls: 'c-redband', label: 'ta fourchette simulée', swatch: 'c-redband' }] : []),
      { pts: P.map((p) => [p.km, (p.cible - p.med) / 60]), kind: 'line', cls: 'c-red', label: 'ton temps' },
    ],
  }) : '';
  const M = E && E.simulation;
  const chances = M ? `<p class="ch-p"><span class="ch-pv">${hmin(M.lo)} à ${hmin(M.hi)}</span>
      ton arrivée, 8 fois sur 10, sur ${(E.draws || 20000).toLocaleString('fr-FR')} courses simulées.</p>
    <p class="ch-p"><span class="ch-pv">${Math.round(M.chance * 10)} sur 10</span>
      de ces courses finissent en ${esc(E.target)} ou moins. Médiane : ${hmin(M.med)}.</p>` : '';

  const lumiere = (po) => po.nuit > 0.9 ? 'de nuit' : po.nuit < 0.1 ? 'de jour' : 'en partie de nuit';
  const cartes = PO.map((po) => {
    const fen = po.ed ? `fenêtre ${hmin(po.ed.lo)} à ${hmin(po.ed.hi)}` : '';
    const sim = po.ed && po.ed.mcLo ? `${hmin(po.ed.mcLo)} à ${hmin(po.ed.mcHi)}` : '';
    const rythmes = po.secs.map((sg) => `<li><span class="mono">km ${km1(Math.max(sg.km0, po.a.km))} à ${km1(Math.min(sg.km1, po.b.km))}</span>
      <span class="tag tg-${sg.cls}">${CLS_LABEL[sg.cls] || sg.cls}</span>
      <span class="mono muted">${sg.slope > 0 ? '+' : ''}${km1(sg.slope)} %</span>
      <span class="po-ry">${esc(rythme(sg))}</span>${sg.walkShare >= 50 ? `<span class="po-m mono">${sg.walkShare === 100
        ? 'en marche' : `${sg.walkShare} % marché`}${sg.poles ? ', bâtons' : ''}</span>` : ''}</li>`).join('');
    const gearA = (po.a.gear || []).length ? po.a.gear.map((g) => `<span class="tag">${esc(g)}</span>`).join(' ') : 'rien de particulier';
    const fig = (l, v) => `<div><p class="po-fl mono">${l}</p><p class="po-fv">${v}</p></div>`;
    return `<details class="po">
      <summary>
        <span class="po-n mono">${String(po.n).padStart(2, '0')}</span>
        <span class="po-t">${esc(po.a.name)} <span class="po-fl2">→</span> ${esc(po.b.name)}
          <span class="po-k mono">km ${km1(po.a.km)} à ${km1(po.b.km)} · +${po.up} m · −${po.down} m</span></span>
        <span class="po-c"><span class="po-v">${po.t1 ? hmin(po.t1) : ''}</span><span class="po-w mono">${fen}</span></span>
      </summary>
      <div class="po-d">
        ${miniProfil(po.segs, po.a.km, po.b.km)}
        <div class="po-figs">
          ${fig('Distance', `${km1(po.b.km - po.a.km)} km`)}
          ${fig('Dénivelé', `+${po.up} m · −${po.down} m`)}
          ${fig('Point haut', `${po.altMax} m`)}
          ${fig('Pente max', `${km1(po.pmax)} %`)}
          ${fig('Ton temps', po.t1 ? hmin(po.t1 - po.t0) : '')}
          ${po.medTroncon ? fig('Temps habituel', hmin(po.medTroncon)) : ''}
          ${sim ? fig('Passage simulé', sim) : ''}
        </div>
        <h4 class="po-h">Ton rythme</h4>
        <ul class="po-ry-l">${rythmes}</ul>
        ${po.marche > 0.2 ? `<p class="po-p">${km1(po.marche)} km en marche${po.batons ? ', bâtons sortis' : ''}.</p>` : ''}
        <h4 class="po-h">Météo</h4>
        <p class="po-p">De ${esc(fr(po.a.eta))} à ${esc(fr(po.b.eta))}, ${lumiere(po)}.
          ${Math.round(po.tmin) === Math.round(po.tmax) ? degC(po.tmin) : `Entre ${Math.round(po.tmin)} et ${degC(po.tmax)}`}
          selon l'altitude.</p>
        <h4 class="po-h">Matériel</h4>
        <p class="po-p">Au départ de ${esc(po.a.name)} : ${gearA}</p>
        <p class="po-p">Ravitaillement à l'arrivée, ${esc(po.b.name)}, vers ${esc(fr(po.b.eta))}.</p>
      </div>
    </details>`;
  }).join('');

  return `<section class="pl-block">
    <h2 class="pl-h">Modélisation et pacing</h2>
    <p class="sub pl-wide">${P.length ? `On a repris ${E.runners.toLocaleString('fr-FR')} finishers de l'UTMB, de ${E.years[0]}
      à ${E.years[1]}. Ceux qui ont fini dans l'heure avant ${esc(E.target)} donnent le temps habituel et la fenêtre.
      ` : ''}Tes séances placent ton temps à l'intérieur. Sur la première moitié, il peut être plus lent que la
      fenêtre : partir prudemment n'est pas une faute. La seconde moitié, elle, tient dans la fenêtre. Dans les
      descentes, tu restes un peu en dessous de ton rythme : on n'y rattrape pas de temps, on préserve les cuisses.</p>
    ${aptitudes(plan)}
    ${graphe}
    ${chances ? `<div class="ch-ps">${chances}</div>` : ''}
    <h3 class="pl-h3">Les temps à respecter</h3>
    <p class="sub">D'un ravitaillement au suivant. L'heure est ton temps de course à l'arrivée de la portion.
      Touche une portion pour en voir le détail.</p>
    <div class="pos">${cartes}</div>
    ${P.length ? `<p class="hint">Monte-Carlo portion par portion : ${(E.draws || 20000).toLocaleString('fr-FR')} courses
      simulées d'un ravitaillement au suivant. À chaque portion, on tire un vrai coureur des éditions passées
      qui venait de courir la portion précédente au même rythme que la course simulée, et on applique ce qu'il a
      fait ensuite à ton temps prévu. Les archives ne contiennent que des finishers : les abandons n'y sont pas.
      Fenêtre : 1 finisher sur 10 passait plus tôt, 1 sur 10 plus tard. Source : ${esc(E.source || 'archives LiveTrail')}.</p>` : ''}
  </section>`;
}

const TABS = [
  ['course', 'Ma course'],
  ['pacing', 'Modélisation et pacing'],
  ['heures', 'Météo et nuit'],
];

function render(plan) {
  const m = plan.model || {};
  const night = (plan.windows || []).filter((w) => w.light === 'nuit').reduce((a, w) => a + w.km1 - w.km0, 0);
  const kpi = (l, v, h) => v ? `<div class="hk"><p class="hk-l mono">${esc(l)}</p>
    <p class="hk-v">${esc(v)}</p><p class="hk-h mono">${esc(h || '')}</p></div>` : '';

  const body = {
    course: `${cockpit(plan)}${aidTable(plan)}${briefing(plan)}${exporter(plan)}`,
    pacing: pacing(plan),
    heures: `${windows(plan)}${hours(plan)}`,
  };
  const tabs = TABS.filter(([k]) => (body[k] || '').trim());

  $('planRoot').innerHTML = `
    <header class="pl-head">
      <p class="eyebrow">${esc(plan.runner || '')} · plan de course</p>
      <h1 class="title">${esc(plan.race || 'Ta course')}<br><span class="soft">${esc(fr(plan.date))}</span></h1>
    </header>
    <div class="hkpis">
      ${kpi('Objectif', plan.goal, (() => {
        const vis = hmsToSec(plan.projected), obj = hmsToSec(plan.goal);
        return vis && obj && obj - vis >= 300 ? `plan calé sur ${hmin(vis)}, ${Math.round((obj - vis) / 60)} min de marge`
          : plan.start ? `départ ${plan.start}` : '';
      })())}
      ${kpi('Distance', plan.distanceKm ? `${km1(plan.distanceKm)} km` : '', plan.elevationM ? `${plan.elevationM} m de D+` : '')}
      ${kpi('Dont marche', m.walkKm != null ? `${km1(m.walkKm)} km` : '', m.runKm != null ? `${km1(m.runKm)} km courus` : '')}
      ${kpi('Dont nuit', night ? `${km1(night)} km` : '', 'frontale obligatoire')}
    </div>
    <div class="tabs" role="tablist">
      ${tabs.map(([k, l], i) => `<button type="button" role="tab" class="tb" data-tab="${k}"
        aria-selected="${i === 0}">${esc(l)}</button>`).join('')}
    </div>
    ${tabs.map(([k], i) => `<div class="tabpane" data-pane="${k}"${i ? ' hidden' : ''}>${body[k]}</div>`).join('')}
    <p class="hint pl-foot">Plan établi par Hold · Lilian Mathien. Révisé le ${esc(plan.revised || '—')}.
      Ce document décrit une cible, pas une garantie : le jour J, tes sensations priment.</p>`;

  // Onglets
  const panes = Array.from(document.querySelectorAll('[data-pane]'));
  const btns = Array.from(document.querySelectorAll('.tb'));
  btns.forEach((b) => b.addEventListener('click', () => {
    btns.forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    panes.forEach((p) => { p.hidden = p.dataset.pane !== b.dataset.tab; });
    if (b.dataset.tab === 'course') redrawCockpit();
  }));

  // Poste de pilotage. Isolé : s'il tombe, le reste du rapport reste lisible.
  try { wireCockpit(plan); } catch (e) { console.error('Hold : poste de pilotage', e); }

  // Chaque ligne de portion amène le curseur au kilomètre correspondant.
  for (const tr of document.querySelectorAll('.clickrow')) {
    const go = () => goToKm && goToKm(parseFloat(tr.dataset.km));
    tr.addEventListener('click', go);
    tr.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(); }
    });
  }

  // Exports, fabriqués dans le navigateur à partir du plan déchiffré.
  const slug = `${plan.race || 'course'}-${plan.runner || ''}`.toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  $('dlGpx')?.addEventListener('click', () => download(`${slug}.gpx`, toGpx(plan), 'application/gpx+xml'));
  $('dlCsv')?.addEventListener('click', () => download(`${slug}.csv`, toCsv(plan), 'text/csv;charset=utf-8'));
  $('doPrint')?.addEventListener('click', () => window.print());

  $('planRoot').hidden = false;
  $('gate').hidden = true;
  $('navWho').textContent = `${plan.runner || ''} · ${plan.race || ''}`;
  document.title = `Hold · ${plan.race || 'Plan'} · ${plan.runner || ''}`;
}

/* ---------- L'espace : une stratégie, des documents, ou les deux ----------
   Les premiers plans publiés ne contiennent qu'une stratégie de course, à nu.
   Ceux que fabrique la page admin l'enveloppent avec les documents du coach.
   On ramène les deux formes à la même, pour que l'affichage n'ait qu'un cas. */
function espaceDe(contenu) {
  if (contenu && contenu.hold === 2) {
    return { coureur: contenu.coureur || '', titre: contenu.titre || '',
      plan: contenu.plan || null, fichiers: Array.isArray(contenu.fichiers) ? contenu.fichiers : [],
      modifie: contenu.modifie || '' };
  }
  return { coureur: contenu?.runner || '', titre: contenu?.race || '', plan: contenu,
    fichiers: [], modifie: '' };
}

const taille = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1).replace('.', ',')} Mo`
  : `${Math.max(1, Math.round(n / 1024))} Ko`;

function documents(fichiers) {
  if (!fichiers.length) return '';
  return `<section class="docs" aria-labelledby="docsT">
    <p class="eyebrow" id="docsT">Tes documents</p>
    <ul class="docs-l">${fichiers.map((f, i) => `<li>
      <span class="docs-n">${esc(f.nom)}</span>
      <span class="docs-t mono">${esc(taille(f.taille || 0))}</span>
      <button type="button" class="btn btn-sm btn-ghost" data-doc="${i}">Télécharger</button>
    </li>`).join('')}</ul>
  </section>`;
}

// Le fichier est déjà là, déchiffré en mémoire : on le rend au coureur sans
// rien redemander au réseau.
function brancheDocuments(fichiers) {
  for (const b of document.querySelectorAll('[data-doc]')) {
    b.addEventListener('click', () => {
      const f = fichiers[Number(b.dataset.doc)];
      if (!f) return;
      const octets = b64(f.data);
      const url = URL.createObjectURL(new Blob([octets], { type: f.type || 'application/octet-stream' }));
      const a = document.createElement('a');
      a.href = url; a.download = f.nom; document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    });
  }
}

function afficher(espace) {
  if (espace.plan) {
    render(espace.plan);
    const ancre = document.querySelector('.hkpis') || document.querySelector('.pl-head');
    if (ancre && espace.fichiers.length) ancre.insertAdjacentHTML('afterend', documents(espace.fichiers));
  } else {
    $('planRoot').innerHTML = `
      <header class="pl-head">
        <p class="eyebrow">${esc(espace.coureur)} · ton espace</p>
        <h1 class="title">${esc(espace.titre || 'Ton espace')}</h1>
      </header>
      ${documents(espace.fichiers) || '<p class="sub docs-vide">Ton coach n\'a encore rien déposé ici.</p>'}
      <p class="hint pl-foot">Espace préparé par Hold · Lilian Mathien${espace.modifie ? `, mis à jour le ${esc(espace.modifie)}` : ''}.</p>`;
    $('planRoot').hidden = false;
    $('gate').hidden = true;
    $('navWho').textContent = [espace.coureur, espace.titre].filter(Boolean).join(' · ');
    document.title = `Hold · ${espace.titre || 'Ton espace'}`;
  }
  brancheDocuments(espace.fichiers);
}

/* ---------- La porte ----------
   Deux formes de code. La nouvelle commence par le prénom et le nom du
   coureur : « clement-dupont-chamois-aurore-482 ». Le fichier à ouvrir n'y
   figure pas : son nom est une empreinte lente du code, calculée ici, si bien
   que le dépôt public ne laisse voir ni nom ni code. L'ancienne,
   « a7f3c921-arete-allure-105 », portait le nom du fichier avant le premier
   tiret ; elle s'ouvre toujours, en second recours. */
const STORE = 'hold.plan';
const SEL_FICHIER = 'hold-espace-v2';
const ITER_FICHIER = 310000;

// Exactement la normalisation de tools/make-plan.py : minuscules, accents
// retirés, tout le reste en tirets. tools/test/codes.js le vérifie.
function normalise(code) {
  return String(code || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

async function fichierDe(code) {
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey('raw', enc.encode(code), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: enc.encode(SEL_FICHIER), iterations: ITER_FICHIER, hash: 'SHA-256' }, base, 80);
  return Array.from(new Uint8Array(bits), (b) => b.toString(16).padStart(2, '0')).join('');
}

function splitCode(raw) {
  const t = String(raw || '').trim();
  const i = t.indexOf('-');
  if (i < 1 || i === t.length - 1) return null;
  return { slug: t.slice(0, i).toLowerCase(), pw: t.slice(i + 1) };
}

// Le navigateur peut refuser le stockage : fenêtre privée, cookies bloqués.
// La page doit marcher sans, donc chaque accès est protégé.
const store = {
  read() {
    try { return JSON.parse(localStorage.getItem(STORE) || 'null'); } catch { return null; }
  },
  write(v) {
    try { localStorage.setItem(STORE, JSON.stringify(v)); } catch { /* tant pis */ }
  },
  clear() {
    try { localStorage.removeItem(STORE); } catch { /* tant pis */ }
  },
};

let slugAncien = null;          // ancien lien qui ne portait que l'identifiant
const msg = (t) => { $('gateMsg').textContent = t; };

async function load(s) {
  const res = await fetch(`data/${encodeURIComponent(s)}.json`, { cache: 'no-store' });
  if (!res.ok) throw new Error(res.status === 404 ? 'introuvable' : String(res.status));
  return res.json();
}

function montre(contenu) {
  // Le déchiffrement a réussi : une erreur d'affichage ne doit pas se faire
  // passer pour un mauvais code, sinon le coureur cherche au mauvais endroit.
  try {
    afficher(espaceDe(contenu));
  } catch (e) {
    console.error('Hold : affichage du plan', e);
    msg("Le plan s'est ouvert mais n'a pas pu s'afficher. Préviens ton coach.");
  }
}

// Ouvre un code, nouvelle forme d'abord. Lève « introuvable » si aucun
// fichier ne correspond, « mot de passe » si le fichier existe mais refuse.
async function ouvre(brut, souvenir) {
  const code = normalise(brut);
  if (!code) throw new Error('introuvable');
  let pack = null;
  try { pack = await load(await fichierDe(code)); } catch (e) { if (e.message !== 'introuvable') throw e; }
  if (pack) {
    let contenu;
    try { contenu = await decrypt(pack, code); } catch { throw new Error('mot de passe'); }
    if (souvenir) store.write({ code }); else store.clear();
    montre(contenu);
    return;
  }
  const v1 = splitCode(brut);
  if (!v1) throw new Error('introuvable');
  await ouvreAncien(v1.slug, v1.pw, souvenir);
}

async function ouvreAncien(s, pw, souvenir) {
  const pack = await load(s);
  let contenu;
  try { contenu = await decrypt(pack, pw); } catch { throw new Error('mot de passe'); }
  if (souvenir) store.write({ slug: s, pw }); else store.clear();
  montre(contenu);
}

const dire = (e) => msg(e.message === 'mot de passe' ? 'Code incorrect.'
  : e.message === 'introuvable' ? "Aucun espace ne correspond à ce code. Vérifie l'orthographe."
    : 'Connexion impossible pour le moment. Réessaie dans un instant.');

window.addEventListener('hashchange', () => { location.reload(); });

(async function boot() {
  const hash = decodeURIComponent((location.hash || '').replace(/^#/, '')).trim();
  const saved = store.read();

  if (hash) {
    msg('Ouverture…');
    try { await ouvre(hash, false); msg(''); return; } catch (e) {
      // Un ancien lien qui ne portait que l'identifiant : on demande le mot de passe.
      if (e.message === 'introuvable' && /^[a-z0-9]+$/i.test(hash)) {
        try {
          await load(hash.toLowerCase());
          slugAncien = hash.toLowerCase();
          $('codeWrap').hidden = true;
          $('pwWrap').hidden = false;
          msg('');
          return;
        } catch { /* rien à cette adresse : message ci-dessous */ }
      }
      dire(e);
      return;
    }
  }

  if (saved && (saved.code || (saved.slug && saved.pw))) {
    $('remember').checked = true;
    try {
      if (saved.code) await ouvre(saved.code, true);
      else await ouvreAncien(saved.slug, saved.pw, true);
      return;
    } catch {
      store.clear();          // le code a changé, ou l'espace n'existe plus
      msg('Ton accès enregistré ne fonctionne plus. Entre ton code à nouveau.');
    }
  }
})();

$('gateForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const remember = $('remember').checked;
  const btn = $('gateBtn');
  btn.disabled = true;
  msg('Ouverture…');
  try {
    if (!$('pwWrap').hidden && slugAncien) {
      const pw = $('pw').value;
      if (!pw) { msg('Entre ton mot de passe.'); return; }
      await ouvreAncien(slugAncien, pw, remember);
    } else {
      const brut = $('code').value;
      if (!normalise(brut)) { msg('Entre le code que ton coach t’a transmis.'); return; }
      await ouvre(brut, remember);
    }
    msg('');
  } catch (err) {
    dire(err);
    ($('pwWrap').hidden ? $('code') : $('pw')).select();
  } finally {
    btn.disabled = false;
  }
});
