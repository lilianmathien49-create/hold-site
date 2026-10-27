// Plan de course : le fichier servi est chiffré, le mot de passe ne quitte jamais le navigateur.
// Clé dérivée en PBKDF2-SHA256, contenu scellé en AES-GCM (qui échoue si on altère le fichier).
const $ = (id) => document.getElementById(id);
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const slug = (location.hash || '').replace(/^#/, '').trim() || 'demo';

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
const km2 = (v) => Number(v).toFixed(2).replace('.', ',');
const degC = (v) => `${Math.round(v)} °C`;
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
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
      <p class="cock-hint mono" id="cockHint">Balaye le profil — ou fais glisser le curseur du temps</p>
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

/* ---------- Chaleur : ce que la température du jour va te coûter ---------- */
function heatPlan(plan) {
  const a = plan.athlete || {};
  const perDeg = (a.hr || {}).hr_heat;
  const hours = plan.hours || [];
  if (!hours.length) return '';
  const warm = hours.filter((h) => h.tmax > 15);
  const peak = hours.reduce((m, h) => (h.tmax > m.tmax ? h : m), hours[0]);
  const cold = hours.reduce((m, h) => (h.tmin < m.tmin ? h : m), hours[0]);
  const over = warm.reduce((a2, h) => a2 + Math.max(0, (h.tmin + h.tmax) / 2 - 15), 0) / (hours.length || 1);
  const cost = perDeg ? perDeg * Math.max(0, peak.tmax - 15) : null;

  return `<div class="panel">
    <div class="two">
      <div class="big">
        <p class="big-l mono">Le plus chaud</p>
        <p class="big-v">${degC(peak.tmax)}</p>
        <p class="big-h mono">vers ${esc(peak.h)}, entre km ${km1(peak.km0)} et ${km1(peak.km1)}</p>
      </div>
      <div class="big">
        <p class="big-l mono">Le plus froid</p>
        <p class="big-v">${degC(cold.tmin)}</p>
        <p class="big-h mono">vers ${esc(cold.h)}, à ${cold.alt} m d'altitude</p>
      </div>
    </div>
    ${perDeg ? `<p class="sub pl-wide" style="margin-top:22px">On a mesuré sur ton année d'entraînement que
      chaque degré au-dessus de 15 °C te coûte <b>${km1(perDeg)} battement par minute</b> à effort égal.
      Au plus chaud de ta course, ça représente <b>+${Math.round(cost)} bpm</b> pour la même allure :
      c'est l'écart qu'il faut accepter de perdre plutôt que de s'entêter.</p>` : ''}
    <p class="hint">${warm.length} heures de course au-dessus de 15 °C sur ${hours.length}.
      L'altitude refroidit l'air de 6,5 °C par millier de mètres : c'est pourquoi les cols de nuit
      passent sous zéro alors qu'il fera ${degC(peak.tmax)} en vallée.</p>
  </div>`;
}

/* ---------- Nutrition : ce qu'il faut emporter, portion par portion ---------- */
// Repères d'ultra-endurance : 60 à 90 g de glucides par heure, et un besoin en
// liquide qui grimpe avec la chaleur. On les applique aux durées réelles du plan.
const CARB_PER_H = 65;
const fluidPerH = (t) => Math.round(450 + Math.max(0, t - 15) * 35);
const sodiumPerH = (t) => Math.round(500 + Math.max(0, t - 15) * 45);

function nutrition(plan) {
  const aid = plan.aid || [];
  if (aid.length < 2) return '';
  const secs = (s) => { const [h, m, x] = (s || '0:00:00').split(':'); return +h * 3600 + +m * 60 + +x; };
  const legs = [];
  for (let i = 0; i < aid.length - 1; i++) {
    const a = aid[i], b = aid[i + 1];
    const dt = secs(b.cumul.length <= 5 ? `${b.cumul}:00` : b.cumul) - secs(a.cumul.length <= 5 ? `${a.cumul}:00` : a.cumul);
    if (dt <= 0) continue;
    const h = dt / 3600, t = (a.temp + b.temp) / 2;
    legs.push({
      from: a.name, to: b.name, km0: a.km, km1: b.km, h,
      carbs: Math.round(CARB_PER_H * h), fluid: Math.round(fluidPerH(t) * h),
      sodium: Math.round(sodiumPerH(t) * h), temp: t, light: b.light,
    });
  }
  const tot = legs.reduce((o, l) => ({ carbs: o.carbs + l.carbs, fluid: o.fluid + l.fluid, sodium: o.sodium + l.sodium }),
    { carbs: 0, fluid: 0, sodium: 0 });

  const rows = legs.map((l) => `<tr>
    <td>${esc(l.from)} <span class="muted">→</span> ${esc(l.to)}</td>
    <td class="mono num">${km1(l.km1 - l.km0)}</td>
    <td class="mono num">${l.h < 1 ? `${Math.round(l.h * 60)} min` : `${Math.floor(l.h)}h${String(Math.round(l.h % 1 * 60)).padStart(2, '0')}`}</td>
    <td class="mono num strong">${l.carbs} g</td>
    <td class="mono num">${(l.fluid / 1000).toFixed(1).replace('.', ',')} L</td>
    <td class="mono num">${l.sodium} mg</td>
    <td class="mono num">${degC(l.temp)}</td>
  </tr>`).join('');

  return `<div class="panel">
    <div class="three">
      <div class="big"><p class="big-l mono">Glucides</p><p class="big-v">${Math.round(tot.carbs / 1000 * 10) / 10} kg</p>
        <p class="big-h mono">${CARB_PER_H} g par heure, ${Math.round(tot.carbs / 25)} gels équivalents</p></div>
      <div class="big"><p class="big-l mono">Liquide</p><p class="big-v">${(tot.fluid / 1000).toFixed(1).replace('.', ',')} L</p>
        <p class="big-h mono">de 450 ml/h au frais à ${fluidPerH(25)} ml/h à 25 °C</p></div>
      <div class="big"><p class="big-l mono">Sodium</p><p class="big-v">${(tot.sodium / 1000).toFixed(1).replace('.', ',')} g</p>
        <p class="big-h mono">davantage quand il fait chaud</p></div>
    </div>
    <p class="sub pl-wide" style="margin:22px 0 14px">À emporter entre deux ravitaillements. Les quantités
      suivent la durée réelle de chaque portion et la température qu'il y fera, pas une règle au kilomètre.</p>
    <div class="tw tw-tall"><table class="tbl">
      <thead><tr><th>Portion</th><th class="num">km</th><th class="num">Durée</th>
        <th class="num">Glucides</th><th class="num">Liquide</th><th class="num">Sodium</th><th class="num">Temp.</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="hint pl-warn">Ces quantités sont des repères d'ultra-endurance appliqués à ton plan,
      <b>pas une prescription personnelle</b>. Ta tolérance digestive se travaille à l'entraînement :
      teste ces volumes sur tes sorties longues avant de les suivre le jour J.</p>
  </div>`;
}

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

/* ---------- Jour et nuit ---------- */
function windows(plan) {
  if (!(plan.windows || []).length) return '';
  const rows = plan.windows.map((w) => `<tr class="lt-${w.light === 'nuit' ? 'night' : w.light === 'jour' ? 'day' : 'dusk'}">
    <td class="nowrap">${LIGHT_ICON[w.light] || ''} ${esc(w.light)}</td>
    <td class="mono nowrap">km ${km1(w.km0)} – ${km1(w.km1)}</td>
    <td class="mono num">${km1(w.km1 - w.km0)} km</td>
    <td class="mono num">${esc(w.start)} → ${esc(w.end)}</td>
    <td class="mono num">${degC(w.tmin)} / ${degC(w.tmax)}</td>
  </tr>`).join('');
  const night = plan.windows.filter((w) => w.light === 'nuit').reduce((a, w) => a + w.km1 - w.km0, 0);
  return `<section class="pl-block">
    <h2 class="pl-h">Où il fera nuit</h2>
    <p class="sub pl-wide">Calculé sur la position réelle du soleil à ta latitude, d'après tes heures de passage.
      Au total, <b>${km1(night)} km de nuit</b>, frontale obligatoire.</p>
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
    <td class="mono nowrap">km ${km1(h.km0)} – ${km1(h.km1)}</td>
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
    <td class="mono num strong">${esc(a.eta)}</td>
    <td class="mono num">${esc(a.cumul)}</td>
    <td class="mono num">${degC(a.temp)}</td>
    <td>${(a.gear || []).map((g) => `<span class="tag">${esc(g)}</span>`).join(' ') || '<span class="muted">—</span>'}</td>
  </tr>`).join('');
  return `<section class="pl-block">
    <h2 class="pl-h">Ravitaillements</h2>
    <div class="tw"><table class="tbl">
      <thead><tr><th>km</th><th>Point</th><th class="num">Alt.</th><th class="num">Passage</th>
        <th class="num">Cumul</th><th class="num">Temp.</th><th>À sortir du sac</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
  </section>`;
}

