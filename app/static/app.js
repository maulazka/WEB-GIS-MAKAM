'use strict';

const $ = (id) => document.getElementById(id);
const esc = (v) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[
        c
      ],
  );
const number = (v) => Number(v || 0).toLocaleString('id-ID');
const fmtDate = (v) =>
  v ? new Date(v + 'T00:00:00').toLocaleDateString('id-ID') : 'Belum didata';
const defaultAdminLabel = $('admin-toggle').textContent.trim();
let csrf = '',
  page = 1,
  total = 0,
  view = 'home',
  blocks = { features: [] },
  features = { features: [] },
  statistics = {},
  selected = '',
  preview = '',
  loadVersion = 0;
let map = null,
  graveLayer = null,
  blockLayer = null,
  allBounds = null,
  layers = null,
  osmBase = null,
  satelliteBase = null,
  imageryBase = null,
  basemapUrl = '',
  imageryBounds = null;
let appConfig = {},
  mapNeedsFit = true,
  homeMap = null,
  homeBlockLayer = null,
  homePhotoLayer = null,
  homePhotoUrl = '',
  statisticsRequest = 0;
const palette = ['#087c8c', '#516ab3', '#b16c2e', '#78468d', '#c34852'];
let toastTimer;

function toast(message, error = false) {
  $('toast').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.add('hidden'), 6000);
}
async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (csrf) headers['X-CSRF-Token'] = csrf;
  if (options.body && !(options.body instanceof FormData))
    headers['Content-Type'] = 'application/json';
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    let body;
    try {
      body = await res.json();
    } catch {
      body = { detail: 'Server tidak dapat diakses.' };
    }
    if (res.status === 401 && csrf) {
      csrf = '';
      renderAuth();
    }
    throw new Error(
      typeof body.detail === 'string' ? body.detail : 'Periksa format isian.',
    );
  }
  return res.json();
}
function params() {
  const p = new URLSearchParams();
  [
    ['q', 'q'],
    ['block', 'block'],
    ['status', 'status'],
    ['year-from', 'year_from'],
    ['year-to', 'year_to'],
  ].forEach(([id, key]) => {
    const value = $(id).value.trim();
    if (value) p.set(key, value);
  });
  return p;
}

