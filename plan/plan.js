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

/* ---------- Rendu ---------- */
const fmtKm = (v) => `${Number(v).toFixed(1).replace('.', ',')}`;

// Profil du parcours en SVG, avec les ravitaillements posés dessus.
function profile(plan) {
  const pts = plan.profile || [];
  if (pts.length < 2) return '';
  const W = 1000, H = 220, P = { l: 44, r: 16, t: 14, b: 26 };
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (v) => P.l + (v - x0) / (x1 - x0 || 1) * (W - P.l - P.r);
  const Y = (v) => H - P.b - (v - y0) / (y1 - y0 || 1) * (H - P.t - P.b);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join('');
  const area = `${line}L${X(x1).toFixed(1)} ${(H - P.b).toFixed(1)}L${X(x0).toFixed(1)} ${(H - P.b).toFixed(1)}Z`;

  const ticks = [y0, (y0 + y1) / 2, y1].map((v) =>
    `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="pf-grid"/>
     <text x="${P.l - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" class="pf-lab">${Math.round(v)}</text>`).join('');

  const aid = (plan.aid || []).filter((a) => a.km >= x0 && a.km <= x1).map((a) =>
    `<line x1="${X(a.km).toFixed(1)}" x2="${X(a.km).toFixed(1)}" y1="${P.t}" y2="${H - P.b}" class="pf-aid"/>
     <circle cx="${X(a.km).toFixed(1)}" cy="${(H - P.b).toFixed(1)}" r="3.5" class="pf-dot"/>`).join('');

  const xlab = [x0, (x0 + x1) / 2, x1].map((v) =>
    `<text x="${X(v).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="pf-lab">${Math.round(v)} km</text>`).join('');

  return `<div class="pf"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Profil du parcours">
    ${ticks}<path d="${area}" class="pf-fill"/><path d="${line}" class="pf-line"/>${aid}${xlab}
  </svg><p class="pf-cap mono">Altitude (m) · les traits marquent les ravitaillements</p></div>`;
}

function segments(plan) {
  const rows = (plan.segments || []).map((s) => `<tr${s.mode === 'marche' ? ' class="is-walk"' : ''}>
    <td class="mono nowrap">${fmtKm(s.km)} – ${fmtKm(s.to)}</td>
    <td>${esc(s.name)}</td>
    <td class="mono num">${s.elevGain != null ? `+${s.elevGain}` : '—'}</td>
    <td class="mono num strong">${esc(s.pace || '—')}</td>
    <td class="mono num">${s.hr != null ? esc(s.hr) : '—'}</td>
    <td class="mono num">${esc(s.split || '—')}</td>
    <td class="mono num strong">${esc(s.cumul || '—')}</td>
    <td class="mono num">${esc(s.clock || '—')}</td>
  </tr>`).join('');
  return `<section class="pl-block">
    <h2 class="pl-h">Allure, portion par portion</h2>
    <div class="tw"><table class="tbl">
      <thead><tr>
        <th>km</th><th>Portion</th><th class="num">D+</th><th class="num">Allure</th>
        <th class="num">FC</th><th class="num">Temps</th><th class="num">Cumul</th><th class="num">Heure</th>
      </tr></thead><tbody>${rows}</tbody>
    </table></div>
    <p class="hint">Les lignes en rouge sont les portions où tu marches.</p>
  </section>`;
}

function aidPlan(plan) {
  if (!(plan.aid || []).length) return '';
  const rows = plan.aid.map((a) => `<tr>
    <td class="mono nowrap">${fmtKm(a.km)}</td>
    <td>${esc(a.name)}</td>
    <td class="mono num">${esc(a.eta || '—')}</td>
    <td class="mono num">${esc(a.stop || '—')}</td>
    <td>${esc(a.do || '')}</td>
  </tr>`).join('');
  return `<section class="pl-block">
    <h2 class="pl-h">Ravitaillements</h2>
    <div class="tw"><table class="tbl">
      <thead><tr><th>km</th><th>Point</th><th class="num">Heure</th><th class="num">Arrêt</th><th>À faire</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </section>`;
}

function render(plan) {
  const k = (label, value) => value ? `<div class="kpi"><p class="kpi-l mono">${esc(label)}</p><p class="kpi-v">${esc(value)}</p></div>` : '';
  const cond = plan.conditions || {};
  const html = `
    <header class="pl-head">
      <p class="eyebrow">${esc(plan.runner || '')} · plan de course</p>
      <h1 class="title">${esc(plan.race || 'Ta course')}<br><span class="soft">${esc(plan.date || '')}</span></h1>
      ${plan.notes ? `<p class="sub pl-note">${esc(plan.notes)}</p>` : ''}
    </header>
    <div class="kpis">
      ${k('Objectif', plan.goal)}
      ${k('Distance', plan.distanceKm ? `${plan.distanceKm} km` : '')}
      ${k('Dénivelé +', plan.elevationM ? `${plan.elevationM} m` : '')}
      ${k('Départ', plan.start)}
      ${k('Température', cond.temp)}
      ${k('Conditions', cond.weather)}
    </div>
    ${profile(plan)}
    ${segments(plan)}
    ${aidPlan(plan)}
    ${plan.fuel ? `<section class="pl-block"><h2 class="pl-h">Nutrition</h2><p class="sub pl-wide">${esc(plan.fuel)}</p></section>` : ''}
    ${plan.advice ? `<section class="pl-block"><h2 class="pl-h">À retenir</h2><ul class="pl-list">${plan.advice.map((a) => `<li>${esc(a)}</li>`).join('')}</ul></section>` : ''}
    <p class="hint pl-foot">Plan établi par Hold · Lilian Mathien. Révisé le ${esc(plan.revised || '—')}.
    Ce document est personnel : il décrit une cible, pas une garantie. Adapte-toi à tes sensations le jour J.</p>`;

  const root = $('planRoot');
  root.innerHTML = html;
  root.hidden = false;
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
