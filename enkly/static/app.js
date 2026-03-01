/* ============================================
   Enkly — Frontend Application
   ============================================ */

const API = '/api';

// State
const state = {
    model: null,
    selectedMetrics: new Set(),
    selectedDimensions: new Set(),
    lastResult: null,
    showChart: false,
    showSql: false,
    chartInstance: null,
};

// ---- Init ----

document.addEventListener('DOMContentLoaded', async () => {
    await loadModel();
    setupNavigation();
    setupActions();
    setupUploadModal();
});

async function loadModel() {
    try {
        const res = await fetch(`${API}/model`);
        if (!res.ok) throw new Error('Failed to load model');
        state.model = await res.json();
        renderSidebar();
        renderPickers();
    } catch (e) {
        document.getElementById('model-name').textContent = 'Erro ao carregar';
        console.error(e);
    }
}

// ---- Sidebar ----

function renderSidebar() {
    const m = state.model;
    document.getElementById('model-name').textContent = m.display_name;

    const metricsList = document.getElementById('metrics-list');
    metricsList.innerHTML = '';
    for (const [key, met] of Object.entries(m.metrics)) {
        const div = document.createElement('div');
        div.className = 'tag-item';
        div.textContent = met.display_name;
        metricsList.appendChild(div);
    }

    const dimList = document.getElementById('dimensions-list');
    dimList.innerHTML = '';
    for (const [key, dim] of Object.entries(m.dimensions)) {
        const div = document.createElement('div');
        div.className = 'tag-item';
        div.textContent = dim.display_name;
        dimList.appendChild(div);
    }
}

// ---- Chip Pickers ----

function renderPickers() {
    const m = state.model;

    const metricsPicker = document.getElementById('picker-metrics');
    metricsPicker.innerHTML = '';
    for (const [key, met] of Object.entries(m.metrics)) {
        const chip = document.createElement('button');
        chip.className = 'chip';
        chip.textContent = met.display_name;
        chip.dataset.key = key;
        chip.addEventListener('click', () => toggleMetric(key, chip));
        metricsPicker.appendChild(chip);
    }

    const dimPicker = document.getElementById('picker-dimensions');
    dimPicker.innerHTML = '';
    for (const [key, dim] of Object.entries(m.dimensions)) {
        const chip = document.createElement('button');
        chip.className = 'chip chip-dimension';
        chip.textContent = dim.display_name;
        chip.dataset.key = key;
        chip.addEventListener('click', () => toggleDimension(key, chip));
        dimPicker.appendChild(chip);
    }
}

function toggleMetric(key, chip) {
    if (state.selectedMetrics.has(key)) {
        state.selectedMetrics.delete(key);
        chip.classList.remove('selected');
    } else {
        state.selectedMetrics.add(key);
        chip.classList.add('selected');
    }
    updateRunButton();
}

function toggleDimension(key, chip) {
    if (state.selectedDimensions.has(key)) {
        state.selectedDimensions.delete(key);
        chip.classList.remove('selected');
    } else {
        state.selectedDimensions.add(key);
        chip.classList.add('selected');
    }
    updateRunButton();
}

function updateRunButton() {
    const btn = document.getElementById('btn-run');
    btn.disabled = state.selectedMetrics.size === 0;
}

// ---- Navigation ----

function setupNavigation() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            document.getElementById(`view-${view}`).classList.add('active');

            if (view === 'catalog') loadCatalog();
        });
    });
}

// ---- Actions ----

function setupActions() {
    // Explore view
    document.getElementById('btn-run').addEventListener('click', runSemanticQuery);
    document.getElementById('btn-clear').addEventListener('click', clearQuery);
    document.getElementById('btn-toggle-chart').addEventListener('click', toggleChart);
    document.getElementById('btn-show-sql').addEventListener('click', toggleSqlPreview);
    document.getElementById('btn-export-csv').addEventListener('click', () => exportCSV(state.lastResult));

    // SQL view
    document.getElementById('btn-run-sql').addEventListener('click', runRawSql);
    document.getElementById('btn-export-sql-csv').addEventListener('click', () => {
        const table = document.getElementById('sql-results-table');
        exportTableCSV(table);
    });

    // Ctrl+Enter in SQL editor
    document.getElementById('sql-editor').addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            runRawSql();
        }
    });
}

