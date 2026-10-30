// Carrousel des avis : la carte du milieu est en avant, les autres reculent
// dans la scène et pivotent. Le module vit à part parce qu'il est le seul
// morceau d'interface de la page à être testable hors navigateur — et qu'il
// l'est : tools/test/avis.js rejoue ses positions sur un faux DOM.

const $ = (id) => document.getElementById(id);

// Sans ce script les cartes restent en grille : c'est lui qui pose .av-3d et
// prend la main sur les positions, jamais l'inverse — une panne ici laisse les
// avis lisibles les uns sous les autres.
export function initAvis() {
  const scene = $('avisScene');
  if (!scene) return;
  const liste = scene.querySelector('.av-l');
  const cartes = [...liste.children];
  if (cartes.length < 2) return;
  const pts = $('avisPts');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  scene.classList.add('av-3d');

  let actif = 0, minuteur = null, x0 = null;

  // Distance circulaire à la carte active : la dernière est voisine de la
  // première, sinon le carrousel se bloquerait aux extrémités.
  const ecart = (i) => {
    const n = cartes.length;
    let d = (i - actif + n) % n;
    return d > n / 2 ? d - n : d;
  };

  function placer() {
    cartes.forEach((c, i) => {
      const d = ecart(i), a = Math.abs(d);
      c.style.transform = `translate(-50%, -50%) translateX(${d * 50}%)`
        + ` translateZ(${-a * 155}px) rotateY(${-d * 23}deg) scale(${1 - a * 0.07})`;
      c.style.opacity = a > 2 ? '0' : a === 0 ? '1' : a === 1 ? '.6' : '.26';
      c.style.zIndex = String(40 - a);
      c.classList.toggle('av-on', a === 0);
      c.classList.toggle('av-loin', a > 2);
    });
    [...pts.children].forEach((b, i) => b.setAttribute('aria-current', i === actif ? 'true' : 'false'));
  }

  function aller(i, manuel) {
    const n = cartes.length;
    actif = ((i % n) + n) % n;
    placer();
    if (manuel) relancer();
  }

  // Les cartes sont hors flux : la liste n'a plus de hauteur propre et il faut
  // lui donner celle de la plus haute, sans quoi la section se replierait.
  function mesurer() {
    liste.style.setProperty('--h', Math.max(...cartes.map((c) => c.offsetHeight)) + 'px');
  }

  const relancer = () => {
    clearInterval(minuteur);
    if (!reduce) minuteur = setInterval(() => aller(actif + 1), 6000);
  };
  const arreter = () => clearInterval(minuteur);

  cartes.forEach((_, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'av-pt';
    b.setAttribute('aria-label', `Avis ${i + 1} sur ${cartes.length}`);
    b.addEventListener('click', () => aller(i, true));
    pts.append(b);
  });

  scene.querySelectorAll('.av-b').forEach((b) => {
    b.addEventListener('click', () => aller(actif + Number(b.dataset.pas), true));
  });

  // Un glissement fait tourner, un clic sur une carte de côté l'amène devant.
  liste.addEventListener('pointerdown', (e) => { x0 = e.clientX; });
  liste.addEventListener('pointerup', (e) => {
    if (x0 === null) return;
    const dx = e.clientX - x0;
    x0 = null;
    if (Math.abs(dx) > 40) { aller(actif + (dx < 0 ? 1 : -1), true); return; }
    const c = e.target.closest('.av-c');
    const i = c ? cartes.indexOf(c) : -1;
    if (i >= 0 && i !== actif) aller(i, true);
  });
  liste.addEventListener('pointercancel', () => { x0 = null; });

  scene.addEventListener('keydown', (e) => {
    const p = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (p) { e.preventDefault(); aller(actif + p, true); }
  });

  scene.addEventListener('pointerenter', arreter);
  scene.addEventListener('pointerleave', relancer);
  scene.addEventListener('focusin', arreter);
  scene.addEventListener('focusout', relancer);
  window.addEventListener('resize', mesurer);
  if (document.fonts) document.fonts.ready.then(mesurer);

  mesurer();
  placer();
  relancer();
}
