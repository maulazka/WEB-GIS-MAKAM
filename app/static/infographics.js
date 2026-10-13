'use strict';

// The dashboard receives the real /api/statistik response from app.js.
// All chart values come from that response, including the unknown-year category.
(function () {
  const get = (id) => document.getElementById(id);
  const escape = (value) =>
    String(value ?? '').replace(
      /[&<>"']/g,
      (char) =>
        ({
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#39;',
        })[char],
    );
  const format = (value) => Number(value ?? 0).toLocaleString('id-ID');
  const percent = (part, total) =>
    total > 0 ? Math.round((part / total) * 100) : null;

  function bars(rows, emptyMessage) {
    if (!rows.length)
      return `<p class="chart-empty">${escape(emptyMessage)}</p>`;
    const maximum = Math.max(...rows.map((row) => row.value), 1);
    return rows
      .map(
        (row) => `
      <div class="chart-row">
        <span class="chart-row-label">${escape(row.label)}</span>
        <div class="chart-track" aria-hidden="true">
          <div class="chart-fill" style="width:${(row.value / maximum) * 100}%;background:${row.color}"></div>
        </div>
        <strong>${format(row.value)}</strong>
      </div>`,
      )
      .join('');
  }

  function donut(
    part,
    total,
    firstLabel,
    secondLabel,
    firstColor,
    secondColor,
  ) {
    const remainder = Math.max(0, total - part);
    const percentage = percent(part, total);
    const angle = total > 0 ? (part / total) * 360 : 0;
    const background =
      total > 0
        ? `conic-gradient(${firstColor} 0deg ${angle}deg, ${secondColor} ${angle}deg 360deg)`
        : '#dce5e9';
    const description =
      total > 0
        ? `${firstLabel}: ${format(part)} dari ${format(total)} makam, ${percentage} persen.`
        : 'Belum ada data makam.';
    return `
      <div class="donut-layout">
        <div class="donut-chart" style="background:${background}" role="img" aria-label="${escape(description)}">
          <div class="donut-center" aria-hidden="true">
            <strong>${percentage === null ? '0' : percentage + '%'}</strong>
            <span>${percentage === null ? 'makam' : escape(firstLabel.toLowerCase())}</span>
          </div>
        </div>
        <div class="chart-key">
          <div><span class="chart-dot" style="background:${firstColor}"></span><span>${escape(firstLabel)}</span><strong>${format(part)}</strong></div>
          <div><span class="chart-dot" style="background:${secondColor}"></span><span>${escape(secondLabel)}</span><strong>${format(remainder)}</strong></div>
          ${total === 0 ? '<p class="chart-empty">Belum ada data makam.</p>' : ''}
        </div>
      </div>`;
  }

  function render(data, blockColor) {
    const total = data.total ?? 0;
    const complete = data.complete ?? 0;
    const verified = Math.max(0, total - (data.unverified ?? 0));
    const blocks = data.blocks ?? [];

    get('infographic-cards').innerHTML = [
      ['Total makam', total, 'Polygon makam terdaftar'],
      ['Data lengkap', complete, 'Identitas dan foto tersedia'],
      ['Terverifikasi', verified, 'Data telah diperiksa'],
      ['Blok terdaftar', blocks.length, 'Cakupan pendataan'],
    ]
      .map(
        ([label, value, detail]) => `
      <div class="card"><span>${escape(label)}</span><strong>${format(value)}</strong><small>${escape(detail)}</small></div>
    `,
      )
      .join('');

    get('block-chart').innerHTML = bars(
      blocks.map((block) => ({
        label: block.name,
        value: block.total,
        color: blockColor(block.id),
      })),
      'Batas blok belum dimasukkan.',
    );

    get('completion-chart').innerHTML = donut(
      complete,
      total,
      'Lengkap',
      'Belum lengkap',
      '#087c8c',
      '#e9c46a',
    );
    get('verification-chart').innerHTML = donut(
      verified,
      total,
      'Terverifikasi',
      'Belum diverifikasi',
      '#516ab3',
      '#dce5e9',
    );

    const years = Object.entries(data.years ?? {}).sort(([a], [b]) => {
      if (a === 'Belum diketahui') return 1;
      if (b === 'Belum diketahui') return -1;
      return Number(a) - Number(b);
    });
    get('infographic-year-chart').innerHTML = bars(
      years.map(([year, value]) => ({
        label: year,
        value,
        color: year === 'Belum diketahui' ? '#7d8d97' : '#087c8c',
      })),
      'Data makam belum dimasukkan.',
    );

    get('infographic-block-stats').innerHTML = blocks.length
      ? blocks
          .map((block) => {
            const share = percent(block.total, total);
            const completion = percent(block.complete, block.total);
            const density = block.density_per_1000m2;
            return `<tr>
        <td><span class="table-block-color" style="border-color:${blockColor(block.id)}"></span>${escape(block.name)}</td>
        <td>${format(block.total)}</td>
        <td>${share === null ? '—' : share + '%'}</td>
        <td>${format(block.area_m2)}</td>
        <td>${density == null ? 'Belum tersedia' : format(density)}</td>
        <td>${format(block.complete)} (${completion === null ? '—' : completion + '%'})</td>
      </tr>`;
          })
          .join('')
      : '<tr><td colspan="6">Batas blok belum dimasukkan.</td></tr>';

    get('infographic-empty').classList.toggle('hidden', total > 0);
    get('infographic-updated').textContent =
      'Dimuat ' +
      new Date().toLocaleString('id-ID', {
        dateStyle: 'medium',
        timeStyle: 'short',
      });
  }

  window.WebGISInfographics = { render };
})();