// ---- Semantic Query ----

async function runSemanticQuery() {
    const btn = document.getElementById('btn-run');
    btn.textContent = 'Executando...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                metrics: [...state.selectedMetrics],
                dimensions: [...state.selectedDimensions],
                order_by: state.selectedMetrics.size > 0
                    ? [{ field: [...state.selectedMetrics][0], direction: 'desc' }]
                    : [],
                limit: 100,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            alert(`Erro: ${err.detail}`);
            return;
        }

        const data = await res.json();
        state.lastResult = data;
        state.showChart = data.chart_suggestion.type !== 'table';
        state.showSql = false;

        renderResults(data);
    } catch (e) {
        alert(`Erro de conexao: ${e.message}`);
    } finally {
        btn.textContent = 'Executar';
        updateRunButton();
    }
}

function clearQuery() {
    state.selectedMetrics.clear();
    state.selectedDimensions.clear();
    state.lastResult = null;

    document.querySelectorAll('.chip').forEach(c => c.classList.remove('selected'));
    document.getElementById('results').classList.add('hidden');
    updateRunButton();
    destroyChart();
}

// ---- Render Results ----

function renderResults(data) {
    const resultsEl = document.getElementById('results');
    resultsEl.classList.remove('hidden');

    // Meta badges
    document.getElementById('row-count').textContent = `${data.row_count} resultado${data.row_count !== 1 ? 's' : ''}`;
    document.getElementById('chart-type-badge').textContent = chartLabel(data.chart_suggestion.type);

    // SQL
    document.getElementById('sql-code').textContent = data.sql;

    // Table
    renderTable(data.columns, data.data, 'table-head', 'table-body');

    // Chart
    if (state.showChart && data.chart_suggestion.type !== 'table') {
        renderChart(data);
        document.getElementById('chart-container').classList.remove('hidden');
        document.getElementById('table-container').classList.add('hidden');
    } else {
        document.getElementById('chart-container').classList.add('hidden');
        document.getElementById('table-container').classList.remove('hidden');
    }
}

function renderTable(columns, data, headId, bodyId) {
    const thead = document.getElementById(headId);
    const tbody = document.getElementById(bodyId);

    thead.innerHTML = '<tr>' + columns.map(c => `<th>${c.display_name}</th>`).join('') + '</tr>';

    tbody.innerHTML = data.map(row =>
        '<tr>' + columns.map(c => {
            const val = row[c.display_name];
            const isMetric = c.type === 'metric';
            const formatted = formatValue(val, c.format);
            return `<td${isMetric ? ' class="metric-cell"' : ''}>${formatted}</td>`;
        }).join('') + '</tr>'
    ).join('');
}