function switchView(next, reload = true) {
  if (!$('view-' + next)) return;
  view = next;
  document
    .querySelectorAll('.view')
    .forEach((el) => el.classList.toggle('hidden', el.id !== 'view-' + next));
  const showSearch = next === 'map' || next === 'table';
  $('search-sidebar').classList.toggle('hidden', !showSearch);
  $('workspace').classList.toggle('workspace-wide', !showSearch);
  document.querySelectorAll('[data-view]').forEach((button) => {
    const active =
      button.dataset.view === next ||
      (next === 'infographics' &&
        button.classList.contains('nav') &&
        button.dataset.view === 'home');
    button.classList.toggle('active', active);
    if (button.classList.contains('nav')) {
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
  });
  if (next === 'map' && map)
    setTimeout(() => {
      map.invalidateSize();
      if (mapNeedsFit && allBounds?.isValid()) {
        map.fitBounds(allBounds, { padding: [30, 30] });
        mapNeedsFit = false;
      }
    }, 50);
  if (next === 'home' && homeMap)
    setTimeout(() => {
      homeMap.invalidateSize();
      fitHomePreview();
    }, 50);
  if (next === 'table')
    loadTable().catch((error) => toast(error.message, true));
  if (reload && ['home', 'stats', 'infographics'].includes(next))
    loadStatistics().catch((error) => {
      for (const id of ['stats-updated', 'infographic-updated'])
        $(id).textContent =
          'Ringkasan gagal dimuat. Muat ulang halaman untuk mencoba kembali.';
      toast(error.message, true);
    });
}
document
  .querySelectorAll('[data-view]')
  .forEach((btn) => (btn.onclick = () => switchView(btn.dataset.view)));
$('admin-toggle').onclick = $('empty-admin').onclick = () =>
  switchView('admin');


const blockOutlines = { A: '#ef4444', B: '#38bdf8', C: '#facc15' };
function blockColor(id) {
  const fixed = blockOutlines[String(id).trim().toUpperCase()];
  if (fixed) return fixed;
  const i = blocks.features.findIndex((b) => b.properties.id === id);
  return palette[Math.max(0, i) % palette.length];
}
function graveColor(p) {
  const mode = $('mode').value;
  if (mode === 'status') return p.complete ? '#258764' : '#ad782b';
  if (mode === 'year') {
    if (!p.year) return '#7d8d97';
    if (p.year < 2010) return '#516ab3';
    if (p.year < 2020) return '#087c8c';
    return '#b16c2e';
  }
  return blockColor(p.block_id);
}
function legend() {
  const mode = $('mode').value;
  let rows = blocks.features.map((b) => [
    blockColor(b.properties.id),
    b.properties.name,
  ]);
  if (mode === 'status')
    rows = [
      ['#258764', 'Lengkap'],
      ['#ad782b', 'Belum lengkap'],
    ];
  if (mode === 'year')
    rows = [
      ['#516ab3', 'Sebelum 2010'],
      ['#087c8c', '2010–2019'],
      ['#b16c2e', '2020 dan setelahnya'],
      ['#7d8d97', 'Tahun belum diketahui'],
    ];
  if (mode === 'density')
    rows = [
      ['#edf5f8', 'Lebih rendah'],
      ['#103f58', 'Lebih tinggi'],
      ['#7d8d97', 'Tanpa data kepadatan'],
    ];
  const outlines = mode !== 'density';
  $('legend').innerHTML =
    /* HTML */ `<strong>` +
    esc(mode === 'density' ? 'Makam / 1.000 m²' : 'LEGENDA :') +
    /* HTML */ `</strong>` +
    rows
      .map(
        ([c, t]) => /* HTML */ `
          <div>
            <i
              class="swatch ${outlines ? 'outline-swatch' : ''}"
              style="${outlines ? 'border-color' : 'background'}:${c}"
            ></i>
            ${esc(t)}
          </div>
        `,
      )
      .join('') +
    (outlines
      ? /* HTML */ `
          <p class="legend-note"></p>
        `
      : '');
  $('legend').classList.toggle('hidden', !rows.length);
}

function satelliteTiles() {
  return L.esri.basemapLayer('Imagery', {
    minZoom: 0,
    maxZoom: 23,
    maxNativeZoom: 19,
    attribution:
      'Esri, Vantor, Earthstar Geographics, and the GIS User Community',
  });
}
function createMap(config) {
  if (typeof L === 'undefined') {
    toast(
      'Pustaka peta belum tersedia. Jalankan scripts/vendor_leaflet.py.',
      true,
    );
    return;
  }
  map = L.map('map', { zoomControl: true }).setView([-7.29, 112.81], 14);
  osmBase = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 23,
    maxNativeZoom: 19,
    attribution: '© OpenStreetMap contributors',
  });
  const baseLayers = { OpenStreetMap: osmBase };
  if (L.esri?.basemapLayer) {
    satelliteBase = satelliteTiles().addTo(map);
    baseLayers['Satelit · Esri World Imagery'] = satelliteBase;
  } else {
    osmBase.addTo(map);
    toast(
      'Pustaka citra satelit belum tersedia. Salin folder app/static/vendor dari ZIP pembaruan.',
      true,
    );
  }
  layers = L.control.layers(baseLayers, {}, { collapsed: false }).addTo(map);
$('layer-bar').appendChild(layers.getContainer());
  applyBasemap(config);
}
function applyBasemap(config, focus = false) {
  appConfig = { ...appConfig, ...config };
  syncHomeBasemap(appConfig);
  if (!map || !config.tile_url || config.tile_url === basemapUrl) return;
  const meta = config.basemap || {};
  if (imageryBase) {
    layers.removeLayer(imageryBase);
    map.removeLayer(imageryBase);
  }
  const context = L.esri?.basemapLayer
    ? satelliteTiles()
    : L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 23,
        maxNativeZoom: 19,
        attribution: '© OpenStreetMap contributors',
      });
  const photo = L.tileLayer(config.tile_url, {
    minZoom: 0,
    minNativeZoom: meta.min_zoom ?? 0,
    maxZoom: 23,
    maxNativeZoom: meta.max_native_zoom ?? 23,
    bounds: meta.bounds,
    attribution: 'Foto udara TPU Keputih',
  });
  imageryBase = L.layerGroup([context, photo]);
  layers.addBaseLayer(imageryBase, 'Foto udara');
  map.removeLayer(osmBase);
  if (satelliteBase) map.removeLayer(satelliteBase);
  imageryBase.addTo(map);
  basemapUrl = config.tile_url;
  if (meta.bounds) {
    imageryBounds = L.latLngBounds(meta.bounds);
    if (!allBounds) allBounds = imageryBounds;
    if (view === 'map' && (focus || !blocks.features.length))
      map.fitBounds(imageryBounds, { padding: [30, 30], maxZoom: 21 });
    else mapNeedsFit = true;
  }
  $('map-empty').classList.add('hidden');
}

