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
check(`${onglets.length} onglets, quatre au plus`, onglets.length <= 4, onglets.join(' '));
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
check('le pacing tronçon par tronçon est dans « Ma course »', course.includes('Ton pacing, tronçon par tronçon'));

// Ce qui doit rester hors de la première page : le pas de 500 m et la méthode.
check('le pas de 500 m n’est pas dans « Ma course »', !course.includes('tous les 500 m'));
check('la méthode n’est pas dans « Ma course »', !course.includes('Comment ce plan est calculé'));

// Le pacing : une ligne par tronçon, toutes cliquables ; des mètres par heure
// dans les montées, une allure au kilomètre ailleurs.
const lignes = (course.match(/<tr class="clickrow"/g) || []).length;
check(`une ligne par tronçon (${lignes}/${plan.sections.length})`, lignes === plan.sections.length);
const montees = plan.sections.filter((sg) => (sg.cls === 'raide' || sg.cls === 'montee') && sg.vam).length;
const mh = (course.match(/<span class="ry-u mono">m\/h<\/span>/g) || []).length;
check(`chaque montée a sa vitesse ascensionnelle (${mh}/${montees})`, mh === montees);
check('les autres tronçons ont une allure', (course.match(/<span class="ry-u mono">\/km<\/span>/g) || []).length
  === plan.sections.length - montees);
check('aucune date en anglais', !/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b|day \d/.test(html));

// Le tableau des portions : six colonnes, pas onze.
const thead = course.match(/<thead>(.*?)<\/thead>/s);
if (thead) {
  const cols = (thead[1].match(/<th/g) || []).length;
  check(`le tableau des portions tient en ${cols} colonnes`, cols <= 6);
}
check('aucun NaN sur la page', !/NaN/.test(html));
check('aucun undefined sur la page', !/undefined/.test(html));
print(ko ? `\n${ko} échec(s) sur ${n}` : `\nles ${n} vérifications passent`);
