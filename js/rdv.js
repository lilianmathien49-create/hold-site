// Prise de rendez-vous par Calendly, chargée au clic et pas avant.
//
// Le script de Calendly dépose ses propres cookies. Posé dans l'en-tête, il
// les déposerait chez tout le monde, y compris chez les neuf visiteurs sur dix
// qui ne demanderont jamais de créneau — et la page ne pourrait plus écrire
// qu'elle n'en dépose pas. Chargé au premier clic, il n'arrive que chez qui
// l'a demandé.
//
// Et si Calendly ne répond pas, le lien reste un lien : il mène à la même page
// chez eux, dans un nouvel onglet. Sans JavaScript du tout, il y mène aussi.

const CSS = 'https://assets.calendly.com/assets/external/widget.css';
const JS = 'https://assets.calendly.com/assets/external/widget.js';

let promesse = null;

function charger() {
  if (promesse) return promesse;
  promesse = new Promise((ok, ko) => {
    const l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = CSS;
    document.head.append(l);
    const s = document.createElement('script');
    s.src = JS;
    s.async = true;
    s.onload = ok;
    s.onerror = () => { promesse = null; ko(new Error('Calendly injoignable')); };
    document.head.append(s);
  });
  return promesse;
}

export function initRdv() {
  document.querySelectorAll('[data-rdv]').forEach((a) => {
    a.addEventListener('click', (e) => {
      // Un clic qui demande explicitement un onglet reste un clic normal.
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
      e.preventDefault();
      a.setAttribute('aria-busy', 'true');
      if (typeof window.plausible === 'function') window.plausible('Prise de rendez-vous');
      charger()
        .then(() => window.Calendly.initPopupWidget({ url: a.href }))
        .catch(() => window.open(a.href, '_blank', 'noopener'))
        .finally(() => a.removeAttribute('aria-busy'));
    });
  });
}