function createHomePreview(config) {
  if (typeof L === 'undefined') return;
  homeMap = L.map('home-preview-map', {
    zoomControl: false,
    scrollWheelZoom: false,
    dragging: false,
    boxZoom: false,
    doubleClickZoom: false,
    touchZoom: false,
    keyboard: false,
  }).setView([-7.29, 112.81], 14);
  const context = L.esri?.basemapLayer
    ? satelliteTiles()
    : L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 23,
        maxNativeZoom: 19,
        attribution: '© OpenStreetMap contributors',
      });
  context.addTo(homeMap);
  syncHomeBasemap(config);
}

function syncHomeBasemap(config) {
  if (!homeMap) return;
  $('home-basemap-label').textContent = config.tile_url
    ? 'Foto udara proyek'
    : L.esri?.basemapLayer
      ? 'Basemap satelit'
      : 'OpenStreetMap';
  if (!config.tile_url || config.tile_url === homePhotoUrl) return;
  if (homePhotoLayer) homeMap.removeLayer(homePhotoLayer);
  const meta = config.basemap || {};
  homePhotoLayer = L.tileLayer(config.tile_url, {
    minZoom: 0,
    minNativeZoom: meta.min_zoom ?? 0,
    maxZoom: 23,
    maxNativeZoom: meta.max_native_zoom ?? 23,
    bounds: meta.bounds,
    attribution: 'Foto udara TPU Keputih',
  }).addTo(homeMap);
  homePhotoUrl = config.tile_url;
}

function fitHomePreview() {
  if (!homeMap) return;
  const bounds = homeBlockLayer?.getBounds();
  if (bounds?.isValid())
    homeMap.fitBounds(bounds, { padding: [28, 28], maxZoom: 18 });
  else if (imageryBounds?.isValid())
    homeMap.fitBounds(imageryBounds, { padding: [12, 12], maxZoom: 18 });
}

function syncHomePreview() {
  const count = blocks.features.length;
  $('home-preview-status').textContent = count
    ? `${number(count)} blok terdaftar. Buka Peta untuk melihat lokasi makam.`
    : 'Batas blok belum dimasukkan. Basemap menampilkan konteks lokasi.';
  if (!homeMap) return;
  if (homeBlockLayer) homeMap.removeLayer(homeBlockLayer);
  homeBlockLayer = L.geoJSON(blocks, {
    style: (feature) => ({
      color: blockColor(feature.properties.id),
      weight: 2.5,
      fillOpacity: 0,
    }),
  }).addTo(homeMap);
  if (view === 'home') fitHomePreview();
}

