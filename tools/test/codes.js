// Le même code doit s'écrire de la même façon en Python et dans le navigateur :
// sinon un coureur tape son code juste et ne trouve pas son espace. Les
// réponses attendues viennent de normalise() dans tools/make-plan.py ;
// tools/test/run.py insère plan/plan.js avant ce fichier.
const VECTEURS = [["Clément Dupont Chamois Aurore 482", "clement-dupont-chamois-aurore-482"], ["  JEAN-PIERRE  O'Neil  ", "jean-pierre-o-neil"], ["Zoé_Ève--Noël.42", "zoe-eve-noel-42"], ["élève à l'école", "eleve-a-l-ecole"], ["Ça-va---bien", "ca-va-bien"], ["cime-ravito-seuil-482", "cime-ravito-seuil-482"], ["Æsir Øre ß", "sir-re"], ["ÉTIENNE  Lefèvre 007", "etienne-lefevre-007"], ["", ""]];
let ko = 0;
for (const [tape, attendu] of VECTEURS) {
  const obtenu = normalise(tape);
  if (obtenu !== attendu) { ko++; print(`  KO   « ${tape} » → « ${obtenu} », attendu « ${attendu} »`); }
  else print(`  OK   « ${tape} » → « ${obtenu} »`);
}
print(ko ? `\n${ko} écart(s) entre Python et le navigateur` : `\nles ${VECTEURS.length} codes s'écrivent pareil en Python et dans le navigateur`);