/* ---------- Le parcours découpé là où il change vraiment ---------- */
const CLS_LABEL = { raide: 'raide', montee: 'montée', plat: 'plat', descente: 'descente', plongeon: 'plongeon' };

function sections(plan) {
  const S = plan.sections || [];
  if (!S.length) return '';
  const maxUp = Math.max(...S.map((s) => s.up), 1);
  const maxDist = Math.max(...S.map((s) => s.dist), 1);

  const rows = S.map((s) => {
    const w = (s.dist / maxDist * 100).toFixed(1);
    const bar = s.up > 20 ? (s.up / maxUp * 100).toFixed(0) : 0;
    return `<tr class="clickrow" data-km="${s.km0}" tabindex="0" role="button"
        aria-label="Voir le kilomètre ${km1(s.km0)} sur le profil">
      <td class="mono nowrap">${km1(s.km0)}<span class="muted"> – ${km1(s.km1)}</span></td>
      <td class="mono num">${km1(s.dist)}</td>
      <td class="num"><span class="cellslope"><span class="mono">${s.slope > 0 ? '+' : ''}${km1(s.slope)} %</span><i class="t-${s.cls}"></i></span></td>
      <td class="nowrap"><span class="tag tg-${s.cls}">${CLS_LABEL[s.cls] || s.cls}</span></td>
      <td class="mono num">${s.up ? `+${s.up}` : '—'}</td>
      <td class="num"><span class="minibar"><i style="width:${bar}%"></i></span></td>
      <td class="mono num strong">${esc(s.pace)}</td>
      <td class="mono num vam">${s.vam || '—'}</td>
      <td class="num"><span class="walkpc ${s.walkShare > 60 ? 'hi' : ''}">${s.walkShare} %</span>${s.poles ? ' <span class="tag">bâtons</span>' : ''}</td>
      <td class="mono num">${esc(s.cumul.slice(0, 5))}</td>
      <td class="mono num">${esc(s.clock)}</td>
      ${''}
    </tr>${s.aid ? `<tr class="aidrow"><td colspan="11">
      <span class="mono">km ${km1(s.km1)}</span> · ravitaillement ${esc(s.aid)}</td></tr>` : ''}`;
  }).join('');

  const climbs = S.filter((s) => s.up > 250).sort((a, b) => b.up - a.up).slice(0, 6);
  const topClimbs = climbs.map((c) => `<div class="cl">
    <p class="cl-km mono">km ${km1(c.km0)}</p>
    <p class="cl-up">+${c.up} m</p>
    <p class="cl-d mono">${km1(c.dist)} km à ${km1(c.slope)} %${c.vam ? ` · ${c.vam} m/h` : ''}</p>
  </div>`).join('');

  return `<section class="pl-block">
    <h2 class="pl-h">Le parcours, bosse par bosse</h2>
    <p class="sub pl-wide">Le découpage ne suit pas une règle fixe : il coupe là où le terrain change
      vraiment, et à chaque ravitaillement. Une montée de six kilomètres reste une ligne,
      au lieu d'être hachée en douze.</p>
    ${topClimbs ? `<div class="climbs">${topClimbs}</div>` : ''}
    <div class="tw tw-tall"><table class="tbl">
      <thead><tr><th>km</th><th class="num">Long.</th><th class="num">Pente</th><th>Terrain</th>
        <th class="num">D+</th><th class="num">Poids</th><th class="num">Allure</th>
        <th class="num">VAM</th><th class="num">Marche</th><th class="num">Cumul</th><th class="num">Heure</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="hint">« Poids » compare le dénivelé de chaque portion à la plus grosse du parcours.
      « VAM » est la vitesse ascensionnelle, en mètres de dénivelé par heure.</p>
  </section>`;
}

