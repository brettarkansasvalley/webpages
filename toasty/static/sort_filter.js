// Minimal client-side sorting and filtering for tables with class 'sortable' and 'filterable'
(function () {
  function compare(a, b, type) {
    if (type === 'number') {
      const na = parseFloat(a.replace(/[^0-9.\-]/g, ''));
      const nb = parseFloat(b.replace(/[^0-9.\-]/g, ''));
      return (isNaN(na) ? 0 : na) - (isNaN(nb) ? 0 : nb);
    }
    // default string compare
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
  }

  function detectType(values) {
    let numeric = 0, total = 0;
    for (const v of values.slice(0, 10)) {
      total++;
      if (/^-?\d{1,3}(,\d{3})*(\.\d+)?$/.test(v) || /^-?\d+(\.\d+)?$/.test(v)) numeric++;
    }
    return numeric > total / 2 ? 'number' : 'string';
  }

  function sortTable(table, colIndex, dir) {
    const tbody = table.tBodies[0];
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const values = rows.map(r => (r.children[colIndex]?.textContent || '').trim());
    const type = detectType(values);

    rows.sort((r1, r2) => {
      const a = (r1.children[colIndex]?.textContent || '').trim();
      const b = (r2.children[colIndex]?.textContent || '').trim();
      const res = compare(a, b, type);
      return dir === 'asc' ? res : -res;
    });
    rows.forEach(r => tbody.appendChild(r));
  }

  function clearIndicators(ths) {
    ths.forEach(th => {
      const i = th.querySelector('.sort-indicator');
      if (i) i.remove();
    });
  }

  function setIndicator(th, dir) {
    const span = document.createElement('span');
    span.className = 'sort-indicator';
    span.textContent = dir === 'asc' ? '▲' : '▼';
    th.appendChild(span);
  }

  function initSorting(table) {
    const ths = Array.from(table.tHead?.querySelectorAll('th') || []);
    ths.forEach((th, idx) => {
      th.addEventListener('click', () => {
        const current = th.getAttribute('data-sort') || 'none';
        const next = current === 'asc' ? 'desc' : 'asc';
        ths.forEach(x => x.setAttribute('data-sort', 'none'));
        th.setAttribute('data-sort', next);
        clearIndicators(ths);
        setIndicator(th, next);
        sortTable(table, idx, next);
      });
    });
  }

  function initFiltering() {
    const input = document.getElementById('tableFilter');
    if (!input) return;
    input.addEventListener('input', filterTable);
  }

  window.filterTable = function filterTable() {
    const input = document.getElementById('tableFilter');
    const q = (input?.value || '').toLowerCase();
    const tables = document.querySelectorAll('table.filterable');
    tables.forEach(table => {
      const rows = table.tBodies[0]?.rows || [];
      Array.from(rows).forEach(tr => {
        const text = tr.textContent?.toLowerCase() || '';
        tr.style.display = text.indexOf(q) >= 0 ? '' : 'none';
      });
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('table.sortable').forEach(initSorting);
    initFiltering();
  });
})();
