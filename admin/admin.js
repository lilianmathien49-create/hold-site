// Page admin des espaces coureurs.
//
// Pas de serveur : GitHub sert de stockage, et le site le publie. Tout ce qui
// concerne un coureur est chiffré ici, dans le navigateur, avant de partir :
// le dépôt est public, il ne reçoit que du chiffré, et ni son prénom ni sa
// course n'apparaissent en clair — pas même dans le message de commit.
//
// Le chiffrement est celui de tools/make-plan.py, au paramètre près : PBKDF2-
// SHA256 à 310 000 itérations, AES-GCM 256, sel de 16 octets, vecteur de 12.
// L'espace coureur (plan/plan.js) ouvre indifféremment les deux.
(function () {
  'use strict';

  const DEPOT = 'lilianmathien49-create/hold-site';
  const BRANCHE = 'main';
  const SITE = 'https://holdrunning.fr';
  const ITER = 310000;
  const MOTS = 'cime arete col ravito foulee cadence seuil tempo bitume sentier aurore crete denivele allure'.split(' ');
  // Le coureur télécharge tout l'espace à l'ouverture, et GitHub refuse les
  // envois trop lourds : dix mégaoctets de documents, c'est déjà beaucoup de PDF.
  const LIMITE = 10 * 1024 * 1024;
  const RANGEMENT = 'hold.admin.cle';

  const $ = (id) => document.getElementById(id);
  const utf8 = new TextEncoder();
  const deutf8 = new TextDecoder();

  // Le navigateur peut refuser le stockage (fenêtre privée) : la page marche
  // alors quand même, il faudra simplement recoller la clé à chaque visite.
  const rangement = {
    lire() { try { return localStorage.getItem(RANGEMENT) || ''; } catch { return ''; } },
    ecrire(v) { try { localStorage.setItem(RANGEMENT, v); } catch { /* tant pis */ } },
    effacer() { try { localStorage.removeItem(RANGEMENT); } catch { /* tant pis */ } },
  };
  let jeton = rangement.lire();

  /* ---------- Octets ---------- */
  // Par tranches : String.fromCharCode sur un PDF entier dépasse la pile.
  function versB64(o) {
    let s = '';
    for (let i = 0; i < o.length; i += 0x8000) s += String.fromCharCode.apply(null, o.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function deB64(t) {
    const s = atob(t);
    const o = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) o[i] = s.charCodeAt(i);
    return o;
  }
  const taille = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1).replace('.', ',')} Mo`
    : `${Math.max(1, Math.round(n / 1024))} Ko`;

  /* ---------- Code du coureur ---------- */
  function hasard(n) {
    // Rejet des valeurs du haut de l'intervalle : un modulo seul favoriserait
    // les petits nombres.
    const plafond = Math.floor(0x100000000 / n) * n;
    const a = new Uint32Array(1);
    do { crypto.getRandomValues(a); } while (a[0] >= plafond);
    return a[0] % n;
  }
  function identifiant() {
    const o = crypto.getRandomValues(new Uint8Array(5));
    return Array.from(o, (b) => b.toString(16).padStart(2, '0')).join('');
  }
  // Trois mots et un nombre : dictable au téléphone, comme l'outil en ligne de commande.
  const motDePasse = () => [0, 1, 2].map(() => MOTS[hasard(MOTS.length)]).join('-') + '-' + (100 + hasard(900));

  function decoupe(code) {
    const t = String(code || '').trim();
    const i = t.indexOf('-');
    if (i < 1 || i === t.length - 1) return null;
    return { slug: t.slice(0, i).toLowerCase(), mdp: t.slice(i + 1) };
  }

  /* ---------- Chiffrement ---------- */
  async function cleDe(mdp, sel, iter) {
    const base = await crypto.subtle.importKey('raw', utf8.encode(mdp), 'PBKDF2', false, ['deriveKey']);
    return crypto.subtle.deriveKey({ name: 'PBKDF2', salt: sel, iterations: iter, hash: 'SHA-256' },
      base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  }
  async function chiffre(contenu, mdp) {
    const sel = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const cle = await cleDe(mdp, sel, ITER);
    const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, cle,
      utf8.encode(JSON.stringify(contenu))));
    return { v: 1, iter: ITER, salt: versB64(sel), iv: versB64(iv), data: versB64(ct) };
  }
  async function dechiffre(pack, mdp) {
    const cle = await cleDe(mdp, deB64(pack.salt), pack.iter);
    const clair = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: deB64(pack.iv) }, cle, deB64(pack.data));
    return JSON.parse(deutf8.decode(clair));
  }

  // Même lecture que plan/plan.js : un plan publié avant cette page est une
  // stratégie à nu, sans enveloppe.
  function espaceDe(c) {
    if (c && c.hold === 2) {
      return { coureur: c.coureur || '', titre: c.titre || '', plan: c.plan || null,
        fichiers: Array.isArray(c.fichiers) ? c.fichiers : [] };
    }
    return { coureur: c?.runner || '', titre: c?.race || '', plan: c, fichiers: [] };
  }

  /* ---------- GitHub ---------- */
  async function github(chemin, { methode = 'GET', corps, brut = false } = {}) {
    const entetes = {
      Authorization: `Bearer ${jeton}`,
      Accept: brut ? 'application/vnd.github.raw+json' : 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    };
    if (corps) entetes['Content-Type'] = 'application/json';
    return fetch(`https://api.github.com/repos/${DEPOT}${chemin}`, {
      method: methode, headers: entetes, cache: 'no-store',
      body: corps ? JSON.stringify(corps) : undefined,
    });
  }
  const cheminDe = (slug) => `/contents/plan/data/${encodeURIComponent(slug)}.json`;

  function raison(r) {
    if (r.status === 401) return 'GitHub refuse la clé : elle a peut-être expiré.';
    if (r.status === 403) return "La clé n'a pas le droit d'écrire. Vérifie « Contents : Read and write » sur hold-site.";
    if (r.status === 409 || r.status === 422) return "L'espace a changé entre-temps. Rouvre-le avant de publier.";
    return `GitHub a répondu ${r.status}.`;
  }

  /* ---------- La clé ---------- */
  function montreCle() {
    $('cleAbsente').hidden = !!jeton;
    $('clePresente').hidden = !jeton;
    $('blocEspace').hidden = !jeton;
  }

  $('formCle').addEventListener('submit', async (e) => {
    e.preventDefault();
    const essai = $('cle').value.trim();
    if (!essai) return;
    $('msgCle').textContent = 'Vérification…';
    jeton = essai;
    try {
      const r = await github('/contents/plan/data');
      if (!r.ok) throw new Error(raison(r));
      rangement.ecrire(jeton);
      $('cle').value = '';
      $('msgCle').textContent = '';
      montreCle();
    } catch (err) {
      jeton = '';
      $('msgCle').textContent = err.message.startsWith('GitHub') || err.message.startsWith('La clé')
        ? err.message : "Impossible de joindre GitHub. Vérifie ta connexion.";
    }
  });

  $('oublierCle').addEventListener('click', () => {
    rangement.effacer();
    jeton = '';
    montreCle();
  });

  /* ---------- L'espace en cours ---------- */
  let etat = null;
  const neuf = () => ({ mode: 'nouveau', slug: '', mdp: '', sha: null, plan: null, planNom: '', fichiers: [] });

  function poidsTotal() { return etat.fichiers.reduce((t, f) => t + (f.taille || 0), 0); }

  function dessine() {
    $('etatPlan').textContent = etat.plan
      ? `${etat.plan.race || 'Stratégie'}${etat.plan.distanceKm ? ` · ${Math.round(etat.plan.distanceKm)} km` : ''}${etat.planNom ? ` (${etat.planNom})` : ''}`
      : 'Aucune.';
    $('retirerPlan').hidden = !etat.plan;
    const liste = $('listeDocs');
    liste.replaceChildren(...etat.fichiers.map((f, i) => {
      const li = document.createElement('li');
      const nom = document.createElement('span'); nom.className = 'adm-doc-n'; nom.textContent = f.nom;
      const t = document.createElement('span'); t.className = 'mono adm-doc-t'; t.textContent = taille(f.taille || 0);
      const x = document.createElement('button'); x.type = 'button'; x.className = 'link-btn'; x.textContent = 'Retirer';
      x.addEventListener('click', () => { etat.fichiers.splice(i, 1); dessine(); });
      li.append(nom, t, x);
      return li;
    }));
    const p = poidsTotal();
    $('poids').textContent = etat.fichiers.length
      ? `${etat.fichiers.length} document${etat.fichiers.length > 1 ? 's' : ''} · ${taille(p)} sur ${taille(LIMITE)} possibles`
      : 'PDF, programme de renforcement, séance pour la montre…';
    $('publier').textContent = etat.mode === 'nouveau' ? 'Générer le code et publier' : 'Publier les modifications';
    $('zoneSuppr').hidden = etat.mode !== 'modifier' || !etat.sha;
  }

  function onglet(mode) {
    $('ongletNouveau').setAttribute('aria-selected', String(mode === 'nouveau'));
    $('ongletModifier').setAttribute('aria-selected', String(mode === 'modifier'));
    $('formOuvrir').hidden = mode !== 'modifier';
    $('formEspace').hidden = mode === 'modifier';
    $('resultat').hidden = true;
    $('msgEspace').textContent = '';
    $('msgOuvrir').textContent = '';
    $('coureur').value = '';
    $('titre').value = '';
    etat = neuf();
    etat.mode = mode;
    dessine();
  }
  $('ongletNouveau').addEventListener('click', () => onglet('nouveau'));
  $('ongletModifier').addEventListener('click', () => onglet('modifier'));

  $('fichierPlan').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    e.target.value = '';
    if (!f) return;
    try {
      const plan = JSON.parse(await f.text());
      if (!plan || typeof plan !== 'object' || !(plan.segments || plan.race)) {
        throw new Error("Ce fichier ne ressemble pas à une stratégie : il n'a ni course ni portions.");
      }
      etat.plan = plan;
      etat.planNom = f.name;
      if (!$('coureur').value && plan.runner) $('coureur').value = plan.runner;
      if (!$('titre').value && plan.race) $('titre').value = plan.race;
      $('msgEspace').textContent = '';
    } catch (err) {
      $('msgEspace').textContent = err instanceof SyntaxError ? "Ce fichier n'est pas du JSON lisible." : err.message;
    }
    dessine();
  });

  $('retirerPlan').addEventListener('click', () => { etat.plan = null; etat.planNom = ''; dessine(); });

  $('fichiersDocs').addEventListener('change', async (e) => {
    const choix = Array.from(e.target.files);
    e.target.value = '';
    for (const f of choix) {
      if (poidsTotal() + f.size > LIMITE) {
        $('msgEspace').textContent = `« ${f.name} » dépasse la place restante (${taille(LIMITE - poidsTotal())}).`;
        continue;
      }
      const data = versB64(new Uint8Array(await f.arrayBuffer()));
      etat.fichiers.push({ nom: f.name, type: f.type || 'application/octet-stream', taille: f.size, data });
    }
    dessine();
  });

  /* ---------- Ouvrir un espace existant ---------- */
  $('formOuvrir').addEventListener('submit', async (e) => {
    e.preventDefault();
    // Le formulaire d'édition reste masqué tant que l'espace n'est pas ouvert :
    // les messages d'ouverture s'écrivent donc sous la case du code.
    const msg = (t) => { $('msgOuvrir').textContent = t; };
    const c = decoupe($('codeOuvrir').value);
    if (!c) { msg('Le code ressemble à « a3f9c2e1b7-col-ravito-seuil-482 ».'); return; }
    $('formEspace').hidden = true;
    $('resultat').hidden = true;
    msg('Ouverture…');
    try {
      const meta = await github(cheminDe(c.slug));
      if (meta.status === 404) throw new Error('Aucun espace ne correspond à ce code. Vérifie la partie avant le premier tiret.');
      if (!meta.ok) throw new Error(raison(meta));
      const { sha } = await meta.json();
      const brut = await github(cheminDe(c.slug), { brut: true });
      if (!brut.ok) throw new Error(raison(brut));
      let contenu;
      try { contenu = await dechiffre(await brut.json(), c.mdp); } catch { throw new Error('Code incorrect.'); }
      const es = espaceDe(contenu);
      etat = { mode: 'modifier', slug: c.slug, mdp: c.mdp, sha, plan: es.plan, planNom: '', fichiers: es.fichiers };
      $('coureur').value = es.coureur;
      $('titre').value = es.titre;
      $('msgEspace').textContent = '';
      msg('');
      $('formEspace').hidden = false;
      dessine();
    } catch (err) {
      msg(err.message || "Impossible de joindre GitHub.");
    }
  });

  /* ---------- Publier ---------- */
  $('formEspace').addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = (t) => { $('msgEspace').textContent = t; };
    const coureur = $('coureur').value.trim();
    if (!coureur) { msg('Il faut au moins le prénom du coureur.'); $('coureur').focus(); return; }
    if (!etat.plan && !etat.fichiers.length) { msg('Ajoute une stratégie ou au moins un document.'); return; }
    if (etat.mode === 'modifier' && !etat.sha) { msg("Ouvre d'abord l'espace avec le code du coureur."); return; }

    const bouton = $('publier');
    bouton.disabled = true;
    msg('Chiffrement…');
    try {
      if (etat.mode === 'nouveau') {
        // Un identifiant de dix caractères hexadécimaux ne collisionne pas en
        // pratique, mais une vérification coûte une requête.
        for (let essai = 0; essai < 5; essai++) {
          etat.slug = identifiant();
          const r = await github(cheminDe(etat.slug));
          if (r.status === 404) break;
          if (!r.ok) throw new Error(raison(r));
        }
        etat.mdp = motDePasse();
      }
      const contenu = {
        hold: 2, coureur, titre: $('titre').value.trim(), plan: etat.plan, fichiers: etat.fichiers,
        modifie: new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }),
      };
      const pack = await chiffre(contenu, etat.mdp);
      msg('Publication…');
      const corps = {
        // Rien d'identifiant ici : le message de commit est public.
        message: `Espace ${etat.slug} : ${etat.mode === 'nouveau' ? 'création' : 'mise à jour'}`,
        content: versB64(utf8.encode(JSON.stringify(pack))),
        branch: BRANCHE,
      };
      if (etat.sha) corps.sha = etat.sha;
      const r = await github(cheminDe(etat.slug), { methode: 'PUT', corps });
      if (!r.ok) throw new Error(raison(r));
      etat.sha = (await r.json()).content.sha;
      const code = `${etat.slug}-${etat.mdp}`;
      $('resCode').textContent = code;
      $('resLien').textContent = `${SITE}/plan/#${code}`;
      $('resultat').hidden = false;
      msg(etat.mode === 'nouveau' ? 'Espace publié.' : 'Modifications publiées. Le code ne change pas.');
      etat.mode = 'modifier';
      dessine();
    } catch (err) {
      msg(err.message || 'La publication a échoué.');
    } finally {
      bouton.disabled = false;
    }
  });

  /* ---------- Supprimer ---------- */
  $('formSuppr').addEventListener('submit', async (e) => {
    e.preventDefault();
    if ($('confSuppr').value.trim() !== 'SUPPRIMER') { $('msgEspace').textContent = 'Tape SUPPRIMER pour confirmer.'; return; }
    try {
      const r = await github(cheminDe(etat.slug), {
        methode: 'DELETE', corps: { message: `Espace ${etat.slug} : suppression`, sha: etat.sha, branch: BRANCHE },
      });
      if (!r.ok) throw new Error(raison(r));
      $('confSuppr').value = '';
      onglet('modifier');
      $('msgOuvrir').textContent = 'Espace supprimé. Le coureur n’y a plus accès.';
    } catch (err) {
      $('msgEspace').textContent = err.message;
    }
  });

  /* ---------- Copier ---------- */
  for (const b of document.querySelectorAll('[data-copie]')) {
    b.addEventListener('click', async () => {
      const el = $(b.dataset.copie);
      try {
        await navigator.clipboard.writeText(el.textContent);
        b.textContent = 'Copié';
        setTimeout(() => { b.textContent = 'Copier'; }, 1600);
      } catch {
        const r = document.createRange(); r.selectNodeContents(el);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      }
    });
  }

  montreCle();
  onglet('nouveau');
})();