function draw() {
  legend();
  if (!map) return;
  if (graveLayer) {
    layers.removeLayer(graveLayer);
    map.removeLayer(graveLayer);
  }
  if (blockLayer) {
    layers.removeLayer(blockLayer);
    map.removeLayer(blockLayer);
  }
  const densities = (statistics.blocks || []).map(
      (b) => b.density_per_1000m2 || 0,
    ),
    max = Math.max(...densities, 1);
  blockLayer = L.geoJSON(blocks, {
    style: (f) => {
      const density = statistics.blocks?.find(
        (b) => b.id === f.properties.id,
      )?.density_per_1000m2;
      const d = $('mode').value === 'density';
      return {
        color: blockColor(f.properties.id),
        weight: 2,
        fillColor: d ? '#103f58' : blockColor(f.properties.id),
        fillOpacity: d ? 0.12 + (0.65 * (density || 0)) / max : 0,
      };
    },
    onEachFeature: (f, l) => {
      const b = statistics.blocks?.find((b) => b.id === f.properties.id);
      const content = document.createElement('div');
      content.innerHTML = /* HTML */ `
        <strong>${esc(f.properties.name)}</strong>
        <br />
        ${number(b?.total)} makam
        <br />
        Luas ${number(f.properties.area_m2.toFixed(2))} m²
        <br />
        Kepadatan ${number(b?.density_per_1000m2)} makam / 1.000 m²
      `;
      l.bindPopup(content);
    },
  }).addTo(map);
  layers.addOverlay(blockLayer, 'Batas blok');
  graveLayer = L.geoJSON(features, {
    style: (f) => ({
      color: graveColor(f.properties),
      weight: f.properties.id === selected ? 3.5 : 1.5,
      fill: true,
      fillOpacity: 0,
      opacity: 1,
    }),
    onEachFeature: (f, l) => {
      l.on('click', () => openDetail(f.properties.id));
      l.bindTooltip(esc(f.properties.id));
    },
  }).addTo(map);
  layers.addOverlay(graveLayer, 'Makam');
  if (blocks.features.length) allBounds = blockLayer.getBounds();
  else if (features.features.length) allBounds = graveLayer.getBounds();
  $('map-empty').classList.toggle(
    'hidden',
    !!blocks.features.length || !!features.features.length || !!basemapUrl,
  );
}
function focusGrave(id) {
  selected = id;
  switchView('map');
  draw();
  if (map) map.invalidateSize();
  mapNeedsFit = false;
  if (graveLayer)
    graveLayer.eachLayer((layer) => {
      if (layer.feature.properties.id === id) {
        map.fitBounds(layer.getBounds(), { maxZoom: 22, padding: [60, 60] });
      }
    });
  openDetail(id);
}
$('fit').onclick = () => {
  if (map && allBounds?.isValid())
    map.fitBounds(allBounds, { padding: [30, 30] });
};
$('mode').onchange = draw;
async function refresh() {
  const seq = ++loadVersion,
    statsSeq = ++statisticsRequest,
    p = params();
  $('results').innerHTML = /* HTML */ `
    <p class="muted">Memuat hasil…</p>
  `;
  const [geo, list, stats] = await Promise.all([
    api('/api/makam/peta?' + p),
    api('/api/makam?' + p + '&limit=25'),
    api('/api/statistik'),
  ]);
  if (seq !== loadVersion) return;
  features = geo;
  if (statsSeq === statisticsRequest) statistics = stats;
  total = list.total;
  $('result-count').textContent = number(total);
  $('results').innerHTML = list.items.length
    ? list.items
        .map(
          (r) => /* HTML */ `
            <button class="result" data-grave="${esc(r.id)}">
              <strong>${esc(r.name || r.id)}</strong>
              <small>
                ${esc(r.id)} · ${esc(r.block_id)} · ${esc(r.status)}
              </small>
            </button>
          `,
        )
        .join('')
    : /* HTML */ `<p class="muted">` +
      (stats.total
        ? 'Tidak ada makam yang sesuai filter.'
        : 'Data makam belum dimasukkan.') +
      /* HTML */ `</p>`;
  if (total > 25)
    $('results').insertAdjacentHTML(
      'beforeend',
      /* HTML */ `
        <p class="muted">
          25 hasil pertama. Buka Data makam untuk seluruh hasil.
        </p>
      `,
    );
  $('results')
    .querySelectorAll('[data-grave]')
    .forEach((b) => (b.onclick = () => focusGrave(b.dataset.grave)));
  draw();
  renderStats();
  syncHomePreview();
  if (view === 'table') await loadTable();
}
$('search-form').onsubmit = (e) => {
  e.preventDefault();
  const a = $('year-from').value,
    b = $('year-to').value;
  if (a && b && Number(a) > Number(b))
    return toast('Tahun awal harus lebih kecil dari tahun akhir.', true);
  page = 1;
  refresh().catch((e) => toast(e.message, true));
};
$('reset').onclick = () => {
  $('search-form').reset();
  page = 1;
  refresh().catch((e) => toast(e.message, true));
};

async function loadTable() {
  const p = params();
  p.set('page', page);
  const data = await api('/api/makam?' + p);
  total = data.total;
  $('table-body').innerHTML = data.items.length
    ? data.items
        .map(
          (r) => /* HTML */ `
            <tr>
              <td>${esc(r.id)}</td>
              <td>${esc(r.name || 'Belum didata')}</td>
              <td>${esc(r.block_id)}</td>
              <td>${esc(fmtDate(r.death_date))}</td>
              <td>
                <span class="badge ${r.complete ? 'good' : ''}">
                  ${esc(r.status)}
                </span>
              </td>
              <td>${r.verified ? 'Terverifikasi' : 'Belum diverifikasi'}</td>
              <td>
                <button class="button outline" data-grave="${esc(r.id)}">
                  Lihat
                </button>
              </td>
            </tr>
          `,
        )
        .join('')
    : /* HTML */ `
        <tr><td colspan="7">Tidak ada data untuk ditampilkan.</td></tr>
      `;
  $('table-body')
    .querySelectorAll('[data-grave]')
    .forEach((b) => (b.onclick = () => focusGrave(b.dataset.grave)));
  $('page-label').textContent =
    `Halaman ${page} / ${Math.max(1, Math.ceil(total / 25))}`;
  $('prev').disabled = page <= 1;
  $('next').disabled = page * 25 >= total;
}
$('prev').onclick = () => {
  page--;
  loadTable().catch((e) => toast(e.message, true));
};
$('next').onclick = () => {
  page++;
  loadTable().catch((e) => toast(e.message, true));
};

