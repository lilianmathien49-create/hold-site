// Carte de nuit, noir et blanc, pilotée par le scroll : le coureur avance, le tracé s'allume derrière lui, la caméra l'accompagne.
// kind 'city' : rues de la ville (OpenFreeMap). kind 'mountain' : relief en 3D éclairé par la lune.
import { pointAt } from './gpx.js';

const OFM = 'https://tiles.openfreemap.org/planet';
const SAT = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const DEM = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';

const line = (coords) => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } });
const point = (c) => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: c } });
const NONE = { type: 'FeatureCollection', features: [] };

function webglOk() {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; }
}

function baseStyle(kind) {
  if (kind === 'city') {
    return {
      sources: { osm: { type: 'vector', url: OFM, attribution: '© OpenStreetMap · OpenFreeMap' } },
      layers: [
        { id: 'bg', type: 'background', paint: { 'background-color': '#0B0B0B' } },
        { id: 'park', type: 'fill', source: 'osm', 'source-layer': 'park', paint: { 'fill-color': '#0F0F0F' } },
        { id: 'water', type: 'fill', source: 'osm', 'source-layer': 'water', paint: { 'fill-color': '#000000' } },
        { id: 'building', type: 'fill', source: 'osm', 'source-layer': 'building', minzoom: 12, paint: { 'fill-color': '#151515' } },
        { id: 'roads-minor', type: 'line', source: 'osm', 'source-layer': 'transportation', filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'tertiary']]],
          paint: { 'line-color': '#2B2B2B', 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.3, 15, 1.2] } },
        { id: 'roads-major', type: 'line', source: 'osm', 'source-layer': 'transportation', filter: ['in', ['get', 'class'], ['literal', ['primary', 'secondary', 'trunk', 'motorway']]],
          paint: { 'line-color': '#4A4A4A', 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.6, 15, 2.4], 'line-blur': 0.6 } },
      ],
    };
  }
  return {
    sources: {
      dem: { type: 'raster-dem', tiles: [DEM], encoding: 'terrarium', tileSize: 256, maxzoom: 14, attribution: 'Relief © Mapzen / AWS Terrain Tiles' },
      hs: { type: 'raster-dem', tiles: [DEM], encoding: 'terrarium', tileSize: 256, maxzoom: 14 },
      sat: { type: 'raster', tiles: [SAT], tileSize: 256, maxzoom: 19, attribution: 'Imagerie © Esri, Maxar, Earthstar Geographics' },
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#050505' } },
      { id: 'sat', type: 'raster', source: 'sat', paint: { 'raster-saturation': -1, 'raster-contrast': 0.25, 'raster-brightness-max': 0.5, 'raster-opacity': 0.55 } },
      { id: 'hs', type: 'hillshade', source: 'hs', paint: { 'hillshade-exaggeration': 0.55, 'hillshade-shadow-color': '#000000', 'hillshade-highlight-color': '#8C8C8C', 'hillshade-accent-color': '#1A1A1A', 'hillshade-illumination-direction': 315 } },
    ],
  };
}