/* ---------- Stratégie au pas de 500 m, groupée par portion ---------- */
function strategy(plan) {
  const segs = plan.segments || [];
  if (!segs.length) return '';
  const marks = (plan.aid || []).map((a) => a.km).filter((k) => k > 0.2);

  // On coupe la liste des tronçons aux ravitaillements : une portion = un inter-ravito.
  const groups = [];
  let cur = null, next = 0;
  for (const s of segs) {
    if (!cur || (next < marks.length && s.km0 >= marks[next])) {
      if (next < marks.length && cur) next++;
      const to = marks[next] ?? segs[segs.length - 1].km1;
      const name = (plan.aid.find((a) => Math.abs(a.km - to) < 0.3) || {}).name || 'Arrivée';
      cur = { from: s.km0, to, name, segs: [] };
      groups.push(cur);
    }
    cur.segs.push(s);
  }

  const body = groups.map((g, i) => {
    const up = g.segs.reduce((a, s) => a + s.up, 0), down = g.segs.reduce((a, s) => a + s.down, 0);
    const walk = g.segs.filter((s) => s.mode === 'marche').reduce((a, s) => a + (s.km1 - s.km0), 0);
    const dist = g.segs[g.segs.length - 1].km1 - g.segs[0].km0;
    const dt = g.segs.reduce((a, s) => a + s.split, 0);
    const last = g.segs[g.segs.length - 1];
    const vam = dt > 0 && up > 60 ? Math.round(up / (dt / 3600)) : null;
    const rows = g.segs.map((s) => `<tr class="${s.mode === 'marche' ? 'is-walk' : ''}">
      <td class="mono nowrap">${km2(s.km0)}</td>
      <td class="mono num">${s.alt}</td>
      <td class="mono num"><span class="cellslope"><span>${s.slope > 0 ? '+' : ''}${km1(s.slope)} %</span><i class="t-${terrainOf(s.slope)}"></i></span></td>
      <td class="nowrap">${s.mode === 'marche' ? 'marche' : 'course'}${s.poles ? ' <span class="tag">bâtons</span>' : ''}</td>
      <td class="mono num strong">${esc(s.pace)}</td>
      <td class="mono num vam">${s.vam ? `${s.vam}` : '—'}</td>
      <td class="mono num">${mmss(s.split)}</td>
      <td class="mono num">${esc(s.cumul)}</td>
      <td class="mono num">${esc(s.clock)}</td>
      <td class="mono num">${degC(s.temp)}</td>
    </tr>`).join('');
    return `<details class="grp"${i === 0 ? ' open' : ''}>
      <summary>
        <span class="grp-km mono">km ${km1(g.from)} – ${km1(g.to)}</span>
        <span class="grp-n">${esc(g.name)}</span>
        <span class="grp-m mono">${km1(dist)} km · +${Math.round(up)} / −${Math.round(down)} m ·
          ${km1(walk)} km marchés · ${Math.floor(dt / 3600)}h${String(Math.round(dt % 3600 / 60)).padStart(2, '0')}${vam ? ` · ${vam} m/h` : ''} ·
          arrivée ${esc(last.clock)}</span>
      </summary>
      <div class="tw"><table class="tbl tbl-sm">
        <thead><tr><th>km</th><th class="num">Alt.</th><th class="num">Pente</th><th>Mode</th>
          <th class="num">Allure</th><th class="num">VAM</th><th class="num">Temps</th><th class="num">Cumul</th>
          <th class="num">Heure</th><th class="num">Temp.</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
    </details>`;
  }).join('');

  const m = plan.model || {};
  return `<section class="pl-block">
    <h2 class="pl-h">Ta course, tous les 500 m</h2>
    <p class="sub pl-wide">Chaque tronçon de 500 m est décidé séparément : la pente est mesurée sur la trace,
      et comparée à <b>ton</b> seuil de bascule marche/course du moment. Ouvre une portion pour le détail.</p>
    <div class="grps">${body}</div>
    ${m.walkKm != null ? `<p class="hint">Au total : ${km1(m.walkKm)} km marchés, ${km1(m.runKm)} km courus.
      Les lignes rouges sont les tronçons marchés.</p>` : ''}
  </section>`;
}