function renderStats() {
  const data = statistics;
  $('summary-total').textContent = number(data.total) + ' makam';
  $('summary-complete').textContent = number(data.complete) + ' data lengkap';
  $('home-total').textContent = number(data.total);
  $('home-blocks').textContent = number(data.blocks?.length);
  $('home-complete').textContent = number(data.complete);
  renderStatisticsSummary(data);
  if (window.WebGISInfographics)
    window.WebGISInfographics.render(data, blockColor);
}

function renderStatisticsSummary(data) {
  const cards = [
    ['Total makam', data.total],
    ['Data lengkap', data.complete],
    ['Belum lengkap', data.incomplete],
    ['Belum diverifikasi', data.unverified],
  ];
  $('stats-cards').innerHTML = cards
    .map(
      ([label, value]) => /* HTML */ `
        <div class="card">
          <span>${esc(label)}</span>
          <strong>${number(value)}</strong>
        </div>
      `,
    )
    .join('');

  $('block-stats').innerHTML = data.blocks?.length
    ? data.blocks
        .map(
          (block) => /* HTML */ `
            <tr>
              <td>${esc(block.name)}</td>
              <td>${number(block.total)}</td>
              <td>${number(block.area_m2)}</td>
              <td>
                ${block.density_per_1000m2 == null
                  ? 'Belum tersedia'
                  : number(block.density_per_1000m2)}
              </td>
              <td>${number(block.complete)}</td>
            </tr>
          `,
        )
        .join('')
    : /* HTML */ `
        <tr><td colspan="5">Batas blok belum dimasukkan.</td></tr>
      `;

  const years = Object.entries(data.years ?? {}).sort(([a], [b]) => {
    if (a === 'Belum diketahui') return 1;
    if (b === 'Belum diketahui') return -1;
    return Number(a) - Number(b);
  });
  const maximum = Math.max(...years.map(([, count]) => count), 1);
  $('year-chart').innerHTML = years.length
    ? years
        .map(
          ([year, count]) => /* HTML */ `
            <div class="year-row">
              <span>${esc(year)}</span>
              <div class="bar-track" aria-hidden="true">
                <div
                  class="bar"
                  style="width:${(count / maximum) * 100}%"
                ></div>
              </div>
              <strong>${number(count)}</strong>
            </div>
          `,
        )
        .join('')
    : /* HTML */ `
        <p class="muted">Data makam belum dimasukkan.</p>
      `;
  $('stats-updated').textContent =
    'Dimuat ' +
    new Date().toLocaleString('id-ID', {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
}

async function loadStatistics() {
  const request = ++statisticsRequest;
  const data = await api('/api/statistik');
  if (request !== statisticsRequest) return;
  statistics = data;
  renderStats();
}

let detailVersion = 0;
async function openDetail(id) {
  const seq = ++detailVersion;
  selected = id;
  $('detail-body').innerHTML = /* HTML */ `
    <p>Memuat informasi makam…</p>
  `;
  if (!$('detail-dialog').open) $('detail-dialog').showModal();
  try {
    const r = await api('/api/makam/' + encodeURIComponent(id));
    if (seq !== detailVersion) return;
    $('detail-body').innerHTML = /* HTML */ `
      <div class="section-label">DETAIL MAKAM</div>
      <h1>${esc(r.name || 'Belum didata')}</h1>
      <span class="badge">${esc(r.id)}</span>
      <dl>
        <dt>Blok</dt>
        <dd>${esc(r.block_id)}</dd>
        <dt>Baris / nomor</dt>
        <dd>${esc(r.row || '—')} / ${esc(r.number || '—')}</dd>
        <dt>Tanggal wafat</dt>
        <dd>${esc(fmtDate(r.death_date))}</dd>
        <dt>Kelengkapan</dt>
        <dd>${esc(r.status)}</dd>
        <dt>Verifikasi</dt>
        <dd>${r.verified ? 'Terverifikasi' : 'Belum diverifikasi'}</dd>
        <dt>Diperbarui</dt>
        <dd>${esc(new Date(r.updated_at).toLocaleString('id-ID'))}</dd>
      </dl>
      <h2>Foto makam</h2>
      <div class="photo-grid">
        ${r.photos
          .map(
            (p) => /* HTML */ `
              <a href="${esc(p.url)}" target="_blank" rel="noopener">
                <img
                  src="${esc(p.url)}"
                  alt="${esc(p.caption)}"
                  loading="lazy"
                />
              </a>
            `,
          )
          .join('')}
      </div>
      ${!r.photos.length
        ? /* HTML */ `
            <p class="muted">Foto belum tersedia.</p>
          `
        : ''}${csrf
        ? /* HTML */ `
            <div class="detail-actions">
              <button id="edit-open" class="button primary">Edit data</button>
              <button id="history-open" class="button outline">
                Riwayat perubahan
              </button>
            </div>
            <div id="edit-container"></div>
            <div id="history-container"></div>
          `
        : ''}
    `;
    if (csrf) {
      $('edit-open').onclick = () => editForm(r);
      $('history-open').onclick = () => showHistory(id);
    }
  } catch (e) {
    $('detail-body').textContent = e.message;
    toast(e.message, true);
  }
}
$('close-detail').onclick = () => $('detail-dialog').close();
$('detail-dialog').addEventListener('click', (e) => {
  if (e.target === $('detail-dialog')) {
    const r = $('detail-dialog').getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      $('detail-dialog').close();
  }
});
function editForm(r) {
  $('edit-container').innerHTML = /* HTML */ `
    <h2>Perbarui atribut</h2>
    <form id="edit-form">
      <label for="edit-name">Nama</label>
      <input id="edit-name" maxlength="200" value="${esc(r.name || '')}" />
      <label for="edit-date">Tanggal wafat</label>
      <input id="edit-date" type="date" value="${esc(r.death_date || '')}" />
      <div class="two">
        <div>
          <label for="edit-row">Baris</label>
          <input id="edit-row" maxlength="80" value="${esc(r.row || '')}" />
        </div>
        <div>
          <label for="edit-number">Nomor</label>
          <input
            id="edit-number"
            maxlength="80"
            value="${esc(r.number || '')}"
          />
        </div>
      </div>
      <label for="edit-verified">Verifikasi</label>
      <select id="edit-verified">
        <option value="false">Belum diverifikasi</option>
        <option value="true">Terverifikasi</option>
      </select>
      <button class="button primary">Simpan atribut</button>
    </form>
    <form id="photo-form">
      <label for="photo-file">Tambah foto (maks. 20 MB)</label>
      <input
        id="photo-file"
        type="file"
        accept="image/jpeg,image/png"
        required
      />
      <button class="button outline">Unggah foto</button>
    </form>
  `;
  $('edit-verified').value = String(r.verified);
  $('edit-form').onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api('/api/admin/makam/' + encodeURIComponent(r.id), {
        method: 'PATCH',
        body: JSON.stringify({
          name: $('edit-name').value || null,
          death_date: $('edit-date').value || null,
          row: $('edit-row').value || null,
          number: $('edit-number').value || null,
          verified: $('edit-verified').value === 'true',
        }),
      });
      toast('Atribut tersimpan.');
      await refresh();
      await openDetail(r.id);
    } catch (e) {
      toast(e.message, true);
    }
  };
  $('photo-form').onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData();
    f.set('file', $('photo-file').files[0]);
    try {
      await api('/api/admin/makam/' + encodeURIComponent(r.id) + '/foto', {
        method: 'POST',
        body: f,
      });
      toast('Foto tersimpan.');
      await refresh();
      await openDetail(r.id);
    } catch (e) {
      toast(e.message, true);
    }
  };
}
async function showHistory(id) {
  try {
    const rows = await api(
      '/api/admin/makam/' + encodeURIComponent(id) + '/riwayat',
    );
    $('history-container').innerHTML =
      /* HTML */ `<h2>Riwayat perubahan</h2>` +
      (rows.length
        ? rows
            .map(
              (a) => /* HTML */ `
                <div class="history-item">
                  <strong>${esc(a.action)}</strong>
                  <br />
                  ${esc(new Date(a.created_at).toLocaleString('id-ID'))} ·
                  ${esc(a.actor)}
                  <br />
                  ${esc(JSON.stringify(a.changes))}
                </div>
              `,
            )
            .join('')
        : /* HTML */ `
            <p class="muted">Belum ada perubahan.</p>
          `);
  } catch (e) {
    toast(e.message, true);
  }
}

