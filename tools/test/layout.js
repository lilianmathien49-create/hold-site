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
check('la bande de parcours est dans « Ma course »', course.includes('class="rs-svg"'));

// Ce qui doit rester hors de la première page : le pas de 500 m et la méthode.
check('le pas de 500 m n’est pas dans « Ma course »', !course.includes('tous les 500 m'));
check('la méthode n’est pas dans « Ma course »', !course.includes('Comment ce plan est calculé'));

// La bande : un bloc par portion, rien hors du cadre, tout cliquable.
const strip = raceStrip(plan);
const bars = [...strip.matchAll(/<rect class="rs-bar[^>]*y="([\d.]+)"[^>]*height="([\d.]+)"/g)];
check(`un bloc par portion (${bars.length}/${plan.sections.length})`,
  bars.length === plan.sections.length);
const vb = strip.match(/viewBox="0 0 \d+ ([\d.]+)"/);
const dehors = bars.filter(([, y, h]) => +y < 0 || +y + +h > +vb[1]).length;
check('aucun bloc hors du cadre', dehors === 0, `${dehors} bloc(s)`);
check('chaque bloc amène le curseur',
  (strip.match(/clickrow/g) || []).length === bars.length);
check('chaque bloc dit ce qu’il est', (strip.match(/<title>/g) || []).length === bars.length);

// Le tableau des portions : six colonnes, pas onze.
const thead = course.match(/<thead>(.*?)<\/thead>/s);
if (thead) {
  const cols = (thead[1].match(/<th/g) || []).length;
  check(`le tableau des portions tient en ${cols} colonnes`, cols <= 6);
}
check('aucun NaN sur la page', !/NaN/.test(html));
check('aucun undefined sur la page', !/undefined/.test(html));
print(ko ? `\n${ko} échec(s) sur ${n}` : `\nles ${n} vérifications passent`);
