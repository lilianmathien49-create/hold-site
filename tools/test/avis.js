// Le carrousel des avis sur un faux DOM. Un carrousel se vérifie sur trois
// choses : une seule carte devant à la fois, aucune carte perdue quand on
// tourne en boucle, et un repli lisible si le script ne part pas. Les deux
// premières se testent ici ; la troisième tient au fait que le mode 3D est
// posé par le script et jamais par la feuille de style.
let ko = 0, n = 0;
function ok(label, cond) {
  n++;
  if (!cond) { ko++; print('  KO   ' + label); } else print('  OK   ' + label);
}

function el(tag) {
  const e = {
    tag, _a: {}, children: [], style: { setProperty(k, v) { this[k] = v; } },
    offsetHeight: 220, dataset: {}, type: '', className: '', _cls: new Set(),
    setAttribute(k, v) { this._a[k] = String(v); },
    getAttribute(k) { return this._a[k] ?? null; },
    append(...c) { this.children.push(...c); },
    addEventListener(t, f) { (this._h = this._h || {})[t] = f; },
    dispatch(t, ev) { if (this._h && this._h[t]) this._h[t](ev || {}); },
    querySelector(s) { return s === '.av-l' ? this._liste : null; },
    querySelectorAll(s) { return s === '.av-b' ? this._boutons : []; },
    closest() { return null; },
  };
  e.classList = {
    add: (c) => e._cls.add(c), remove: (c) => e._cls.delete(c),
    contains: (c) => e._cls.has(c),
    toggle: (c, v) => (v ? e._cls.add(c) : e._cls.delete(c)),
  };
  return e;
}

const N = 5;
const scene = el('div'), liste = el('ul'), pts = el('div');
scene._liste = liste;
for (let i = 0; i < N; i++) liste.children.push(el('li'));
const prec = el('button'), suiv = el('button');
prec.dataset.pas = '-1'; suiv.dataset.pas = '1';
scene._boutons = [prec, suiv];

const IDS = { avisScene: scene, avisPts: pts };
globalThis.document = { getElementById: (id) => IDS[id] || null, createElement: el };
globalThis.window = { addEventListener() {} };
globalThis.matchMedia = () => ({ matches: true });   // pas de minuteur en test
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};

// js/avis.js est inséré avant ce fichier par run.py, export retiré.
initAvis();

const devant = () => liste.children.filter((c) => c.style.opacity === '1');
const zIndex = () => liste.children.map((c) => Number(c.style.zIndex));

ok('le mode 3D est posé par le script', scene.classList.contains('av-3d'));
ok(`un point par avis (${pts.children.length}/${N})`, pts.children.length === N);
ok('une seule carte devant', devant().length === 1);
ok('la carte devant est la plus haute pile',
  Math.max(...zIndex()) === Number(devant()[0].style.zIndex));

// On fait un tour complet : chaque carte doit passer devant une fois, et une
// seule. C'est ce qui casse en premier quand l'écart circulaire est faux.
const vues = new Set();
for (let i = 0; i < N; i++) {
  vues.add(liste.children.indexOf(devant()[0]));
  suiv.dispatch('click');
}
ok(`un tour complet montre les ${N} avis`, vues.size === N);
ok('le tour revient à son point de départ',
  liste.children.indexOf(devant()[0]) === [...vues][0]);

// Et dans l'autre sens, sans se bloquer au bord.
const avant = liste.children.indexOf(devant()[0]);
for (let i = 0; i < N; i++) prec.dispatch('click');
ok('le sens inverse boucle aussi', liste.children.indexOf(devant()[0]) === avant);

ok('aucune carte sans position', liste.children.every((c) => c.style.transform));
ok('aucune carte invisible avec cinq avis',
  liste.children.every((c) => !c.classList.contains('av-loin')));
ok('un seul point est courant',
  pts.children.filter((b) => b.getAttribute('aria-current') === 'true').length === 1);
ok('la liste reçoit une hauteur', liste.style['--h'] === '220px');

print(ko ? `\n${ko} vérification(s) en échec sur ${n}` : `\nles ${n} vérifications passent`);
