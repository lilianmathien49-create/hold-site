// Deux régressions déjà vécues, qu'aucun test ne couvrait :
//   1. une réécriture des onglets avait supprimé l'appel à wireCockpit().
//      Le profil restait vide, sans erreur en console.
//   2. le curseur lit la géométrie du tracé dans svg.dataset.geo, posé par
//      profile(). Si ce contrat se casse, wireCockpit sort en silence.
// On ne simule pas le navigateur : on vérifie l'appel et le contrat.
const plan = JSON.parse(PLAN);
let ko = 0, n = 0;
function check(label, cond, detail) {
  n++;
  if (!cond) { ko++; print('  KO   ' + label + (detail ? ' — ' + detail : '')); } else print('  OK   ' + label);
}

// 1. render() doit câbler le poste de pilotage.
const vrai = globalThis.wireCockpit;
let appels = 0;
globalThis.wireCockpit = function (p) { appels++; return vrai(p); };
try {
  render(plan);
} catch (e) {
  check('render() ne lève pas', false, String(e));
}
globalThis.wireCockpit = vrai;
check('render() câble le poste de pilotage', appels === 1, `appelé ${appels} fois`);

// 2. profile() doit poser la géométrie que le curseur lit.
const svg = profile(plan, true);
const geo = svg.match(/data-geo='([^']+)'/) || svg.match(/data-geo="([^"]+)"/);
check('profile(interactif) pose data-geo', !!geo);
if (geo) {
  let g = null;
  try { g = JSON.parse(geo[1].replace(/&quot;/g, '"')); } catch (e) { /* signalé ci-dessous */ }
  check('data-geo est du JSON valide', !!g);
  if (g) {
    const champs = ['l', 'r', 't', 'w', 'ph', 'y0', 'y1'];
    const absents = champs.filter((k) => typeof g[k] !== 'number');
    check('data-geo porte toute la géométrie', absents.length === 0, 'absents : ' + absents);
    check('échelle verticale non dégénérée', g.y1 > g.y0, `y0=${g.y0} y1=${g.y1}`);
  }
}
check('le curseur a sa ligne', svg.includes('id="curLine"'));
check('le curseur a son point', svg.includes('id="curDot"'));

// 3. L'échelle d'altitude doit coller aux données, pas les noyer.
let gg = null;
try { gg = geo && JSON.parse(geo[1].replace(/&quot;/g, '"')); } catch (e) { gg = null; }
const alts = (plan.segments || []).map((s) => s.alt).filter((v) => typeof v === 'number');
if (alts.length && gg) {
  const g = gg;
  const lo = Math.min(...alts), hi = Math.max(...alts);
  const remplissage = (hi - lo) / (g.y1 - g.y0) * 100;
  check(`l'altitude remplit l'axe (${remplissage.toFixed(0)} %)`, remplissage >= 70,
    `données ${lo}-${hi} m, axe ${g.y0}-${g.y1} m`);
}
print(ko ? `\n${ko} échec(s) sur ${n}` : `\nles ${n} vérifications passent`);
