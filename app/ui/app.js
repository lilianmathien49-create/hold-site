// Hold, l'interface de l'application de bureau.
//
// Tout le travail se fait côté Python (app/hold.py) : cette page ne fait
// qu'afficher et envoyer. Elle garde un brouillon du coureur ouvert, que
// « Publier » chiffre et pousse sur le site.
(function () {
  'use strict';

  const JETON = document.querySelector('meta[name="hold-jeton"]').content;
  const $ = (id) => document.getElementById(id);
  const LIMITE = 10 * 1024 * 1024;

  async function api(chemin, corps, methode) {
    const r = await fetch(chemin, {
      method: methode || (corps ? 'POST' : 'GET'),
      headers: { 'X-Hold-Jeton': JETON, 'Content-Type': 'application/json' },
      body: corps ? JSON.stringify(corps) : undefined,
    });
    const rep = await r.json().catch(() => ({ erreur: `Réponse illisible (${r.status}).` }));
    if (!r.ok) throw new Error(rep.erreur || `Erreur ${r.status}.`);
    return rep;
  }

  const taille = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1).replace('.', ',')} Mo`
    : `${Math.max(1, Math.round(n / 1024))} Ko`;
  const km = (v) => v == null ? '—' : `${Number(v).toFixed(1).replace('.', ',')} km`;
  const dire = (t, id = 'etat') => { $(id).textContent = t || ''; };

  /* ---------- État ---------- */
  let coureurs = [];
  let brouillon = null;          // le coureur ouvert, tel qu'il sera publié
  let modifie = false;
  let calcul = { gpx: '', dossier: '' };

  function vierge() {
    return { slug: null, coureur: '', titre: '', plan: null, resume: null, fichiers: [], code: '', lien: '' };
  }

  function marque() {
    modifie = true;
    $('publier').disabled = false;
    dire(brouillon.slug ? 'Modifications non publiées.' : 'Pas encore publié.');
  }

  /* ---------- Liste ---------- */
  async function charge() {
    const e = await api('/api/etat');
    coureurs = e.coureurs;
    dessineListe();
    if (!e.cle) ouvreReglages("Ajoute ta clé GitHub pour pouvoir publier.");
  }

  function dessineListe() {
    const f = $('filtre').value.trim().toLowerCase();
    const liste = $('liste');
    const vus = coureurs.filter((c) => !f || `${c.coureur} ${c.titre}`.toLowerCase().includes(f));
    liste.replaceChildren(...vus.map((c) => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'item' + (brouillon && brouillon.slug === c.slug ? ' actif' : '');
      const n = document.createElement('span'); n.className = 'item-n'; n.textContent = c.coureur || 'Sans nom';
      const t = document.createElement('span'); t.className = 'item-t'; t.textContent = c.titre || '';
      const m = document.createElement('span'); m.className = 'item-m';
      m.textContent = [c.plan ? 'stratégie' : '', c.docs ? `${c.docs} doc${c.docs > 1 ? 's' : ''}` : '']
        .filter(Boolean).join(' · ');
      b.append(n, t, m);
      b.addEventListener('click', () => ouvre(c.slug));
      li.append(b);
      return li;
    }));
    if (!vus.length) {
      const li = document.createElement('li');
      li.className = 'liste-vide';
      li.textContent = coureurs.length ? 'Aucun coureur ne correspond.' : 'Aucun coureur pour l’instant.';
      liste.append(li);
    }
  }
  $('filtre').addEventListener('input', dessineListe);

  /* ---------- Fiche ---------- */
  // confirm() n'est pas garanti dans une fenêtre native : une boîte maison.
  function quitterAutorise() {
    if (!modifie) return Promise.resolve(true);
    return new Promise((ok) => {
      const d = $('quitter');
      d.returnValue = '';
      d.addEventListener('close', () => ok(d.returnValue === 'abandonner'), { once: true });
      d.showModal();
    });
  }

  function montre() {
    $('vide').hidden = true;
    $('fiche').hidden = false;
    $('barre').hidden = false;
    $('coureur').value = brouillon.coureur;
    $('titre').value = brouillon.titre;
    codeTouche = false;
    modeCode = brouillon.slug ? 'affiche' : 'nouveau';
    afficheCode();
    if (!brouillon.slug && brouillon.coureur) propose();
    $('blocSuppr').hidden = !brouillon.slug;
    $('confSuppr').value = '';
    $('atelier').hidden = true;
    $('publier').textContent = brouillon.slug ? 'Publier les modifications' : 'Publier et générer le code';
    $('publier').disabled = !modifie;
    dessinePlan();
    dessineDocs();
    dessineListe();
  }

  async function nouveau() {
    if (!(await quitterAutorise())) return;
    brouillon = vierge();
    modifie = false;
    montre();
    dire('Pas encore publié.');
    $('coureur').focus();
  }
  $('nouveau').addEventListener('click', nouveau);

  async function ouvre(slug) {
    if (!(await quitterAutorise())) return;
    dire('Ouverture…');
    try {
      const e = await api('/api/ouvrir', { slug });
      brouillon = { ...vierge(), ...e };
      modifie = false;
      montre();
      dire('À jour avec le site.');
    } catch (err) {
      dire(err.message);
    }
  }

  $('coureur').addEventListener('input', (e) => {
    brouillon.coureur = e.target.value;
    marque();
    // Tant que Lilian n'a pas touché au code, il suit le nom.
    if (!brouillon.slug && !codeTouche) { clearTimeout(minuterieNom); minuterieNom = setTimeout(propose, 350); }
  });

  /* ---------- Le code ----------
     Avant la première publication, le code se choisit : il est proposé à
     partir du nom, et peut être réécrit. Après, il se change par « Changer »,
     qui déplace l'espace sous le nouveau code : l'ancien cesse de marcher. */
  let modeCode = 'nouveau';
  let codeTouche = false;
  let minuterieNom = null;
  let minuterieCode = null;

  function afficheCode() {
    const saisie = modeCode !== 'affiche';
    $('code').hidden = saisie;
    $('codeSaisie').hidden = !saisie;
    $('copierCode').hidden = saisie;
    $('changerCode').hidden = modeCode !== 'affiche';
    $('proposer').hidden = !saisie;
    $('validerCode').hidden = modeCode !== 'edition';
    $('annulerCode').hidden = modeCode !== 'edition';
    $('ligneLien').hidden = !brouillon.slug;
    $('code').textContent = brouillon.code || '';
    $('lien').textContent = brouillon.lien || '';
    if (modeCode === 'affiche') { $('msgCode').textContent = ''; $('msgCode').classList.remove('refus'); }
    if (modeCode === 'nouveau' && !$('codeSaisie').value) {
      $('msgCode').textContent = 'Le code sera proposé dès que tu auras écrit le nom.';
    }
  }

  async function propose() {
    try {
      const { code } = await api('/api/proposer', { coureur: brouillon.coureur });
      $('codeSaisie').value = code;
      verifie();
    } catch (err) { $('msgCode').textContent = err.message; }
  }

  async function verifie() {
    const t = $('codeSaisie').value;
    if (!t.trim()) { $('msgCode').textContent = ''; return; }
    try {
      const r = await api('/api/verifier', { code: t, coureur: brouillon.coureur });
      $('msgCode').classList.toggle('refus', !!r.refus);
      $('msgCode').textContent = r.refus || (r.code !== t.trim()
        ? `Il s'écrira « ${r.code} ». Majuscules, accents et espaces n'y changent rien.`
        : modeCode === 'edition' ? 'Code valable. L’ancien cessera de marcher.' : 'Code valable.');
    } catch (err) { $('msgCode').textContent = err.message; }
  }

  $('codeSaisie').addEventListener('input', () => {
    codeTouche = true;
    if (!brouillon.slug) marque();
    clearTimeout(minuterieCode);
    minuterieCode = setTimeout(verifie, 300);
  });
  $('proposer').addEventListener('click', () => { codeTouche = true; propose(); });
  $('changerCode').addEventListener('click', () => { modeCode = 'edition'; afficheCode(); propose(); $('codeSaisie').focus(); });
  $('annulerCode').addEventListener('click', () => { modeCode = 'affiche'; afficheCode(); });
  $('validerCode').addEventListener('click', async () => {
    $('msgCode').textContent = 'Changement du code…';
    try {
      const r = await api('/api/renommer', { slug: brouillon.slug, code: $('codeSaisie').value });
      Object.assign(brouillon, r);
      modeCode = 'affiche';
      afficheCode();
      await charge();
      $('msgCode').classList.remove('refus');
      $('msgCode').textContent = `Code changé. L’ancien ne marche plus : envoie celui-ci à ${brouillon.coureur || 'ton coureur'}.`;
    } catch (err) {
      $('msgCode').classList.add('refus');
      $('msgCode').textContent = err.message;
    }
  });
  $('titre').addEventListener('input', (e) => { brouillon.titre = e.target.value; marque(); });

  /* ---------- Stratégie ---------- */
  function dessinePlan() {
    const r = brouillon.resume;
    $('retirerPlan').hidden = !brouillon.plan;
    const zone = $('resumePlan');
    if (!r) {
      zone.className = 'resume-vide';
      zone.textContent = 'Aucune stratégie pour l’instant.';
      return;
    }
    zone.className = 'resume';
    const cases = [
      ['Course', r.course || '—'], ['Date', r.date || '—'], ['Objectif', r.objectif || '—'],
      ['Distance', km(r.km)], ['Dénivelé', r.dplus ? `${r.dplus} m` : '—'],
      ['Marché', km(r.marche)], ['De nuit', km(r.nuit)],
    ];
    zone.replaceChildren(...cases.map(([l, v]) => {
      const d = document.createElement('div');
      const a = document.createElement('span'); a.className = 'lib'; a.textContent = l;
      const b = document.createElement('span'); b.className = 'val'; b.textContent = v;
      d.append(a, b);
      return d;
    }));
  }

  $('fabriquer').addEventListener('click', () => {
    $('atelier').hidden = false;
    if (!$('course').value && brouillon.titre) $('course').value = brouillon.titre;
    $('atelier').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  $('fermerAtelier').addEventListener('click', () => { $('atelier').hidden = true; });

  const nomDe = (chemin) => chemin.replace(/\/$/, '').split('/').pop();

  $('choixGpx').addEventListener('click', async () => {
    const { chemins } = await api('/api/choisir', { genre: 'gpx' });
    if (!chemins.length) return;
    calcul.gpx = chemins[0];
    $('nomGpx').textContent = nomDe(calcul.gpx);
    if (!$('course').value) $('course').value = nomDe(calcul.gpx).replace(/\.gpx$/i, '');
  });
  $('choixDossier').addEventListener('click', async () => {
    const { chemins } = await api('/api/choisir', { genre: 'dossier' });
    if (!chemins.length) return;
    calcul.dossier = chemins[0];
    $('nomDossier').textContent = nomDe(calcul.dossier);
    $('sansDossier').hidden = false;
  });
  $('sansDossier').addEventListener('click', () => {
    calcul.dossier = '';
    $('nomDossier').textContent = 'Aucun : réglages de référence';
    $('sansDossier').hidden = true;
  });

  $('atelier').addEventListener('submit', async (e) => {
    e.preventDefault();
    const bouton = $('calculer');
    bouton.disabled = true;
    dire('Calcul en cours… (quelques secondes, davantage avec un gros dossier de séances)', 'etatCalcul');
    $('journalBloc').hidden = true;
    try {
      const r = await api('/api/strategie', {
        gpx: calcul.gpx, dossier: calcul.dossier, course: $('course').value.trim(),
        coureur: brouillon.coureur, depart: $('depart').value, objectif: $('objectif').value.trim(),
        tmin: $('tmin').value, tmax: $('tmax').value,
      });
      brouillon.plan = r.plan;
      brouillon.resume = r.resume;
      if (!brouillon.titre && r.resume.course) { brouillon.titre = r.resume.course; $('titre').value = brouillon.titre; }
      $('journal').textContent = r.journal;
      $('journalBloc').hidden = false;
      dessinePlan();
      marque();
      dire('Stratégie calculée. Relis ce que le calcul a mesuré, puis publie.', 'etatCalcul');
    } catch (err) {
      dire(err.message, 'etatCalcul');
    } finally {
      bouton.disabled = false;
    }
  });

  $('importerPlan').addEventListener('click', async () => {
    try {
      const { plan } = await api('/api/plan', {});
      if (!plan) return;
      if (!plan.segments && !plan.race) throw new Error('Ce fichier ne ressemble pas à une stratégie.');
      brouillon.plan = plan;
      brouillon.resume = {
        course: plan.race, date: plan.date, objectif: plan.goal, km: plan.distanceKm,
        dplus: plan.elevationM, marche: plan.model && plan.model.walkKm, nuit: null,
      };
      dessinePlan();
      marque();
    } catch (err) {
      dire(err.message);
    }
  });

  $('retirerPlan').addEventListener('click', () => {
    brouillon.plan = null;
    brouillon.resume = null;
    dessinePlan();
    marque();
  });

  /* ---------- Documents ---------- */
  const poids = () => brouillon.fichiers.reduce((t, f) => t + (f.taille || 0), 0);

  function dessineDocs() {
    $('docs').replaceChildren(...brouillon.fichiers.map((f, i) => {
      const li = document.createElement('li');
      const n = document.createElement('span'); n.className = 'doc-n'; n.textContent = f.nom;
      const t = document.createElement('span'); t.className = 'doc-t'; t.textContent = taille(f.taille || 0);
      const x = document.createElement('button'); x.type = 'button'; x.className = 'b-lien danger'; x.textContent = 'Retirer';
      x.addEventListener('click', () => { brouillon.fichiers.splice(i, 1); dessineDocs(); marque(); });
      li.append(n, t, x);
      return li;
    }));
    $('depose').textContent = brouillon.fichiers.length
      ? `${taille(poids())} sur ${taille(LIMITE)}. Glisse d'autres fichiers ici.`
      : 'Ou glisse des fichiers ici. Dix mégaoctets au plus par espace.';
  }

  function ajoute(fichiers) {
    for (const f of fichiers) {
      if (poids() + f.taille > LIMITE) { dire(`« ${f.nom} » dépasse la place restante.`); continue; }
      brouillon.fichiers.push(f);
    }
    dessineDocs();
    marque();
  }

  $('ajouterDocs').addEventListener('click', async () => {
    try {
      const { fichiers } = await api('/api/documents', {});
      if (fichiers.length) ajoute(fichiers);
    } catch (err) { dire(err.message); }
  });

  // Glisser-déposer : lu dans la page, sans passer par un dialogue.
  const zone = $('blocDocs');
  ['dragenter', 'dragover'].forEach((t) => zone.addEventListener(t, (e) => {
    e.preventDefault(); zone.classList.add('survol');
  }));
  ['dragleave', 'drop'].forEach((t) => zone.addEventListener(t, () => zone.classList.remove('survol')));
  zone.addEventListener('drop', async (e) => {
    e.preventDefault();
    const lus = [];
    for (const f of Array.from(e.dataTransfer.files)) {
      const octets = new Uint8Array(await f.arrayBuffer());
      let s = '';
      for (let i = 0; i < octets.length; i += 0x8000) s += String.fromCharCode.apply(null, octets.subarray(i, i + 0x8000));
      lus.push({ nom: f.name, type: f.type || 'application/octet-stream', taille: f.size, data: btoa(s) });
    }
    if (lus.length) ajoute(lus);
  });
  // Un fichier lâché à côté de la zone ne doit pas remplacer la page.
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());

  /* ---------- Publier, supprimer ---------- */
  $('publier').addEventListener('click', async () => {
    const b = $('publier');
    b.disabled = true;
    dire('Chiffrement et publication…');
    try {
      const r = await api('/api/publier', {
        slug: brouillon.slug, coureur: brouillon.coureur, titre: brouillon.titre,
        plan: brouillon.plan, fichiers: brouillon.fichiers,
        code: brouillon.slug ? undefined : $('codeSaisie').value,
      });
      const premier = !brouillon.slug;
      Object.assign(brouillon, r);
      modifie = false;
      await charge();
      montre();
      dire(premier
        ? 'Publié. Copie le lien et envoie-le : il marche dans une à deux minutes.'
        : 'Modifications publiées. Le code ne change pas.');
    } catch (err) {
      b.disabled = false;
      dire(err.message);
    }
  });

  $('supprimer').addEventListener('click', async () => {
    if ($('confSuppr').value.trim() !== 'SUPPRIMER') { dire('Tape SUPPRIMER pour confirmer.'); return; }
    try {
      await api('/api/supprimer', { slug: brouillon.slug });
      brouillon = null;
      modifie = false;
      $('fiche').hidden = true;
      $('barre').hidden = true;
      $('vide').hidden = false;
      await charge();
    } catch (err) { dire(err.message); }
  });

  $('voir').addEventListener('click', () => api('/api/lien', { url: brouillon.lien }));

  for (const b of document.querySelectorAll('[data-copie]')) {
    b.addEventListener('click', async () => {
      const t = $(b.dataset.copie).textContent;
      try {
        await navigator.clipboard.writeText(t);
      } catch {
        const r = document.createRange(); r.selectNodeContents($(b.dataset.copie));
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
        document.execCommand && document.execCommand('copy');
      }
      b.textContent = 'Copié';
      setTimeout(() => { b.textContent = 'Copier'; }, 1500);
    });
  }

  /* ---------- Réglages ---------- */
  function ouvreReglages(message) {
    $('etatCle').textContent = message || '';
    $('msgCle').textContent = '';
    $('reglages').showModal();
  }
  $('ouvrirReglages').addEventListener('click', async () => {
    const e = await api('/api/etat');
    ouvreReglages(e.cle ? 'Une clé est enregistrée dans le trousseau du Mac.' : 'Aucune clé enregistrée.');
  });
  $('garderCle').addEventListener('click', async () => {
    $('msgCle').textContent = 'Vérification…';
    try {
      await api('/api/cle', { cle: $('cle').value });
      $('cle').value = '';
      $('msgCle').textContent = '';
      $('reglages').close();
      await charge();
    } catch (err) { $('msgCle').textContent = err.message; }
  });
  $('pageGithub').addEventListener('click', () =>
    api('/api/lien', { url: 'https://github.com/settings/personal-access-tokens/new' }));
  $('oublierCle').addEventListener('click', async () => {
    await api('/api/cle', {}, 'DELETE');
    $('etatCle').textContent = 'Clé retirée du trousseau.';
  });

  /* ---------- Import ---------- */
  $('ouvrirImport').addEventListener('click', () => {
    $('msgImport').textContent = '';
    $('codeImport').value = '';
    $('import').showModal();
  });
  $('importer').addEventListener('click', async () => {
    $('msgImport').textContent = 'Ouverture…';
    try {
      const { slug } = await api('/api/importer', { code: $('codeImport').value });
      $('import').close();
      await charge();
      ouvre(slug);
    } catch (err) { $('msgImport').textContent = err.message; }
  });

  // Une valeur de départ réaliste : dans trois mois, à 7 h.
  const d = new Date(); d.setMonth(d.getMonth() + 3); d.setHours(7, 0, 0, 0);
  $('depart').value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T07:00`;

  charge().catch((err) => dire(err.message));
})();