function renderAuth() {
  $('login-form').classList.toggle('hidden', !!csrf);
  $('admin-panel').classList.toggle('hidden', !csrf);
  $('admin-toggle').classList.toggle('hidden', !csrf);
  $('admin-toggle').textContent = csrf ? 'Admin' : defaultAdminLabel;
  if (!csrf) {
    preview = '';
    $('preview-panel').classList.add('hidden');
    clearTimeout(imageryTimer);
  } else {
    loadImageryStatus().catch((e) => toast(e.message, true));
  }
}
$('login-form').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password: $('password').value }),
    });
    csrf = r.csrf;
    $('password').value = '';
    renderAuth();
    toast('Login berhasil.');
  } catch (e) {
    toast(e.message, true);
  }
};
$('logout').onclick = async () => {
  try {
    await api('/api/auth/logout', { method: 'POST' });
    csrf = '';
    renderAuth();
    $('detail-dialog').close();
    toast('Anda sudah keluar.');
  } catch (e) {
    toast(e.message, true);
  }
};

$('geo-form').onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData();
  f.set('file', $('geo-file').files[0]);
  try {
    const r = await api(
      '/api/admin/import/geojson?kind=' + $('geo-kind').value,
      { method: 'POST', body: f },
    );
    toast(number(r.imported) + ' fitur berhasil dimasukkan.');
    await loadBlocks();
    await refresh();
    $('geo-file').value = '';
  } catch (e) {
    toast(e.message, true);
  }
};
$('csv-form').onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData();
  f.set('file', $('csv-file').files[0]);
  preview = '';
  $('preview-panel').classList.add('hidden');
  try {
    const r = await api('/api/admin/import/csv/preview', {
      method: 'POST',
      body: f,
    });
    preview = r.preview_id;
    $('preview-count').textContent =
      number(r.count) +
      ' makam akan diperbarui. Maksimal 100 perubahan ditampilkan di bawah.';
    $('preview-list').innerHTML = r.changes
      .map(
        (c) => /* HTML */ `
          <div class="preview-item">
            <strong>${esc(c.id)}</strong>
            <pre>
${esc(
                Object.entries(c.changes)
                  .map(
                    ([k, v]) =>
                      `${k}: ${v.before ?? '(kosong)'} menjadi ${v.after}`,
                  )
                  .join('\n'),
              )}</pre
            >
          </div>
        `,
      )
      .join('');
    $('preview-panel').classList.remove('hidden');
    $('commit').disabled = !r.count;
  } catch (e) {
    toast(e.message, true);
  }
};
$('commit').onclick = async () => {
  try {
    const r = await api('/api/admin/import/csv/commit', {
      method: 'POST',
      body: JSON.stringify({ preview_id: preview }),
    });
    toast(number(r.updated) + ' makam diperbarui.');
    preview = '';
    $('preview-panel').classList.add('hidden');
    await refresh();
  } catch (e) {
    toast(e.message, true);
  }
};
$('cancel-preview').onclick = () => {
  preview = '';
  $('preview-panel').classList.add('hidden');
};
$('export').onclick = () => {
  window.location.href = '/api/admin/export.csv';
};
async function loadBlocks() {
  blocks = await api('/api/blok');
  const old = $('block').value;
  $('block').innerHTML =
    /* HTML */ `<option value="">Semua blok</option>` +
    blocks.features
      .map(
        (b) => /* HTML */ `
          <option value="${esc(b.properties.id)}">
            ${esc(b.properties.name)}
          </option>
        `,
      )
      .join('');
  $('block').value = old;
}

