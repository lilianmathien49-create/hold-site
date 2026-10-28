// Vérifie le contrat entre fit_gam.py et le tableau de bord : tout champ que
// le profil met à null doit disparaître de l'écran, sans laisser de trou ni de
// « undefined ». PROFIL est injecté par tools/test/run.py.
const prof = JSON.parse(PROFIL);
let ko = 0, n = 0;
function check(label, cond) {
  n++;
  if (!cond) { ko++; print('  KO   ' + label); } else print('  OK   ' + label);
}
let html;
try {
  html = gamCharts({ gam: prof, speed: prof.speed });
} catch (e) {
  print('  KO   gamCharts a levé : ' + e);
  print('\n1 échec'); return;
}
const has = (s) => html.includes(s);

check('rend quelque chose', html.length > 1000);
check('aucun NaN affiché', !has('NaN'));
check('aucun undefined affiché', !has('undefined'));
check('aucun null affiché', !/>\s*null\s*</.test(html));
// Un profil d'avant la mesure de couverture ne doit pas faire apparaître de
// bloc vide : la section est là si et seulement si le profil la porte.
check('la couverture est annoncée si et seulement si elle est mesurée',
  has('Ce que tes données mesurent') === !!(prof.coverage || {}).hours);

const gaps = ['threshold', 'decay', 'durability', 'heat']
  .filter((k) => ((prof.coverage || {})[k] || {}).ok === false);
check(`les ${gaps.length} lacune(s) du profil sont annoncées`,
  gaps.length === 0 || has('ne mesurent pas encore'));

// Le piège qu'on a corrigé : un coût de chaleur estimé entre saisons donnait
// une FC qui BAISSE quand il fait chaud. Le profil le met à null ; l'écran ne
// doit plus en parler, et doit parler du coût en vitesse à la place.
const hrTemp = (prof.hr || {}).temp;
check('courbe FC/température affichée seulement si mesurée',
  has('chaleur coûte à ton cœur') === !!hrTemp);
if (prof.heatSpeed) {
  check('le coût chaleur en vitesse est affiché', has('chaleur te coûte en vitesse'));
  // Un résultat nul doit être dit comme tel — « non mesurable » — et surtout
  // pas comme une absence d'effet : la méthode est connue pour sous-estimer.
  check('une absence de mesure est dite, pas conclue',
    prof.heatSpeed.sure || (has('Non mesurable') && !has("n'est pas ton facteur limitant")));
}
// Pas de point décimal à l'anglaise : ni dans le texte, ni sur les axes, où
// un yFmt maison contourne facilement le formateur par défaut du graphique.
const badText = html.match(/\d+\.\d+\s*(%|km\/h|bpm|°)/);
check('nombres au format français dans le texte', !badText);
if (badText) print('       trouvé : ' + badText[0]);
const badAxis = [...html.matchAll(/class="ch-lab[^"]*">(-?\d+\.\d+)</g)].map((m) => m[1]);
check('graduations au format français', badAxis.length === 0);
if (badAxis.length) print('       trouvé : ' + badAxis.slice(0, 6).join(' '));

// Une courbe ne doit pas dépasser l'intervalle que les données couvrent.
const hrHours = (prof.hr || {}).hours, mx = (prof.coverage || {}).maxHours;
if (hrHours && mx) {
  check(`courbe horaire bornée à ${mx} h`, Math.max(...hrHours.map((p) => p[0])) <= mx + 0.1);
}
print(ko ? `\n${ko} échec(s) sur ${n}` : `\nles ${n} vérifications passent`);
