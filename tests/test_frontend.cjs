'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..', 'app', 'static');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

function element(attributes = {}) {
  const classes = new Set(
    (attributes.class || '').split(/\s+/).filter(Boolean),
  );
  return {
    id: attributes.id || '',
    attributes,
    dataset: { view: attributes['data-view'] },
    value: attributes.value || (attributes.id === 'mode' ? 'block' : ''),
    textContent: '',
    innerHTML: '',
    disabled: false,
    classList: {
      contains: (value) => classes.has(value),
      add: (value) => classes.add(value),
      remove: (value) => classes.delete(value),
      toggle(value, force) {
        const enabled = force ?? !classes.has(value);
        enabled ? classes.add(value) : classes.delete(value);
        return enabled;
      },
    },
    setAttribute(name, value) {
      attributes[name] = value;
    },
    removeAttribute(name) {
      delete attributes[name];
    },
    addEventListener() {},
    querySelectorAll() {
      return [];
    },
    insertAdjacentHTML(_position, value) {
      this.innerHTML += value;
    },
    showModal() {
      this.open = true;
    },
    close() {
      this.open = false;
    },
  };
}

const elements = [],
  ids = new Map();
for (const match of html.matchAll(/<\w+\b([^>]*)>/g)) {
  const attributes = Object.fromEntries(
    [...match[1].matchAll(/([\w-]+)="([^"]*)"/g)].map((item) => [
      item[1],
      item[2],
    ]),
  );
  if (!attributes.id && !attributes['data-view'] && !attributes.class) continue;
  const node = element(attributes);
  elements.push(node);
  if (node.id) {
    assert(!ids.has(node.id), 'duplicate HTML id: ' + node.id);
    ids.set(node.id, node);
  }
}

let data = {
  total: 0,
  complete: 0,
  incomplete: 0,
  unverified: 0,
  blocks: [],
  years: {},
};
const requests = [],
  timers = [];
let responseFactory = () => structuredClone(data);
const sandbox = {
  console,
  URLSearchParams,
  FormData: class {},
  Date,
  document: {
    getElementById: (id) => ids.get(id),
    createElement: () => element(),
    querySelectorAll: (selector) =>
      elements.filter((node) =>
        selector === '.view'
          ? node.classList.contains('view')
          : selector === '[data-view]' && node.dataset.view,
      ),
  },
  window: {},
  fetch: async (url) => {
    requests.push(url);
    if (url.startsWith('/api/makam?'))
      return { ok: true, json: async () => ({ total: data.total, items: [] }) };
    return { ok: true, json: async () => await responseFactory(url) };
  },
  setTimeout(callback, delay) {
    timers.push({ callback, delay });
    return timers.length;
  },
  clearTimeout() {},
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(path.join(root, 'infographics.js'), 'utf8'),
  sandbox,
);
ids.get('admin-toggle').textContent = '0000';
ids.get('raster-limit').textContent = 'SUKIII SUKII KAMU PASTI WAHYUDI.';
ids.get('raster-capability').textContent = 'Dana di proses BOSKUUU!!!';
ids.get('raster-status').textContent = 'Mana ada, Penipuu anjeng!!!';
const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
vm.runInContext(app.replace(/\nboot\(\);\s*$/, ''), sandbox);
const run = (script) => vm.runInContext(script, sandbox);
const flushResize = () => {
  for (const timer of timers.splice(0)) if (timer.delay <= 50) timer.callback();
};
const allChartMarkup = () =>
  [
    'infographic-cards',
    'block-chart',
    'completion-chart',
    'verification-chart',
    'infographic-year-chart',
    'infographic-block-stats',
  ]
    .map((id) => ids.get(id).innerHTML)
    .join('');