let imageryTimer = null,
  imageryUploading = false,
  rasterCapability = null,
  rasterUpload = null;
function applyRasterUploadConfig(config) {
  const limit = config.raster_upload;
  if (
    !limit ||
    !Number.isSafeInteger(limit.max_bytes) ||
    limit.max_bytes <= 0 ||
    !Number.isSafeInteger(limit.timeout_ms) ||
    limit.timeout_ms <= 0 ||
    typeof limit.label !== 'string'
  ) {
    rasterUpload = null;
    $('raster-upload-details').textContent =
      'Server belum mendukung pembaruan unggahan besar. Perbarui aplikasi dan mulai ulang server.';
    return false;
  }
  rasterUpload = limit;
  $('raster-upload-details').textContent =
    `Baju untuk Rongawi hingga ${limit.label}. Baju yang dipake udah pasti bagus kok wok, ntar ditampilkan di awal loh ya....`;
  return true;
}
async function loadImageryStatus() {
  clearTimeout(imageryTimer);
  if (!csrf) return;
  const data = await api('/api/admin/imagery/status');
  const hasUploadConfig = applyRasterUploadConfig(data);
  rasterCapability = data.capability;
  $('raster-reader-details').textContent = rasterCapability.message;
  const job = data.job;
  const busy = job && !['ready', 'failed'].includes(job.status);
  $('raster-submit').disabled = !hasUploadConfig || imageryUploading || !!busy;
  if (!imageryUploading) {
    $('raster-progress').value = job?.progress ?? 0;
    $('raster-job-status').textContent = job
      ? job.message
      : data.current
        ? 'Foto udara sudah aktif.'
        : 'Belum ada citra yang diproses.';
  }
  if (data.current)
    applyBasemap({ tile_url: data.current.tile_url, basemap: data.current });
  if (busy)
    imageryTimer = setTimeout(
      () =>
        loadImageryStatus().catch((e) => {
          toast(e.message, true);
          imageryTimer = setTimeout(
            () => loadImageryStatus().catch(() => {}),
            5000,
          );
        }),
      3000,
    );
}
function uploadRaster(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(
      'POST',
      `/api/admin/imagery/upload?min_zoom=${encodeURIComponent($('raster-min').value)}&max_zoom=${encodeURIComponent($('raster-max').value)}&crop=${$('raster-crop').value}`,
    );
    xhr.setRequestHeader('X-CSRF-Token', csrf);
    xhr.timeout = rasterUpload.timeout_ms;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(
          new Error(
            'Unggahan ditolak server. Periksa batas ukuran unggahan di hosting.',
          ),
        );
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else
        reject(
          new Error(
            typeof data.detail === 'string'
              ? data.detail
              : 'Unggahan tidak berhasil. Periksa isian.',
          ),
        );
    };
    xhr.onerror = () =>
      reject(new Error('Koneksi terputus saat unggah. Coba lagi.'));
    xhr.ontimeout = () =>
      reject(
        new Error(
          `Unggahan melewati ${rasterUpload.timeout_ms / 3600000} jam. Periksa koneksi lalu coba lagi.`,
        ),
      );
    xhr.send(form);
  });
}
$('imagery-form').onsubmit = async (e) => {
  e.preventDefault();
  const file = $('raster-file').files[0];
  if (!file) return;
  if (!rasterUpload)
    return toast(
      'Server belum diperbarui. Mulai ulang server dari folder proyek terbaru.',
      true,
    );
  if (file.size > rasterUpload.max_bytes)
    return toast(`Ukuran citra maksimum ${rasterUpload.label}.`, true);
  if (Number($('raster-min').value) > Number($('raster-max').value))
    return toast('Zoom awal harus lebih kecil dari zoom maksimum.', true);
  if (
    file.name.toLowerCase().endsWith('.ecw') &&
    rasterCapability &&
    !rasterCapability.ecw
  )
    return toast(rasterCapability.message, true);
  imageryUploading = true;
  clearTimeout(imageryTimer);
  $('raster-submit').disabled = true;
  $('raster-progress').value = 0;
  $('raster-job-status').textContent = 'Mengunggah citra…';
  const form = new FormData();
  form.set('file', file);
  try {
    await uploadRaster(form, (p) => {
      $('raster-progress').value = p;
      $('raster-job-status').textContent =
        p < 100
          ? `Mengunggah citra: ${p}%.`
          : 'Unggahan diterima server. Menyiapkan pengolahan…';
    });
    toast('Citra diterima. Tunggu hingga pengolahan selesai.');
    $('raster-file').value = '';
  } catch (e) {
    toast(e.message, true);
    $('raster-job-status').textContent = e.message;
  } finally {
    imageryUploading = false;
    $('raster-submit').disabled = !rasterUpload;
    await loadImageryStatus().catch((e) => toast(e.message, true));
  }
};