function formatValue(val, format) {
    if (val === null || val === undefined) return '-';

    if (typeof val === 'number') {
        if (format === 'currency') {
            return 'R$ ' + val.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        if (format === 'percent') {
            return (val * 100).toFixed(1) + '%';
        }
        return val.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
    }

    // Date handling
    if (typeof val === 'string' && /^\d{4}-\d{2}-\d{2}/.test(val)) {
        const d = new Date(val);
        return d.toLocaleDateString('pt-BR', { year: 'numeric', month: 'short' });
    }

    return String(val);
}

function chartLabel(type) {
    const labels = { bar: 'Barras', line: 'Linha', pie: 'Pizza', table: 'Tabela' };
    return labels[type] || type;
}

// ---- Chart ----

function renderChart(data) {
    destroyChart();

    const ctx = document.getElementById('chart-canvas').getContext('2d');
    const suggestion = data.chart_suggestion;
    const columns = data.columns;
    const rows = data.data;

    // Dimensions are labels, metrics are datasets
    const dimCols = columns.filter(c => c.type === 'dimension');
    const metCols = columns.filter(c => c.type === 'metric');

    if (dimCols.length === 0 || metCols.length === 0) return;

    const labels = rows.map(r => {
        const val = r[dimCols[0].display_name];
        if (typeof val === 'string' && /^\d{4}-\d{2}-\d{2}/.test(val)) {
            return new Date(val).toLocaleDateString('pt-BR', { year: 'numeric', month: 'short' });
        }
        return String(val);
    });

    const palette = ['#5B8A72', '#E07A5F', '#6C8EBF', '#D4A574', '#7B9EA8', '#C97B84'];

    const datasets = metCols.map((col, i) => ({
        label: col.display_name,
        data: rows.map(r => r[col.display_name]),
        backgroundColor: suggestion.type === 'pie'
            ? palette.slice(0, rows.length)
            : palette[i % palette.length] + (suggestion.type === 'bar' ? 'CC' : 'FF'),
        borderColor: palette[i % palette.length],
        borderWidth: suggestion.type === 'line' ? 2 : 1,
        tension: 0.3,
        fill: false,
    }));

    state.chartInstance = new Chart(ctx, {
        type: suggestion.type === 'pie' ? 'pie' : suggestion.type,
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: metCols.length > 1 || suggestion.type === 'pie',
                    position: 'bottom',
                    labels: {
                        font: { family: 'Inter', size: 12 },
                        padding: 16,
                    }
                },
            },
            scales: suggestion.type === 'pie' ? {} : {
                x: {
                    grid: { display: false },
                    ticks: { font: { family: 'Inter', size: 11 } },
                },
                y: {
                    beginAtZero: true,
                    grid: { color: '#E4E3DF' },
                    ticks: { font: { family: 'Inter', size: 11 } },
                },
            },
        },
    });
}

function destroyChart() {
    if (state.chartInstance) {
        state.chartInstance.destroy();
        state.chartInstance = null;
    }
}

function toggleChart() {
    const chartEl = document.getElementById('chart-container');
    const tableEl = document.getElementById('table-container');

    if (chartEl.classList.contains('hidden')) {
        if (state.lastResult && state.lastResult.chart_suggestion.type !== 'table') {
            renderChart(state.lastResult);
            chartEl.classList.remove('hidden');
            tableEl.classList.add('hidden');
        }
    } else {
        chartEl.classList.add('hidden');
        tableEl.classList.remove('hidden');
    }
}

function toggleSqlPreview() {
    const el = document.getElementById('sql-preview');
    el.classList.toggle('hidden');
}

// ---- Raw SQL ----

async function runRawSql() {
    const editor = document.getElementById('sql-editor');
    const sql = editor.value.trim();
    if (!sql) return;

    const btn = document.getElementById('btn-run-sql');
    btn.textContent = 'Executando...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/sql`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sql }),
        });

        if (!res.ok) {
            const err = await res.json();
            alert(`Erro: ${err.detail}`);
            return;
        }

        const data = await res.json();
        const resultsEl = document.getElementById('sql-results');
        resultsEl.classList.remove('hidden');

        document.getElementById('sql-row-count').textContent = `${data.row_count} resultado${data.row_count !== 1 ? 's' : ''}`;
        renderTable(data.columns, data.data, 'sql-table-head', 'sql-table-body');
    } catch (e) {
        alert(`Erro de conexao: ${e.message}`);
    } finally {
        btn.textContent = 'Executar SQL';
        btn.disabled = false;
    }
}

// ---- Export ----