/* ---------- Ce qu'on a mesuré sur le coureur ---------- */
function athlete(plan) {
  const a = plan.athlete;
  if (!a) return '';
  const row = (label, value, ci, unit, note) => `<tr>
    <td>${esc(label)}</td>
    <td class="mono num strong">${esc(value)}${unit ? ` ${esc(unit)}` : ''}</td>
    <td class="mono num">${ci ? `${esc(ci[0])} – ${esc(ci[1])}` : '—'}</td>
    <td class="note">${esc(note || '')}</td>
  </tr>`;
  const w = a.walk || {}, h = a.hr || {}, s = a.speed || {};
  return `<section class="pl-block">
    <h2 class="pl-h">Ce qu'on a mesuré sur toi</h2>
    <p class="sub pl-wide">Tiré de <b>${a.sessions} séances</b> et ${(a.blocks || 0).toLocaleString('fr-FR')} blocs
      de 15 secondes, sur une année complète. Les intervalles viennent d'un rééchantillonnage par séance :
      deux blocs voisins d'une même sortie ne comptent pas pour deux mesures indépendantes.</p>
    <div class="tw"><table class="tbl">
      <thead><tr><th>Ce qu'on mesure</th><th class="num">Valeur</th><th class="num">Intervalle 95 %</th><th>Ce que ça change</th></tr></thead>
      <tbody>
        ${row('Pente de bascule à la marche', km1(w.thr0), w.thr0CI, '%', 'Au-delà, tu marches plus vite que tu ne cours')}
        ${row('Chute du seuil', km1(w.decay), w.decayCI, 'pt/h', "Après 4 h, tu marches des pentes que tu courais au départ")}
        ${row('Dérive cardiaque', km1(h.hr_drift), h.driftCI, 'bpm/h', 'À effort constant, le cœur monte seul')}
        ${row('Coût de la chaleur', km1(h.hr_heat), h.heatCI, 'bpm/°C', 'Au-dessus de 15 °C, chaque degré se paie')}
        ${row('Durabilité', km1(s.durability), s.durabilityCI, '%/h', 'Vitesse perdue par heure, à pente égale')}
      </tbody></table></div>
    ${a.r2 != null ? `<p class="hint">Le modèle cardiaque explique ${Math.round(a.r2 * 100)} % de la variation de ta FC.</p>` : ''}
  </section>`;
}

