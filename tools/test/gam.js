// Vérifie le contrat entre fit_gam.py et l'onglet « Mes aptitudes » : un champ
// que le profil met à null disparaît de l'écran, sans trou ni « undefined ».
// PROFIL est injecté par tools/test/run.py.
const prof = JSON.parse(PROFIL);
let ko = 0, n = 0;
function check(label, cond) {
  n++;
  if (!cond) { ko++; print('  KO   ' + label); } else print('  OK   ' + label);
}
const sp = prof.speed || {};
const plan = {
  gam: prof,
  model: { walkThr: (prof.walk || {}).thr0 ?? null, walkDecay: null, fatigue: sp.lossPerHour1to3 ?? null,
    params: { 'seuil de marche': 'mesuré', 'durabilité': 'référence' } },
  sections: [{ cls: 'raide', vam: 520, up: 400 }, { cls: 'montee', vam: 600, up: 200 }, { cls: 'plat', up: 10 }],
};
let html;
try {
  html = aptitudes(plan);
} catch (e) {
  print('  KO   aptitudes a levé : ' + e);
  print('\n1 échec'); return;
}
const has = (s) => html.includes(s);
check('rend quelque chose', html.length > 300);
check('aucun NaN affiché', !has('NaN'));
check('aucun undefined affiché', !has('undefined'));
check('aucun null affiché', !/>\s*null\s*</.test(html));
check('quatre tuiles au plus', (html.match(/class="big"/g) || []).length <= 4);
check('vitesse ascensionnelle pondérée par le dénivelé (547 m/h)', has('547 m/h'));
check('une valeur de référence est dite comme telle', !plan.model.fatigue || has('valeur de référence'));
const badText = html.match(/\d+\.\d+\s*(%|km\/h|m\/h)/);
check('nombres au format français', !badText);
if (badText) print('       trouvé : ' + badText[0]);
print(ko ? `\n${ko} échec(s) sur ${n}` : `\nles ${n} vérifications passent`);
