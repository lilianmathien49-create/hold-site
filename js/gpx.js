// Lecture d'un GPX (trkpt ou rtept) et métriques du parcours.

const R = 6371.0088; // km
const rad = (d) => d * Math.PI / 180;

function haversine(a, b) {
  const dLat = rad(b.lat - a.lat), dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function bearing(a, b) {
  const y = Math.sin(rad(b.lon - a.lon)) * Math.cos(rad(b.lat));
  const x = Math.cos(rad(a.lat)) * Math.sin(rad(b.lat)) - Math.sin(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.cos(rad(b.lon - a.lon));
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

export async function loadGpx(url, { officialKm } = {}) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GPX introuvable : ${url}`);
  const xml = new DOMParser().parseFromString(await res.text(), 'application/xml');
  let nodes = Array.from(xml.getElementsByTagName('trkpt'));
  if (!nodes.length) nodes = Array.from(xml.getElementsByTagName('rtept'));
  if (nodes.length < 2) throw new Error('GPX vide');

  const num = (parent, tag) => { const n = parent?.getElementsByTagName(tag)[0]; return n ? parseFloat(n.textContent) : NaN; };
  const txt = (parent, tag) => parent?.getElementsByTagName(tag)[0]?.textContent.trim() ?? '';

  let pts = nodes.map((n) => ({
    lat: +n.getAttribute('lat'), lon: +n.getAttribute('lon'), ele: num(n, 'ele'),
    d: num(n, 'distance'), // distance officielle en mètres (extension UTMB), si présente
  })).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));

  // Métadonnées officielles (GPX UTMB : <distance> en m, <elevationgain> en m).
  const meta = xml.getElementsByTagName('metadata')[0];
  const metaKm = num(meta, 'distance') / 1000, metaGain = num(meta, 'elevationgain');

  // Points de passage (<wpt>) : ravitaillements, cols, pointages.
  const wpts = Array.from(xml.getElementsByTagName('wpt')).map((w) => ({
    name: txt(w, 'name').replace(/\s+sortie$/i, '').replace(/\s+Sport Center$/i, ''),
    type: txt(w, 'type'), lat: +w.getAttribute('lat'), lon: +w.getAttribute('lon'), ele: num(w, 'ele'), d: num(w, 'distance'),
  })).filter((w) => w.name && Number.isFinite(w.lat));

  // Allège les très gros fichiers (UTMB : souvent > 10 000 points).
  const MAX = 4000;
  if (pts.length > MAX) {
    const step = pts.length / MAX;
    const out = [];
    for (let i = 0; i < MAX; i++) out.push(pts[Math.floor(i * step)]);
    out.push(pts[pts.length - 1]);
    pts = out;
  }

  // Altitudes manquantes : on recopie la dernière connue.
  let last = pts.find((p) => Number.isFinite(p.ele))?.ele ?? 0;
  for (const p of pts) { if (Number.isFinite(p.ele)) last = p.ele; else p.ele = last; }

  // Distance cumulée : celle du fichier quand chaque point la donne, sinon calculée (et recalée sur la distance officielle).
  let km = 0;
  const own = pts.every((p, i) => Number.isFinite(p.d) && (i === 0 || p.d >= pts[i - 1].d));
  if (own) { pts.forEach((p) => { p.km = (p.d - pts[0].d) / 1000; }); km = pts[pts.length - 1].km; }
  else {
    pts[0].km = 0;
    for (let i = 1; i < pts.length; i++) { km += haversine(pts[i - 1], pts[i]); pts[i].km = km; }
    if (officialKm) { const f = officialKm / km; pts.forEach((p) => { p.km *= f; }); km = officialKm; }
  }
  pts.forEach((p) => { delete p.d; });

  // Kilomètre de chaque point de passage : celui du fichier, sinon le point du tracé le plus proche.
  const waypoints = wpts.map((w) => {
    let k = Number.isFinite(w.d) ? w.d / 1000 : NaN;
    if (!Number.isFinite(k)) {
      let best = Infinity;
      for (const p of pts) { const dd = (p.lat - w.lat) ** 2 + (p.lon - w.lon) ** 2; if (dd < best) { best = dd; k = p.km; } }
    }
    return { name: w.name, type: w.type, lat: w.lat, lon: w.lon, ele: Number.isFinite(w.ele) ? w.ele : null, km: k };
  }).filter((w) => w.km > 0.5 && w.km < km - 0.5).sort((a, b) => a.km - b.km);

  // D+ : altitude lissée sur ±100 m (fichiers denses), puis seuil de 3 m, pour ignorer le bruit GPS.
  const sm = pts.map((p, i) => {
    let s = p.ele, c = 1;
    for (let j = i - 1; j >= 0 && p.km - pts[j].km <= 0.1; j--) { s += pts[j].ele; c++; }
    for (let j = i + 1; j < pts.length && pts[j].km - p.km <= 0.1; j++) { s += pts[j].ele; c++; }
    return s / c;
  });
  let gain = 0, ref = sm[0];
  for (const e of sm) { if (e - ref > 3) { gain += e - ref; ref = e; } else if (e < ref) ref = e; }

  let minEle = Infinity, maxEle = -Infinity, w = 180, e = -180, s = 90, n = -90;
  for (const p of pts) {
    minEle = Math.min(minEle, p.ele); maxEle = Math.max(maxEle, p.ele);
    w = Math.min(w, p.lon); e = Math.max(e, p.lon); s = Math.min(s, p.lat); n = Math.max(n, p.lat);
  }

  return {
    points: pts, totalKm: km, gain, minEle, maxEle, bounds: [[w, s], [e, n]], waypoints,
    officialKm: officialKm || (metaKm > 0 ? metaKm : null),
    officialGain: metaGain > 0 ? metaGain : null,
  };
}

// Point interpolé au kilomètre `km`, avec l'indice du segment.
export function pointAt(route, km) {
  const p = route.points;
  if (km <= 0) return { ...p[0], i: 0 };
  if (km >= route.totalKm) return { ...p[p.length - 1], i: p.length - 1 };
  let lo = 0, hi = p.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (p[mid].km <= km) lo = mid; else hi = mid; }
  const a = p[lo], b = p[hi], f = (km - a.km) / Math.max(1e-9, b.km - a.km);
  return { lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f, ele: a.ele + (b.ele - a.ele) * f, km, i: lo };
}