/* ---------- Ce que disent les finishers du même chrono ---------- */
function reference(plan) {
  const r = plan.reference;
  if (!r || !(r.points || []).length) return '';
  const W = 1000, H = 260, P = { l: 52, r: 16, t: 16, b: 34 };
  const X = (v) => P.l + v * (W - P.l - P.r);
  const Y = (v) => H - P.b - v * (H - P.t - P.b);
  const path = (key) => r.points.map((p, i) => `${i ? 'L' : 'M'}${X(p.dist).toFixed(1)} ${Y(p[key]).toFixed(1)}`).join('');
  const bandPath = r.points.map((p, i) => `${i ? 'L' : 'M'}${X(p.dist).toFixed(1)} ${Y(p.p75).toFixed(1)}`).join('')
    + r.points.slice().reverse().map((p) => `L${X(p.dist).toFixed(1)} ${Y(p.p25).toFixed(1)}`).join('') + 'Z';
  const ticks = [0, .25, .5, .75, 1].map((v) =>
    `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="pf-grid"/>
     <text x="${P.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" class="pf-lab">${v * 100} %</text>
     <text x="${X(v).toFixed(1)}" y="${H - 10}" text-anchor="middle" class="pf-lab">${v * 100} %</text>`).join('');

  const worst = r.points.reduce((a, p) => (p.drift > a.drift ? p : a), r.points[0]);
  const rows = r.points.filter((p) => [0.25, 0.5, 0.75, 0.9].some((d) => Math.abs(p.dist - d) < 1e-6))
    .map((p) => `<tr><td class="mono num">${Math.round(p.dist * 100)} %</td>
      <td class="mono num strong">${(p.median * 100).toFixed(1)} %</td>
      <td class="mono num">${(p.p25 * 100).toFixed(1)} – ${(p.p75 * 100).toFixed(1)} %</td>
      <td class="mono num ${p.drift > 0 ? 'late' : ''}">${p.drift > 0 ? '+' : ''}${p.drift.toFixed(1)} pt</td></tr>`).join('');

  return `<section class="pl-block">
    <h2 class="pl-h">Ce qu'ont fait ceux qui ont réussi</h2>
    <p class="sub pl-wide">${r.runners} coureurs arrivés autour de ${esc(r.target)} sur les éditions
      ${r.years[0]}–${r.years[r.years.length - 1]}. Le parcours change d'une année à l'autre, donc on ne compare
      pas des ravitaillements mais des proportions : <b>à 50 % de la distance, quelle part de leur temps avaient-ils
      déjà dépensée ?</b> La diagonale serait une course parfaitement régulière.</p>
    <div class="pf"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
        aria-label="Part du temps dépensée selon la part de distance parcourue">
      ${ticks}
      <path d="${bandPath}" class="rf-band"/>
      <line x1="${X(0)}" y1="${Y(0)}" x2="${X(1)}" y2="${Y(1)}" class="rf-even"/>
      <path d="${path('median')}" class="rf-line"/>
    </svg><p class="pf-cap mono">Horizontal : part de la distance · vertical : part du temps ·
      trait plein : médiane · zone : moitié centrale · diagonale : course régulière</p></div>
    <div class="tw"><table class="tbl">
      <thead><tr><th class="num">À cette distance</th><th class="num">Temps dépensé</th>
        <th class="num">Moitié centrale</th><th class="num">Écart à la régularité</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="hint">Le retard maximal apparaît à ${Math.round(worst.dist * 100)} % du parcours :
      ${worst.drift.toFixed(1)} points de temps en plus qu'une course régulière.
      ${r.stopMedianSec ? `Ils passent en médiane ${Math.floor(r.stopMedianSec / 3600)}h${String(Math.round(r.stopMedianSec % 3600 / 60)).padStart(2, '0')} arrêtés aux ravitaillements.` : ''}</p>
  </section>`;
}