function exportCSV(data) {
    if (!data || !data.data.length) return;

    const cols = data.columns.map(c => c.display_name);
    const rows = data.data.map(r => cols.map(c => {
        const v = r[c];
        if (typeof v === 'string' && v.includes(',')) return `"${v}"`;
        return v;
    }));

    const csv = [cols.join(','), ...rows.map(r => r.join(','))].join('\n');
    downloadFile(csv, 'enkly-export.csv', 'text/csv');
}

function exportTableCSV(table) {
    const rows = [];
    const headers = [];
    table.querySelectorAll('thead th').forEach(th => headers.push(th.textContent));
    rows.push(headers.join(','));

    table.querySelectorAll('tbody tr').forEach(tr => {
        const cells = [];
        tr.querySelectorAll('td').forEach(td => {
            const v = td.textContent;
            cells.push(v.includes(',') ? `"${v}"` : v);
        });
        rows.push(cells.join(','));
    });

    downloadFile(rows.join('\n'), 'enkly-sql-export.csv', 'text/csv');
}

function downloadFile(content, filename, type) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

// ---- Catalog ----

let catalogData = [];
let selectedTable = null;

async function loadCatalog() {
    try {
        const res = await fetch(`${API}/catalog`);
        if (!res.ok) throw new Error('Failed to load catalog');
        catalogData = await res.json();
        renderCatalogList();
    } catch (e) {
        console.error(e);
    }
}

function renderCatalogList() {
    const list = document.getElementById('catalog-list');
    list.innerHTML = '';

    for (const entry of catalogData) {
        const item = document.createElement('div');
        item.className = 'catalog-item' + (selectedTable === entry.table_name ? ' active' : '');
        item.dataset.table = entry.table_name;

        const ext = entry.source?.type || '?';
        item.innerHTML = `
            <div class="catalog-item-icon">${ext}</div>
            <div class="catalog-item-info">
                <div class="catalog-item-name">${entry.table_name}</div>
                <div class="catalog-item-sub">${entry.row_count.toLocaleString('pt-BR')} linhas · ${entry.column_count} colunas</div>
            </div>`;

        item.addEventListener('click', () => showTableDetail(entry));
        list.appendChild(item);
    }
}

function showTableDetail(entry) {
    selectedTable = entry.table_name;
    renderCatalogList();

    document.getElementById('catalog-empty-state').classList.add('hidden');
    const panel = document.getElementById('catalog-detail-panel');
    panel.classList.remove('hidden');

    document.getElementById('detail-table-name').textContent = entry.table_name;
    document.getElementById('detail-rows').textContent = `${entry.row_count.toLocaleString('pt-BR')} linhas`;
    document.getElementById('detail-cols').textContent = `${entry.column_count} colunas`;

    const typeBadge = document.getElementById('detail-type');
    typeBadge.textContent = (entry.source?.type || 'unknown').toUpperCase();

    // Render columns
    const colsContainer = document.getElementById('detail-columns');
    colsContainer.innerHTML = '';
    for (const col of entry.columns) {
        const typeKey = col.type.split('(')[0].toLowerCase().replace(/\s/g, '');
        const row = document.createElement('div');
        row.className = 'column-row';
        row.innerHTML = `
            <span class="column-name">${col.name}</span>
            <span class="column-type-badge type-${typeKey}">${col.type}</span>`;
        colsContainer.appendChild(row);
    }

    // Hide sample until requested
    document.getElementById('detail-sample-section').classList.add('hidden');
    document.getElementById('btn-load-sample').onclick = () => loadSample(entry.table_name);
}

async function loadSample(tableName) {
    try {
        const res = await fetch(`${API}/catalog/${tableName}/sample`);
        if (!res.ok) throw new Error('Failed to load sample');
        const data = await res.json();

        const section = document.getElementById('detail-sample-section');
        section.classList.remove('hidden');

        const rawCols = data.columns.map(c => ({ ...c, type: 'raw', format: undefined }));
        renderTable(rawCols, data.data, 'detail-sample-head', 'detail-sample-body');
    } catch (e) {
        console.error(e);
    }
}