const routeLayers = [
  { id: 'route-dim', type: 'line', source: 'route', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': '#FFFFFF', 'line-width': 1.2, 'line-opacity': 0.18 } },
  { id: 'lit-halo', type: 'line', source: 'lit', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': '#FFFFFF', 'line-width': 48, 'line-blur': 34, 'line-opacity': 0.09 } },
  { id: 'lit-glow', type: 'line', source: 'lit', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': '#FFFFFF', 'line-width': 10, 'line-blur': 7, 'line-opacity': 0.45 } },
  { id: 'lit-core', type: 'line', source: 'lit', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': '#FFFFFF', 'line-width': 2.2 } },
  { id: 'head-halo', type: 'circle', source: 'head', paint: { 'circle-radius': 34, 'circle-color': '#FFFFFF', 'circle-opacity': 0.22, 'circle-blur': 1 } },
  { id: 'head', type: 'circle', source: 'head', paint: { 'circle-radius': 5, 'circle-color': '#FFFFFF' } },
];

export function createNightMap(container, { kind, route, view, reduceMotion, getPadding, zones }) {
  if (!window.maplibregl || !webglOk()) return null;
  const base = baseStyle(kind);
  const map = new maplibregl.Map({
    container,
    style: {
      version: 8,
      sources: { ...base.sources, route: { type: 'geojson', data: line(route.points.map((p) => [p.lon, p.lat])) }, lit: { type: 'geojson', data: line([]) }, head: { type: 'geojson', data: NONE }, zones: { type: 'geojson', data: zones || NONE } },
      layers: [...base.layers, ...routeLayers.slice(0, 4),
        // Trail : portions marchées en rouge (au-dessus du tracé allumé), descentes raides en pointillés blancs.
        { id: 'down', type: 'line', source: 'zones', filter: ['==', ['get', 'kind'], 'down'], paint: { 'line-color': '#FFFFFF', 'line-width': 1.8, 'line-dasharray': [1, 2.2], 'line-opacity': 0.75 } },
        { id: 'walk-glow', type: 'line', source: 'zones', filter: ['==', ['get', 'kind'], 'walk'], layout: { 'line-cap': 'round' }, paint: { 'line-color': '#F0443E', 'line-width': 9, 'line-blur': 6, 'line-opacity': 0.45 } },
        { id: 'walk', type: 'line', source: 'zones', filter: ['==', ['get', 'kind'], 'walk'], layout: { 'line-cap': 'round' }, paint: { 'line-color': '#F0443E', 'line-width': 2.8 } },
        ...routeLayers.slice(4)],
    },
    bounds: route.bounds, fitBoundsOptions: { padding: 40 },
    interactive: false, // la caméra suit le scroll, pas la souris
    maxPitch: 75,
    attributionControl: { compact: true },
  });

  let ready = false, introDone = reduceMotion, cam = null, progress = 0, drawn = -1;

  // Étiquettes : départ / arrivée et, pour l'ultra, les grands points de passage.
  const label = (txt, lngLat, cls) => {
    const el = Object.assign(document.createElement('div'), { className: `nl ${cls || ''}` });
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = '<i></i><span></span>';
    el.querySelector('span').textContent = txt;
    return new maplibregl.Marker({ element: el, anchor: 'bottom' }).setLngLat(lngLat);
  };
  const markers = [];
  const a = route.points[0], b = route.points[route.points.length - 1];
  const loop = Math.hypot(a.lon - b.lon, a.lat - b.lat) < 0.002;
  markers.push(label(loop ? `${view.start} · départ et arrivée` : `Départ · ${view.start}`, [a.lon, a.lat], 'nl-main'));
  if (!loop) markers.push(label(`Arrivée · ${view.finish}`, [b.lon, b.lat], 'nl-main'));
  for (const w of route.waypoints) if (/^(Grand )?Col\b|Courmayeur|Champex/.test(w.name)) markers.push(label(w.name, [w.lon, w.lat]));

  const camera = () => {
    const c = map.cameraForBounds(route.bounds, { padding: getPadding(), bearing: view.bearing });
    return c ? { center: maplibregl.LngLat.convert(c.center), zoom: c.zoom, bearing: view.bearing, pitch: view.pitch } : null;
  };
  function slice(k1) {
    const p1 = pointAt(route, k1), pts = route.points, coords = [];
    for (let i = 0; i <= p1.i; i++) coords.push([pts[i].lon, pts[i].lat]);
    coords.push([p1.lon, p1.lat]);
    return coords;
  }

  // Une image par progression : tracé allumé jusqu'au coureur, caméra qui se rapproche au milieu puis se recule à l'arrivée.
  function draw() {
    if (!ready || !cam || progress === drawn) return;
    drawn = progress;
    const k = progress * route.totalKm, p = pointAt(route, k);
    map.getSource('lit').setData(line(k > 0.01 ? slice(k) : []));
    map.getSource('head').setData(progress > 0.002 && progress < 0.999 ? point([p.lon, p.lat]) : NONE);
    const end = Math.max(0, (progress - 0.94) / 0.06);
    map.setPaintProperty('lit-glow', 'line-opacity', 0.45 + 0.4 * end);
    map.setPaintProperty('lit-halo', 'line-opacity', 0.09 + 0.12 * end);
    if (!introDone || reduceMotion) return;
    const s = Math.sin(Math.PI * Math.min(1, progress / 0.94));
    map.jumpTo({
      center: [cam.center.lng + (p.lon - cam.center.lng) * 0.5 * s, cam.center.lat + (p.lat - cam.center.lat) * 0.5 * s],
      zoom: cam.zoom + (view.zoomIn || 0.9) * s,
      bearing: cam.bearing + (view.turn || 20) * (progress - 0.5),
      pitch: cam.pitch + (view.tilt || 18) * s,
    });
  }

  map.on('load', () => {
    ready = true;
    if (kind === 'mountain') {
      try { map.setTerrain({ source: 'dem', exaggeration: view.exaggeration || 1.4 }); } catch (e) { console.warn(e); }
      try { map.setSky({ 'sky-color': '#000000', 'horizon-color': '#262626', 'fog-color': '#050505', 'sky-horizon-blend': 0.5, 'horizon-fog-blend': 0.6, 'fog-ground-blend': 0.3, 'atmosphere-blend': 0.4 }); } catch (e) { console.warn(e); }
    }
    cam = camera();
    markers.forEach((m) => m.addTo(map));
    container.classList.add('lit');
    if (cam && !reduceMotion) {
      // L'arrivée : on tombe du ciel sur la ville, une seule fois.
      map.jumpTo({ ...cam, zoom: cam.zoom - 1.6, pitch: 0, bearing: cam.bearing - 25 });
      map.easeTo({ ...cam, duration: view.introMs || 3200, easing: (t) => 1 - Math.pow(1 - t, 3) });
      map.once('moveend', () => { introDone = true; drawn = -1; draw(); });
    } else if (cam) map.jumpTo(cam);
    drawn = -1; draw();
  });
  map.on('resize', () => { if (!ready) return; cam = camera(); drawn = -1; if (reduceMotion && cam) map.jumpTo(cam); draw(); });

  return {
    map,
    setProgress(f) { progress = Math.max(0, Math.min(1, f)); draw(); },
  };
}