(async () => {
  assert.equal(run('view'), 'home');
  assert(ids.get('search-sidebar').classList.contains('hidden'));
  assert(!ids.get('view-home').classList.contains('hidden'));
  assert(ids.get('view-map').classList.contains('hidden'));
  const hero = elements
    .filter((node) => node.classList.contains('home-action'))
    .map((node) => node.dataset.view);
  assert.deepEqual(hero, ['map', 'infographics', 'about']);
  const headerViews = elements
    .filter((node) => node.classList.contains('nav'))
    .map((node) => node.dataset.view);
  assert.deepEqual(headerViews, ['home', 'map', 'table', 'stats', 'about']);
  assert.equal(
    elements.filter((node) => node.dataset.view === 'infographics').length,
    1,
  );

  run("switchView('map', false)");
  assert(!ids.get('search-sidebar').classList.contains('hidden'));
  assert(!ids.get('workspace').classList.contains('workspace-wide'));
  run("switchView('home', false)");
  assert(ids.get('search-sidebar').classList.contains('hidden'));
  assert(ids.get('workspace').classList.contains('workspace-wide'));
  for (const view of ['stats', 'infographics', 'about', 'admin']) {
    run(`switchView('${view}', false)`);
    assert(ids.get('search-sidebar').classList.contains('hidden'), view);
    assert(!ids.get('view-' + view).classList.contains('hidden'), view);
  }
  run("switchView('table', false)");
  assert(!ids.get('search-sidebar').classList.contains('hidden'));
  const tableNav = elements.find(
    (node) => node.classList.contains('nav') && node.dataset.view === 'table',
  );
  const statsNav = elements.find(
    (node) => node.classList.contains('nav') && node.dataset.view === 'stats',
  );
  assert(tableNav.classList.contains('active'));
  assert(!statsNav.classList.contains('active'));

  sandbox.mapCalls = [];
  run(
    "map={invalidateSize(){mapCalls.push('resize')},fitBounds(){mapCalls.push('fit')}};allBounds={isValid:()=>true};mapNeedsFit=true;switchView('map',false)",
  );
  flushResize();
  assert.deepEqual(sandbox.mapCalls, ['resize', 'fit']);
  sandbox.mapCalls.length = 0;
  run("switchView('home',false);switchView('map',false)");
  flushResize();
  assert.deepEqual(
    sandbox.mapCalls,
    ['resize'],
    'returning to the map preserves an existing zoom',
  );

  run('renderAuth()');
  assert.equal(ids.get('admin-toggle').textContent, '0000');
  run(
    "applyRasterUploadConfig({raster_upload:{max_bytes:6442450944,timeout_ms:14400000,label:'6 GB'}})",
  );
  assert.equal(
    ids.get('raster-limit').textContent,
    'SUKIII SUKII KAMU PASTI WAHYUDI.',
  );
  assert(ids.get('raster-upload-details').textContent.includes('6 GB'));
  await run('loadStatistics()');
  assert.equal(ids.get('home-total').textContent, '0');
  assert(!ids.get('infographic-empty').classList.contains('hidden'));
  assert(
    ids
      .get('infographic-year-chart')
      .innerHTML.includes('Data makam belum dimasukkan'),
  );
  assert(!/NaN|Infinity/.test(allChartMarkup()));
  assert(!ids.get('completion-chart').innerHTML.includes('100%'));

  data = {
    total: 8,
    complete: 3,
    incomplete: 5,
    unverified: 2,
    blocks: [
      {
        id: 'A',
        name: 'Blok A',
        total: 4,
        area_m2: 100,
        density_per_1000m2: 40,
        complete: 2,
      },
      {
        id: 'B',
        name: 'Blok B',
        total: 3,
        area_m2: 150,
        density_per_1000m2: 20,
        complete: 1,
      },
      {
        id: 'C',
        name: 'Blok C',
        total: 1,
        area_m2: 200,
        density_per_1000m2: 5,
        complete: 0,
      },
    ],
    years: { 2022: 3, 2018: 2, 'Belum diketahui': 3 },
  };
  await run('loadStatistics()');
  assert.equal(ids.get('home-total').textContent, '8');
  assert.equal(ids.get('home-blocks').textContent, '3');
  assert.equal(ids.get('home-complete').textContent, '3');
  assert(ids.get('infographic-empty').classList.contains('hidden'));
  assert(
    ids
      .get('completion-chart')
      .innerHTML.includes('Lengkap: 3 dari 8 makam, 38 persen'),
  );
  assert(
    ids
      .get('verification-chart')
      .innerHTML.includes('Terverifikasi: 6 dari 8 makam, 75 persen'),
  );
  assert(ids.get('infographic-block-stats').innerHTML.includes('50%'));
  assert.equal(
    (ids.get('infographic-block-stats').innerHTML.match(/<tr>/g) || []).length,
    3,
  );
  assert.equal(
    (ids.get('block-stats').innerHTML.match(/<tr>/g) || []).length,
    3,
  );
  assert.equal(
    (ids.get('block-stats').innerHTML.match(/<td>/g) || []).length,
    15,
  );
  assert.equal(
    (ids.get('infographic-block-stats').innerHTML.match(/<td>/g) || []).length,
    18,
  );
  assert(ids.get('stats-cards').innerHTML.includes('Belum diverifikasi'));
  assert(ids.get('year-chart').innerHTML.includes('Belum diketahui'));
  const years = ids.get('infographic-year-chart').innerHTML;
  assert(years.indexOf('2018') < years.indexOf('2022'));
  assert(years.indexOf('2022') < years.indexOf('Belum diketahui'));
  assert(!/NaN|Infinity/.test(allChartMarkup()));

  data.blocks[0].name = '<img src=x onerror=alert(1)>';
  await run('loadStatistics()');
  assert(!ids.get('block-chart').innerHTML.includes('<img'));
  assert(ids.get('block-chart').innerHTML.includes('&lt;img'));
  assert(!ids.get('infographic-block-stats').innerHTML.includes('<img'));

  data = {
    total: 2,
    complete: 2,
    incomplete: 0,
    unverified: 0,
    blocks: [],
    years: { 2024: 2 },
  };
  const before = requests.length;
  run("switchView('stats')");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert(requests.slice(before).includes('/api/statistik'));
  await run('loadStatistics()');
  assert.equal(ids.get('home-total').textContent, '2');
  assert(ids.get('completion-chart').innerHTML.includes('100%'));
  assert(
    !ids.get('infographic-year-chart').innerHTML.includes('Belum diketahui'),
  );
  const beforeInfographics = requests.length;
  run("switchView('infographics')");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert(requests.slice(beforeInfographics).includes('/api/statistik'));
  assert(ids.get('search-sidebar').classList.contains('hidden'));
  assert(!ids.get('view-infographics').classList.contains('hidden'));
  assert(ids.get('view-stats').classList.contains('hidden'));
  assert(
    elements
      .find(
        (node) =>
          node.classList.contains('nav') && node.dataset.view === 'home',
      )
      .classList.contains('active'),
  );

  let resolveOlder;
  let responseIndex = 0;
  responseFactory = () =>
    ++responseIndex === 1
      ? new Promise((resolve) => {
          resolveOlder = resolve;
        })
      : structuredClone(data);
  const older = run('loadStatistics()');
  await Promise.resolve();
  const newer = run('loadStatistics()');
  await newer;
  resolveOlder({
    total: 99,
    complete: 0,
    incomplete: 99,
    unverified: 99,
    blocks: [],
    years: {},
  });
  await older;
  assert.equal(
    ids.get('home-total').textContent,
    '2',
    'an older response must not replace newer counts',
  );

  console.log(
    'Frontend checks passed: header menus, Beranda-only infographic entry, separate statistics, preserved admin captions, sidebar visibility, map resize/zoom, empty/populated charts, unknown years, live refresh, safe labels, and response ordering.',
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
