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

/* ---------- Profil, avec les bandes de nuit ---------- */
function profile(plan) {
  const pts = plan.profile || [];
  if (pts.length < 2) return '';
  const W = 1000, H = 230, P = { l: 46, r: 14, t: 14, b: 28 };
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (v) => P.l + (v - x0) / (x1 - x0 || 1) * (W - P.l - P.r);
  const Y = (v) => H - P.b - (v - y0) / (y1 - y0 || 1) * (H - P.t - P.b);

  const bands = (plan.windows || []).filter((w) => w.light !== 'jour').map((w) =>
    `<rect x="${X(w.km0).toFixed(1)}" y="${P.t}" width="${Math.max(0.5, X(w.km1) - X(w.km0)).toFixed(1)}"
       height="${H - P.t - P.b}" class="${w.light === 'nuit' ? 'pf-night' : 'pf-dusk'}"/>`).join('');

  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join('');
  const area = `${line}L${X(x1).toFixed(1)} ${(H - P.b).toFixed(1)}L${X(x0).toFixed(1)} ${(H - P.b).toFixed(1)}Z`;
  const ticks = [y0, (y0 + y1) / 2, y1].map((v) =>
    `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="pf-grid"/>
     <text x="${P.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" class="pf-lab">${Math.round(v)}</text>`).join('');
  const aid = (plan.aid || []).map((a) =>
    `<line x1="${X(a.km).toFixed(1)}" x2="${X(a.km).toFixed(1)}" y1="${P.t}" y2="${H - P.b}" class="pf-aid"/>`).join('');
  const xlab = [x0, x1 * 0.25, x1 * 0.5, x1 * 0.75, x1].map((v) =>
    `<text x="${X(v).toFixed(1)}" y="${H - 9}" text-anchor="middle" class="pf-lab">${Math.round(v)}</text>`).join('');

  return `<div class="pf"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
      aria-label="Profil du parcours, avec les portions de nuit assombries">
    ${bands}${ticks}<path d="${area}" class="pf-fill"/><path d="${line}" class="pf-line"/>${aid}${xlab}
  </svg>
  <p class="pf-cap mono">Altitude (m) par kilomètre · zones sombres : nuit · traits verticaux : ravitaillements</p></div>`;
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
    const rows = g.segs.map((s) => `<tr class="${s.mode === 'marche' ? 'is-walk' : ''}">
      <td class="mono nowrap">${km2(s.km0)}</td>
      <td class="mono num">${s.alt}</td>
      <td class="mono num ${s.slope >= 0 ? 'up' : 'dn'}">${s.slope > 0 ? '+' : ''}${km1(s.slope)} %</td>
      <td class="nowrap">${s.mode === 'marche' ? 'marche' : 'course'}${s.poles ? ' <span class="tag">bâtons</span>' : ''}</td>
      <td class="mono num strong">${esc(s.pace)}</td>
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
          ${km1(walk)} km marchés · ${Math.floor(dt / 3600)}h${String(Math.round(dt % 3600 / 60)).padStart(2, '0')} ·
          arrivée ${esc(last.clock)}</span>
      </summary>
      <div class="tw"><table class="tbl tbl-sm">
        <thead><tr><th>km</th><th class="num">Alt.</th><th class="num">Pente</th><th>Mode</th>
          <th class="num">Allure</th><th class="num">Temps</th><th class="num">Cumul</th>
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
    <p class="hint pl-foot">Plan établi par Hold · Lilian Mathien. Révisé le ${esc(plan.revised || '—')}.
      Ce document décrit une cible, pas une garantie : le jour J, tes sensations priment.</p>`;

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
