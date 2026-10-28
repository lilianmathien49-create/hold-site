// Faux DOM minimal : on ne teste pas le navigateur, on teste que le tableau de
// bord rende vraiment quelque chose à partir d'un profil mesuré — et surtout
// qu'il ne rende rien de faux quand le profil dit « non mesurable ».
const LIGHT = { '--mark': '#C5342C', '--grid': 'rgba(21,23,26,.10)',
  '--text': '#15171A', '--muted': '#595D64', '--dim': '#666B72' };
function mkEl(id) {
  return { id, _a: {}, _c: [], _t: '', clientWidth: 760, clientHeight: 380, value: '',
    setAttribute(k, v) { this._a[k] = String(v); }, getAttribute(k) { return this._a[k] ?? null; },
    append(...c) { this._c.push(...c); }, replaceChildren(...c) { this._c = c; },
    appendChild(c) { this._c.push(c); return c; },
    addEventListener(t, f) { (this._h = this._h || {})[t] = f; },
    querySelector() { return mkEl('x'); }, querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    get textContent() { return this._t; }, set textContent(v) { this._t = String(v); },
    get innerHTML() { return this._t; }, set innerHTML(v) { this._t = String(v); },
    dataset: {}, hidden: false, tabIndex: 0, focus() {}, select() {}, style: {}, checked: false };
}
const IDS = {};
globalThis.getComputedStyle = () => ({ getPropertyValue: (n) => LIGHT[n] || '' });
globalThis.document = {
  getElementById: (id) => (IDS[id] = IDS[id] || mkEl(id)),
  createElement: (t) => mkEl(t), createElementNS: (ns, t) => mkEl(t),
  querySelectorAll: () => [], addEventListener() {}, body: mkEl('body'),
};
globalThis.window = { addEventListener() {}, location: { hash: '', search: '' },
  matchMedia: () => ({ matches: false, addEventListener() {} }) };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = globalThis.localStorage;
globalThis.atob = (s) => s; globalThis.btoa = (s) => s;
globalThis.crypto = { subtle: {}, getRandomValues: (a) => a };
globalThis.TextEncoder = class { encode(s) { return new Uint8Array(s.length); } };
globalThis.TextDecoder = class { decode() { return '{}'; } };
globalThis.fetch = () => Promise.reject(new Error('pas de réseau en test'));
globalThis.console = { error: (...a) => print('  [err] ' + a.map(String).join(' ')), warn() {}, log() {} };