/* ---------- Où les autres perdent du temps ---------- */
function lessons(plan) {
  const L = plan.lessons;
  if (!L) return '';
  const pc = (v) => `${v > 0 ? '+' : ''}${km1(v)} %`;
  const spots = (L.spots || []).slice(0, 8).map((s) => `<tr>
    <td class="mono nowrap">${km1(s.km)}</td>
    <td>${esc(s.name)}</td>
    <td class="mono num ${s.lost > 8 ? 'late' : ''}">${pc(s.lost)}</td>
    <td class="mono num strong ${s.lostNet > 8 ? 'late' : ''}">${pc(s.lostNet)}</td>
    <td class="mono num">${s.n}</td>
  </tr>`).join('');

  const fat = L.fatigue || [];
  const maxAbs = Math.max(...fat.map((b) => Math.abs(b.lost)), 1);
  const bars = fat.map((b) => {
    const w = Math.abs(b.lost) / maxAbs * 50;
    const neg = b.lost < 0;
    return `<div class="fg-row">
      <span class="fg-l mono">${Math.round(b.from * 100)}–${Math.round((b.from + 0.1) * 100)} %</span>
      <span class="fg-track"><span class="fg-bar ${neg ? 'neg' : 'pos'}"
        style="width:${w.toFixed(1)}%;${neg ? `right:50%` : `left:50%`}"></span></span>
      <span class="fg-v mono ${neg ? '' : 'late'}">${pc(b.lost)}</span>
    </div>`;
  }).join('');

  const stops = (L.stops || []).slice(0, 8).map((s) => `<tr>
    <td>${esc(s.name)}</td>
    <td class="mono num strong">${Math.round(s.median / 60)} min</td>
    <td class="mono num">${Math.round(s.p90 / 60)} min</td>
    <td class="mono num">${s.n}</td>
  </tr>`).join('');
  const totalStop = (L.stops || []).reduce((a, s) => a + s.median, 0);

  return `<section class="pl-block">
    <h2 class="pl-h">Ce que les autres ont appris à leurs dépens</h2>
    <p class="sub pl-wide">${L.runners} coureurs arrivés autour de ton objectif, ${(L.legs || 0).toLocaleString('fr-FR')}
      tronçons entre ravitaillements sur les éditions ${L.years[0]}–${L.years[L.years.length - 1]}.
      Un tronçon long et raide prend du temps : ça n'apprend rien. On a donc retiré ce que la distance
      et le dénivelé expliquent, puis regardé ce qui restait.</p>

    <h3 class="pl-h3">Les tronçons qui coûtent plus cher qu'ils n'en ont l'air</h3>
    <div class="tw"><table class="tbl">
      <thead><tr><th>km</th><th>Jusqu'à</th><th class="num">Brut</th>
        <th class="num">Fatigue retirée</th><th class="num">Passages</th></tr></thead>
      <tbody>${spots}</tbody></table></div>
    <p class="hint"><b>Brut</b> : tout ce qui dépasse le terrain, fatigue comprise.
      <b>Fatigue retirée</b> : ce qui reste une fois qu'on tient compte du fait qu'un tronçon tardif
      est couru épuisé. Les deux colonnes ne classent pas dans le même ordre — un passage peut paraître
      terrible seulement parce qu'il arrive tard, et un autre être réellement traître.</p>

    <h3 class="pl-h3">Comment la fatigue s'installe</h3>
    <p class="sub pl-wide">Écart au rythme que le terrain seul prévoit, selon la part de course déjà faite.
      À gauche, ils vont plus vite que le terrain ne le voudrait ; à droite, moins vite.</p>
    <div class="fg">${bars}</div>

    ${L.nightEffect != null ? `<p class="hint pl-warn">À terrain et fatigue égaux, la nuit coûte
      <b>${pc(L.nightEffect)}</b> de temps en plus.</p>` : ''}

    ${stops ? `<h3 class="pl-h3">Le temps passé à l'arrêt</h3>
    <p class="sub pl-wide">Arrêts les plus longs, mesurés entre l'heure d'arrivée et l'heure de départ
      du point. Sur les points listés, ils cumulent ${Math.floor(totalStop / 60)} minutes à l'arrêt.</p>
    <div class="tw"><table class="tbl">
      <thead><tr><th>Point</th><th class="num">Médiane</th><th class="num">Les plus lents (90 %)</th>
        <th class="num">Passages</th></tr></thead><tbody>${stops}</tbody></table></div>` : ''}

    ${L.heatPctPerDegree != null ? `<p class="hint">Sur le peloton entier
      (${(L.fieldFinishers || 0).toLocaleString('fr-FR')} finishers, douze éditions), on ne détecte
      <b>aucun effet mesurable de la météo</b> sur le chrono médian : ${km1(L.heatPctPerDegree)} % par degré.
      Le temps limite comprime trop la distribution pour qu'un effet y soit lisible.</p>` : ''}
  </section>`;
}

/* ---------- Monte-Carlo ---------- */
function montecarlo(plan) {
  const m = plan.montecarlo;
  if (!m) return '';
  const pct = Math.round((m.probability || 0) * 100);
  const rows = (m.checkpoints || []).map((c) => `<tr>
    <td class="mono nowrap">${km1(c.km)}</td><td>${esc(c.name)}</td>
    <td class="mono num">${esc(c.p10)}</td>
    <td class="mono num strong">${esc(c.median)}</td>
    <td class="mono num">${esc(c.p90)}</td>
  </tr>`).join('');
  return `<section class="pl-block">
    <h2 class="pl-h">Dix mille courses simulées</h2>
    <p class="sub pl-wide">On ne connaît aucun de tes paramètres exactement : on connaît leur fourchette.
      Alors on rejoue ${(m.runs || 0).toLocaleString('fr-FR')} fois ta course en tirant au sort,
      à chaque fois, ta forme du jour, ta fatigue, la météo et tes arrêts.</p>
    <div class="mc">
      <div class="mc-big"><p class="mc-v">${pct} %</p><p class="mc-l mono">de chances de tenir ${esc(m.target)}</p></div>
      <div class="mc-range">
        <p class="mc-rl mono">Fourchette des chronos simulés</p>
        <div class="mc-bar"><span class="mc-fill"></span></div>
        <p class="mc-ticks mono"><span>${esc(m.p10)}</span><span>${esc(m.median)}</span><span>${esc(m.p90)}</span></p>
        <p class="mc-sub mono">10 % · médiane · 90 %</p>
      </div>
    </div>
    ${rows ? `<div class="tw tw-tall"><table class="tbl">
      <thead><tr><th>km</th><th>Point</th><th class="num">Au plus vite</th>
        <th class="num">Médiane</th><th class="num">Au plus lent</th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : ''}
  </section>`;
}

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
  <desc>Passage visé ${esx(a.cumul || '')} · ${esx(a.eta || '')} · ${a.temp ?? '?'} °C · ${esx(a.light || '')}${(a.gear || []).length ? ' · ' + esx(a.gear.join(', ')) : ''}</desc>
  <sym>Flag</sym></wpt>`);
  }
  for (const s of plan.sections || []) {
    if (s.lat == null || s.lon == null) continue;
    wpts.push(`<wpt lat="${s.lat}" lon="${s.lon}"><ele>${s.alt0 ?? 0}</ele>
  <name>km ${s.km0} ${CLS_LABEL[s.cls] || s.cls} ${s.slope > 0 ? '+' : ''}${s.slope}%</name>
  <desc>${s.dist} km · ${s.up ? `+${s.up} m · ` : ''}${s.pace}/km${s.vam ? ` · ${s.vam} m/h` : ''} · ${s.walkShare}% marche${s.poles ? ' · bâtons' : ''} · cumul ${esx(s.cumul || '')}</desc>
  <sym>Waypoint</sym></wpt>`);
  }
  const trk = (plan.segments || []).filter((s) => s.lat != null && s.lon != null)
    .map((s) => `<trkpt lat="${s.lat}" lon="${s.lon}"><ele>${s.alt}</ele></trkpt>`).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Hold" xmlns="http://www.topografix.com/GPX/1/1">
<metadata><name>${esx(plan.race || 'Course')} — ${esx(plan.runner || '')} — objectif ${esx(plan.goal || '')}</name></metadata>
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
  const slug = `${(plan.race || 'course')}-${(plan.runner || '')}`.toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const n = (plan.aid || []).filter((a) => a.lat != null).length
    + (plan.sections || []).filter((s) => s.lat != null).length;
  return `<section class="pl-block">
    <h2 class="pl-h">Emporter le plan</h2>
    <p class="sub pl-wide">Le fichier est fabriqué ici, dans ton navigateur, à partir du plan
      déchiffré : il ne repasse jamais par le serveur. Le GPX contient la trace et
      ${n} points nommés — chaque ravitaillement et chaque changement de terrain —
      avec l'heure de passage visée, l'allure et le matériel à sortir.</p>
    <div class="f-actions">
      <button type="button" class="btn" id="dlGpx">Télécharger le GPX</button>
      <button type="button" class="btn btn-ghost" id="dlCsv">Télécharger le tableau (CSV)</button>
      <button type="button" class="btn btn-ghost" id="doPrint">Imprimer</button>
    </div>
    <p class="hint" id="dlHint">Le GPX s'importe sur Garmin Connect, Coros, Suunto et Strava.
      Les points nommés apparaissent comme alertes au fil du parcours.
      <b>Le FIT n'est pas proposé</b> : son format binaire est propre à Garmin, et un fichier
      mal formé est refusé par la montre sans message. Le GPX, lui, passe partout.</p>
  </section>`;
}

function method(plan) {
  const m = plan.model || {}, L = plan.learnedFrom;
  return `<section class="pl-block">
    <h2 class="pl-h">Comment ce plan est calculé</h2>
    <ul class="pl-list pl-model">
      <li>Le parcours est découpé en tronçons de 500 m, pente mesurée sur la trace GPX,
        puis regroupé là où le terrain change vraiment.</li>
      ${L ? `<li>Le rythme ne vient pas d'un modèle mais de <b>${L.runners} coureurs</b> arrivés autour de
        ton objectif sur les éditions ${L.years[0]}–${L.years[L.years.length - 1]}. Pour chacun des
        ${L.matched} ravitaillements reconnus d'une année sur l'autre, on reprend la part de leur temps
        total qu'ils avaient dépensée en y arrivant.</li>` : ''}
      <li>Marche ou course : décidé tronçon par tronçon en comparant la pente à ton seuil,
        qui part de ${m.walkThr ?? '—'} % et baisse de ${m.walkDecay ?? '—'} point par heure.</li>
      <li>Jour et nuit : position réelle du soleil à la date et au lieu de la course.</li>
      <li>Températures : prévision en vallée, corrigée de −6,5 °C par millier de mètres.</li>
    </ul>
    <p class="hint pl-warn">Deux limites à connaître. Ton seuil de marche a été mesuré sur des sorties
      allant jusqu'à quatre heures : au-delà, le plan prolonge la tendance et la plafonne. Et les repères
      de nutrition sont des valeurs d'ultra-endurance appliquées à ton plan, pas une prescription
      personnelle — teste-les à l'entraînement.</p>
  </section>`;
}

/* ---------- Assemblage : un onglet à la fois ----------
   Tout afficher d'un bloc noyait l'essentiel. Chaque onglet répond à une
   seule question, et le parcours est celui qui s'ouvre. */
const TABS = [
  ['course', 'La course'],
  ['chaleur', 'Chaleur & nutrition'],
  ['moi', 'Ce qu\'on a mesuré'],
  ['autres', 'Ce qu\'ont fait les autres'],
  ['simu', 'Simulations'],
  ['emporter', 'Emporter'],
];

function render(plan) {
  const m = plan.model || {};
  const night = (plan.windows || []).filter((w) => w.light === 'nuit').reduce((a, w) => a + w.km1 - w.km0, 0);
  const kpi = (l, v, h) => v ? `<div class="hk"><p class="hk-l mono">${esc(l)}</p>
    <p class="hk-v">${esc(v)}</p><p class="hk-h mono">${esc(h || '')}</p></div>` : '';

  const body = {
    course: `${cockpit(plan)}${sections(plan)}${aidTable(plan)}${strategy(plan)}`,
    chaleur: `${heatPlan(plan)}${nutrition(plan)}${windows(plan)}${hours(plan)}`,
    moi: `${athlete(plan)}`,
    autres: `${reference(plan)}${lessons(plan)}`,
    simu: `${montecarlo(plan)}`,
    emporter: `${exporter(plan)}${method(plan)}`,
  };
  const tabs = TABS.filter(([k]) => (body[k] || '').trim());

  $('planRoot').innerHTML = `
    <header class="pl-head">
      <p class="eyebrow">${esc(plan.runner || '')} · plan de course</p>
      <h1 class="title">${esc(plan.race || 'Ta course')}<br><span class="soft">${esc(plan.date || '')}</span></h1>
    </header>
    <div class="hkpis">
      ${kpi('Objectif', plan.goal, plan.start ? `départ ${plan.start}` : '')}
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

  $('planRoot').hidden = false;
  $('gate').hidden = true;
  $('navWho').textContent = `${plan.runner || ''} · ${plan.race || ''}`;
  document.title = `Hold — ${plan.race || 'Plan'} · ${plan.runner || ''}`;
}

