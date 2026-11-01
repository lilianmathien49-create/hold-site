// La structure du tableau de bord est une décision de produit, pas un détail :
// quatre onglets au plus, le parcours et le curseur en tête, et le pas de
// 500 m rangé en Méthode. Ces tests existent pour qu'une réécriture ne la
// défasse pas sans qu'on le voie.
const plan = JSON.parse(PLAN);
let ko = 0, n = 0;
function check(label, cond, detail) {
  n++;
  if (!cond) { ko++; print('  KO   ' + label + (detail ? ' — ' + detail : '')); } else print('  OK   ' + label);
}

render(plan);
const html = document.getElementById('planRoot').innerHTML;
const onglets = [...html.matchAll(/data-tab="([a-z]+)"/g)].map((m) => m[1]);
check(`${onglets.length} onglets, trois au plus`, onglets.length <= 3, onglets.join(' '));
check('le premier onglet est la course', onglets[0] === 'course');

function pane(k) {
  const i = html.indexOf(`data-pane="${k}"`);
  if (i < 0) return '';
  const j = html.indexOf('data-pane="', i + 12);
  return html.slice(i, j < 0 ? html.length : j);
}
const course = pane('course');
check('le poste de pilotage est dans « Ma course »', course.includes('id="chartWrap"'));
check('le curseur de temps est dans « Ma course »', course.includes('id="scrub"'));

// Ce qui doit rester hors de la première page : le pas de 500 m et la méthode.
check('le pas de 500 m n’est pas dans « Ma course »', !course.includes('tous les 500 m'));
check('la méthode n’est pas dans « Ma course »', !course.includes('Comment ce plan est calculé'));

// Modélisation et pacing : une portion par intervalle entre deux ravitaillements,
// chacune dépliable sur son profil, son rythme, sa météo et son matériel.
const pac = pane('pacing');
check('l’onglet « Modélisation et pacing » existe', pac.includes('Modélisation et pacing'));
const nPo = (pac.match(/<details class="po">/g) || []).length;
check(`une portion par intervalle de ravitaillements (${nPo}/${plan.aid.length - 1})`, nPo === plan.aid.length - 1);
check('chaque portion a son profil', (pac.match(/<svg class="mp"/g) || []).length === nPo);
check('chaque portion dit son matériel', (pac.match(/>Matériel</g) || []).length === nPo);
check('chaque portion dit son rythme', (pac.match(/>Ton rythme</g) || []).length === nPo);
check('pas de nutrition inventée', !/glucides|g\/h/.test(pac));
check('aucune date en anglais', !/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b|day \d/.test(html));

check('aucun NaN sur la page', !/NaN/.test(html));
check('aucun undefined sur la page', !/undefined/.test(html));
print(ko ? `\n${ko} échec(s) sur ${n}` : `\nles ${n} vérifications passent`);
