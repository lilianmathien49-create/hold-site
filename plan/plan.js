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

function profile(plan) {
  const segs = plan.segments || [];
  const pts = plan.profile || [];
  if (pts.length < 2) return '';
  const W = 1000, PH = 250, SH = 16, GAP = 5;
  const P = { l: 52, r: 16, t: 16 };
  const stripsY = P.t + PH + 14;
  const H = stripsY + (SH + GAP) * 3 + 30;

  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = 0, x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (v) => P.l + (v - x0) / (x1 - x0 || 1) * (W - P.l - P.r);
  const Y = (v) => P.t + PH - (v - y0) / (y1 - y0 || 1) * PH;

  // Le profil est dessiné en colonnes colorées par la pente : la couleur porte
  // l'information que la seule silhouette ne donne pas.
  const cols = segs.map((s) => {
    const xa = X(s.km0), xb = X(s.km1);
    return `<rect x="${xa.toFixed(1)}" y="${Y(s.alt).toFixed(1)}"
      width="${Math.max(0.6, xb - xa).toFixed(1)}" height="${(P.t + PH - Y(s.alt)).toFixed(1)}"
      class="t-${terrainOf(s.slope)}"/>`;
  }).join('');

  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join('');
  const grid = [y0, (y0 + y1) / 2, y1].map((v) =>
    `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="pf-grid"/>
     <text x="${P.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" class="pf-lab">${Math.round(v)}</text>`).join('');

  // Ravitaillements : un repère, et le nom un rang sur deux pour éviter la bouillie.
  const majors = (plan.aid || []).filter((a) => a.km > 1 && a.km < x1 - 1);
  const marks = majors.map((a, i) => `
    <line x1="${X(a.km).toFixed(1)}" x2="${X(a.km).toFixed(1)}" y1="${P.t}" y2="${P.t + PH}" class="pf-aid"/>
    <text x="${X(a.km).toFixed(1)}" y="${P.t + 11 + (i % 2) * 13}" class="pf-aidlab"
      text-anchor="${X(a.km) > W * 0.82 ? 'end' : 'middle'}">${esc(a.name.split(/[-–]/)[0].trim().slice(0, 14))}</text>`).join('');

  const strip = (y, cells, label) => `
    <text x="${P.l - 8}" y="${y + SH - 4}" text-anchor="end" class="pf-lab">${label}</text>
    ${cells}`;
  const cell = (s, y, cls) => `<rect x="${X(s.km0).toFixed(1)}" y="${y}"
    width="${Math.max(0.6, X(s.km1) - X(s.km0)).toFixed(1)}" height="${SH}" class="${cls}"/>`;

  const slopeStrip = strip(stripsY, segs.map((s) => cell(s, stripsY, `t-${terrainOf(s.slope)}`)).join(''), 'pente');
  const modeY = stripsY + SH + GAP;
  const modeStrip = strip(modeY, segs.map((s) =>
    cell(s, modeY, s.mode === 'marche' ? (s.poles ? 'm-poles' : 'm-marche') : 'm-course')).join(''), 'mode');
  const lightY = modeY + SH + GAP;
  const lightStrip = strip(lightY, segs.map((s) =>
    cell(s, lightY, s.light === 'nuit' ? 'l-nuit' : s.light === 'jour' ? 'l-jour' : 'l-chien')).join(''), 'lumière');

  const xlab = [0, .2, .4, .6, .8, 1].map((f) => {
    const v = x0 + (x1 - x0) * f;
    return `<text x="${X(v).toFixed(1)}" y="${H - 8}" class="pf-lab"
      text-anchor="${f === 0 ? 'start' : f === 1 ? 'end' : 'middle'}">${Math.round(v)} km</text>`;
  }).join('');

  const legend = [['t-raide', 'raide · ≥ 12 %'], ['t-montee', 'montée · 4–12 %'], ['t-plat', 'plat'],
    ['t-descente', 'descente'], ['t-plongeon', 'descente raide']]
    .map(([c, l]) => `<span class="lg"><i class="sw ${c}"></i>${l}</span>`).join('');
  const legend2 = [['m-course', 'course'], ['m-marche', 'marche'], ['m-poles', 'bâtons'],
    ['l-nuit', 'nuit'], ['l-chien', 'chien et loup'], ['l-jour', 'jour']]
    .map(([c, l]) => `<span class="lg"><i class="sw ${c}"></i>${l}</span>`).join('');

  return `<div class="pf">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Profil du parcours, pente, mode et lumière">
      ${grid}${cols}<path d="${line}" class="pf-line"/>${marks}
      ${slopeStrip}${modeStrip}${lightStrip}${xlab}
    </svg>
    <div class="pf-legend">${legend}</div>
    <div class="pf-legend">${legend2}</div>
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
    return `<tr>
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

/* ---------- Assemblage ---------- */
function render(plan) {
  const m = plan.model || {}, c = plan.conditions || {};
  const kpi = (l, v) => v ? `<div class="kpi"><p class="kpi-l mono">${esc(l)}</p><p class="kpi-v">${esc(v)}</p></div>` : '';
  const night = (plan.windows || []).filter((w) => w.light === 'nuit').reduce((a, w) => a + w.km1 - w.km0, 0);

  $('planRoot').innerHTML = `
    <header class="pl-head">
      <p class="eyebrow">${esc(plan.runner || '')} · plan de course</p>
      <h1 class="title">${esc(plan.race || 'Ta course')}<br><span class="soft">${esc(plan.date || '')}</span></h1>
      ${plan.notes ? `<p class="sub pl-note">${esc(plan.notes)}</p>` : ''}
    </header>
    <div class="kpis">
      ${kpi('Objectif', plan.goal)}
      ${kpi('Projeté', plan.projected)}
      ${kpi('Départ', plan.start)}
      ${kpi('Distance', plan.distanceKm ? `${km1(plan.distanceKm)} km` : '')}
      ${kpi('Dénivelé +', plan.elevationM ? `${plan.elevationM} m` : '')}
      ${kpi('Dont marche', m.walkKm != null ? `${km1(m.walkKm)} km` : '')}
      ${kpi('Dont nuit', night ? `${km1(night)} km` : '')}
      ${kpi('Températures', c.temp)}
    </div>
    ${profile(plan)}
    ${athlete(plan)}
    ${reference(plan)}
    ${lessons(plan)}
    ${montecarlo(plan)}
    ${sections(plan)}
    ${strategy(plan)}
    ${windows(plan)}
    ${hours(plan)}
    ${aidTable(plan)}
    ${plan.advice ? `<section class="pl-block"><h2 class="pl-h">À retenir</h2>
      <ul class="pl-list">${plan.advice.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></section>` : ''}
    <section class="pl-block">
      <h2 class="pl-h">Comment ce plan est calculé</h2>
      <ul class="pl-list pl-model">
        <li>Le parcours est découpé en tronçons de 500 m, pente mesurée sur la trace GPX.</li>
        <li>Marche ou course : décidé tronçon par tronçon en comparant la pente à ton seuil,
          qui part de ${m.walkThr ?? '—'} % et baisse de ${m.walkDecay ?? '—'} point par heure de course.</li>
        <li>Les vitesses suivent le coût énergétique de la pente (Minetti 2002), recalées pour tenir ton objectif.</li>
        <li>Jour et nuit : position réelle du soleil à la date et au lieu de la course.</li>
        <li>Températures : prévision en vallée, corrigée de −6,5 °C par 1000 m d'altitude.</li>
      </ul>
      <p class="hint pl-warn">Une limite à connaître : ton seuil de marche a été mesuré sur des sorties
        allant jusqu'à quatre heures. Au-delà, le plan prolonge la tendance et la plafonne à un plancher
        prudent. Sur une course de ${plan.goal || 'cette durée'}, les dernières heures reposent donc sur
        une extrapolation, pas sur une mesure.</p>
    </section>
    ${exporter(plan)}
    <p class="hint pl-foot">Plan établi par Hold · Lilian Mathien. Révisé le ${esc(plan.revised || '—')}.
      Ce document décrit une cible, pas une garantie : le jour J, tes sensations priment.</p>`;

  const slug = `${(plan.race || 'course')}-${(plan.runner || '')}`.toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  $('dlGpx')?.addEventListener('click', () => download(`${slug}.gpx`, toGpx(plan), 'application/gpx+xml'));
  $('dlCsv')?.addEventListener('click', () => download(`${slug}.csv`, toCsv(plan), 'text/csv;charset=utf-8'));
  $('doPrint')?.addEventListener('click', () => window.print());
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
  try {
    render(await decrypt(pack, pw));
  } catch {
    // AES-GCM refuse aussi bien un mauvais mot de passe qu'un fichier modifié : même message.
    msg('Mot de passe incorrect.');
    $('pw').select();
  } finally {
    $('gateBtn').disabled = false;
  }
});