/* ---------- La porte ---------- */
let pack = null;
const msg = (t) => { $('gateMsg').textContent = t; };

(async function boot() {
  try {
    const res = await fetch(`data/${encodeURIComponent(slug)}.json`, { cache: 'no-store' });
    if (!res.ok) throw new Error(res.status);
    pack = await res.json();
  } catch {
    msg("Aucun plan à cette adresse. Vérifie le lien que ton coach t'a envoyé.");
    $('pw').disabled = true; $('gateBtn').disabled = true;
  }
})();

$('gateForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!pack) return;
  const pw = $('pw').value;
  if (!pw) return;
  $('gateBtn').disabled = true;
  msg('Déchiffrement…');
  let plan;
  try {
    plan = await decrypt(pack, pw);
  } catch {
    // AES-GCM refuse aussi bien un mauvais mot de passe qu'un fichier modifié : même message.
    msg('Mot de passe incorrect.');
    $('pw').select();
    $('gateBtn').disabled = false;
    return;
  }
  // Le déchiffrement a réussi : une erreur d'affichage ne doit plus se faire
  // passer pour un mauvais mot de passe, sinon le coureur cherche au mauvais endroit.
  try {
    render(plan);
  } catch (e) {
    console.error('Hold : affichage du plan', e);
    msg("Le plan s'est ouvert mais n'a pas pu s'afficher. Préviens ton coach.");
    $('gateBtn').disabled = false;
  }
});
