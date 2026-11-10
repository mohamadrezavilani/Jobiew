/** Synthetic, dependency-free contract tests for homepage-preview JS.
 *  Run: node --test tests/homepage_frontend_v219.test.mjs
 *  This checks browser-like DOM integration, not pixel/screen-reader E2E.
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {fileURLToPath} from 'node:url';
import {resolve, dirname} from 'node:path';
const script = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../backend/companies/static/companies/js/homepage_preview_v219.js'), 'utf8');

const microtasks = async () => {
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
};

function fakeElement(id, document) {
  const listeners = new Map();
  const classes = new Set();
  return {
    id, hidden: false, inert: false, isConnected: true, textContent: '',
    style: {}, dataset: {}, offsetParent: {}, attrs: {}, children: [],
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    setAttribute(name, value) { this.attrs[name] = value; },
    getAttribute(name) { return this.attrs[name]; },
    addEventListener(name, fn) { listeners.set(name, fn); },
    trigger(name, event = {}) { return listeners.get(name)?.(event); },
    focus() { document.activeElement = this; },
    contains(target) { return this === target || this.children.includes(target); },
    appendChild(child) { this.children.push(child); return child; },
    querySelectorAll() { return this.children; },
  };
}
function makeHarness({features = [], fetchFails = false, includeCompany = true} = {}) {
  const docListeners = new Map();
  const document = {activeElement: null, addEventListener(name, fn) { docListeners.set(name, fn); }};
  const ids = Object.fromEntries(['drawer', 'open', 'close', 'scrim', 'home-map', 'map-empty',
    'map-status-title', 'map-status-text'].map(k => [k, fakeElement(k, document)]));
  const background = fakeElement('main', document);
  const body = fakeElement('body', document);
  body.dataset.geojsonUrl = '/api/locations.geojson';
  body.children = [ids.open, background, ids.scrim, ids.drawer];
  ids.drawer.inert = true;
  ids.drawer.children = [ids.close, fakeElement('checkbox', document), fakeElement('link', document)];
  ids.close.offsetParent = {};
  const company = fakeElement('company', document);
  company.dataset.companyId = 'c-1';
  company.href = '/companies/c-1/';
  company.querySelector = () => ({textContent: 'شرکت ساختگی تست'});
  const rows = includeCompany ? [company] : [];
  const requested = [];
  const created = [];
  let pinCount = 0;
  let fetchCount = 0;
  document.body = body;
  document.getElementById = id => ids[id];
  document.querySelectorAll = selector => selector === '.company[data-company-id]' ? rows : [];
  document.createElement = tag => fakeElement(tag, document);
  document.head = {
    appendChild(el) {
      requested.push(el.src || el.href);
      if (el.src?.includes('maplibre-gl.js')) {
        globalContext.maplibregl = {
          Map: class {
            constructor() {}
            addControl() {}
            on(event, handler) { if (event === 'load') queueMicrotask(handler); }
            resize() {}
            setCenter() {}
            setZoom() {}
            fitBounds() {}
          },
          NavigationControl: class {},
          LngLatBounds: class { extend() {} },
          Marker: class {
            constructor() { pinCount++; }
            setLngLat() { return this; }
            setPopup() { return this; }
            addTo() { return this; }
          },
          Popup: class { setDOMContent() { return this; } },
          supported: () => true,
        };
      }
      queueMicrotask(() => el.onload?.());
    },
  };
  const globalContext = {
    document, console, Map, Number, Math, Array, String, Promise, setTimeout,
    fetch: async () => {
      fetchCount++;
      if (fetchFails) throw Error('synthetic 503');
      return {ok: true, json: async () => ({features})};
    },
  };
  globalContext.window = globalContext;
  runInNewContext(script, globalContext, {timeout: 3000});
  return {document, ids, background, requested, get pinCount() {return pinCount;},
    get fetchCount() {return fetchCount;}, docListeners, body};
}

test('no verified locations means no external script/style requests', async () => {
  const h = makeHarness();
  await microtasks();
  assert.equal(h.fetchCount, 1);
  assert.equal(h.requested.length, 0);
  assert.match(h.ids['map-status-title'].textContent, /موقعیت تأییدشده/);
  assert.equal(h.ids['home-map'].hidden, true);
});

test('drawer shields background, traps focus, restores it after Escape', async () => {
  const h = makeHarness();
  await microtasks();
  h.ids.open.focus();
  h.ids.open.trigger('click');
  assert.equal(h.background.inert, true);
  assert.equal(h.ids.open.inert, true);
  assert.equal(h.ids.drawer.inert, false);
  assert.equal(h.document.activeElement, h.ids.close);
  assert.equal(h.ids.open.getAttribute('aria-expanded'), 'true');
  h.docListeners.get('keydown')({key: 'Escape', preventDefault() {}});
  assert.equal(h.background.inert, false);
  assert.equal(h.ids.open.inert, false);
  assert.equal(h.ids.drawer.inert, true);
  assert.equal(h.document.activeElement, h.ids.open);
});

test('verified point initializes map only for company on current page', async () => {
  const h = makeHarness({features: [{geometry:{coordinates:[51.41,35.72]},properties:{company_id:'c-1'}}]});
  await microtasks();
  assert.equal(h.requested.filter(x => x.includes('unpkg.com')).length, 2);
  assert.equal(h.pinCount, 1);
  assert.equal(h.ids['map-empty'].hidden, true);
  assert.equal(h.ids['home-map'].hidden, false);
});

test('unverified or off-page points cannot trigger map CDNs', async () => {
  const h = makeHarness({features: [
    {geometry:{coordinates:[400,0]},properties:{company_id:'c-1'}},
    {geometry:{coordinates:[51.4,35.7]},properties:{company_id:'different'}},
  ]});
  await microtasks();
  assert.equal(h.requested.length, 0);
  assert.equal(h.pinCount, 0);
});

test('no companies means no geojson request at all', async () => {
  const h = makeHarness({includeCompany: false});
  await microtasks();
  assert.equal(h.fetchCount, 0);
  assert.equal(h.requested.length, 0);
});

test('API failure leaves accessible fallback and no CDN request', async () => {
  const h = makeHarness({fetchFails: true});
  await microtasks();
  assert.match(h.ids['map-status-title'].textContent, /بارگیری نشدند/);
  assert.equal(h.requested.length, 0);
  assert.equal(h.ids['home-map'].hidden, true);
});