// ---- Upload Modal ----

let pendingFile = null;

function setupUploadModal() {
    const openBtn = document.getElementById('btn-add-source');
    const overlay = document.getElementById('upload-modal');
    const closeBtn = document.getElementById('btn-modal-close');
    const cancelBtn = document.getElementById('btn-cancel-upload');
    const dropZone = document.getElementById('upload-drop-zone');
    const fileInput = document.getElementById('upload-file-input');
    const browseBtn = document.getElementById('btn-browse');
    const changeBtn = document.getElementById('btn-change-file');
    const confirmBtn = document.getElementById('btn-confirm-upload');
    const doneBtn = document.getElementById('btn-upload-done');

    openBtn.addEventListener('click', () => openUploadModal());
    closeBtn.addEventListener('click', closeUploadModal);
    cancelBtn.addEventListener('click', closeUploadModal);
    doneBtn.addEventListener('click', () => {
        closeUploadModal();
        loadCatalog();
    });

    browseBtn.addEventListener('click', () => fileInput.click());
    changeBtn.addEventListener('click', () => {
        fileInput.value = '';
        fileInput.click();
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) onFileSelected(fileInput.files[0]);
    });

    // Drag and drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file) onFileSelected(file);
    });

    // Click on drop zone
    dropZone.addEventListener('click', (e) => {
        if (e.target !== browseBtn) fileInput.click();
    });

    confirmBtn.addEventListener('click', doUpload);
}

function openUploadModal() {
    pendingFile = null;
    document.getElementById('upload-modal').classList.remove('hidden');
    document.getElementById('upload-drop-zone').classList.remove('hidden');
    document.getElementById('upload-form').classList.add('hidden');
    document.getElementById('upload-success').classList.add('hidden');
    document.getElementById('upload-preview').classList.add('hidden');
    document.getElementById('input-table-name').value = '';
}

function closeUploadModal() {
    document.getElementById('upload-modal').classList.add('hidden');
    pendingFile = null;
}

function onFileSelected(file) {
    const allowed = ['csv', 'json', 'parquet'];
    const ext = file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) {
        alert(`Formato não suportado: .${ext}. Use CSV, JSON ou Parquet.`);
        return;
    }

    pendingFile = file;
    document.getElementById('upload-drop-zone').classList.add('hidden');
    document.getElementById('upload-form').classList.remove('hidden');
    document.getElementById('upload-success').classList.add('hidden');
    document.getElementById('upload-filename').textContent = file.name;

    // Auto-derive table name from filename
    const suggested = file.name
        .replace(/\.[^.]+$/, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
    document.getElementById('input-table-name').value = suggested;
}

async function doUpload() {
    if (!pendingFile) return;

    const tableName = document.getElementById('input-table-name').value.trim();
    if (!tableName) {
        alert('Informe o nome da tabela.');
        return;
    }

    const btn = document.getElementById('btn-confirm-upload');
    btn.textContent = 'Enviando...';
    btn.disabled = true;

    const formData = new FormData();
    formData.append('file', pendingFile);
    formData.append('table_name', tableName);

    try {
        const res = await fetch(`${API}/sources/upload`, {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json();
            alert(`Erro: ${err.detail}`);
            return;
        }

        const data = await res.json();

        document.getElementById('upload-form').classList.add('hidden');
        const successEl = document.getElementById('upload-success');
        successEl.classList.remove('hidden');
        document.getElementById('upload-success-msg').textContent =
            `"${data.table_name}" adicionado — ${data.row_count.toLocaleString('pt-BR')} linhas, ${data.column_count} colunas`;

        await loadCatalog();
    } catch (e) {
        alert(`Erro de conexão: ${e.message}`);
    } finally {
        btn.textContent = 'Adicionar fonte';
        btn.disabled = false;
    }
}