async function boot() {
  switchView('home', false);
  try {
    appConfig = await api('/api/config');
    applyRasterUploadConfig(appConfig);
    createMap(appConfig);
    await loadBlocks();
    await refresh();
    if (view === 'map' && map && allBounds?.isValid()) {
      map.invalidateSize();
      map.fitBounds(allBounds, { padding: [30, 30] });
      mapNeedsFit = false;
    }
    try {
      const session = await api('/api/auth/session');
      csrf = session.csrf;
    } catch {}
    renderAuth();
  } catch (error) {
    toast(error.message, true);
    $('results').innerHTML = /* HTML */ `
      <p class="muted">
        Data tidak berhasil dimuat. Muat ulang halaman untuk mencoba kembali.
      </p>
    `;
    $('home-preview-status').textContent =
      'Data tidak berhasil dimuat. Muat ulang halaman untuk mencoba kembali.';
    ['home-total', 'home-blocks', 'home-complete'].forEach(
      (id) => ($(id).textContent = '—'),
    );
    for (const id of ['stats-updated', 'infographic-updated'])
      $(id).textContent = 'Ringkasan belum berhasil dimuat.';
  }
}
boot();

if (location.hash === '#admin') switchView('admin');
document.addEventListener('keydown', e => {
  if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'k' ) {
    e.preventDefault();
    switchView('admin');
  }
});